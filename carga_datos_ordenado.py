"""
Módulo para cargar datos ordenadamente respetando integridad referencial
Usa SQLAlchemy engine de main.py
"""

import pandas as pd


def carga_datos_ordenado(ruta_csv_activos, ruta_csv_ot, ruta_csv_repuestos):
    """
    Carga datos de tres CSVs en orden respetando integridad referencial

    Args:
        ruta_csv_activos: Ruta al archivo activos.csv
        ruta_csv_ot: Ruta al archivo ordenes_trabajo.csv
        ruta_csv_repuestos: Ruta al archivo repuestos_consumidos.csv
    """
    from src.db import engine

    try:
        # ===== PASO 1: CARGAR ACTIVOS =====
        print("\n📦 Cargando ACTIVOS...")
        df_activos = pd.read_csv(ruta_csv_activos)

        # Validar columnas básicas
        if 'activo_id' not in df_activos.columns:
            raise ValueError("Columna 'activo_id' faltante en activos.csv")

        # Limpiar NaN
        df_activos = df_activos.where(pd.notna(df_activos), None)

        # Cargar a BD
        df_activos.to_sql(
            "activos",
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000
        )
        print(f"✅ {len(df_activos)} activos cargados exitosamente")

        # ===== PASO 2: CARGAR ORDENES DE TRABAJO =====
        print("\n📋 Cargando ORDENES_TRABAJO...")
        df_ot = pd.read_csv(ruta_csv_ot)

        # Validar columnas esperadas
        columnas_obligatorias_ot = {'ot_id', 'activo_id', 'fecha_apertura'}
        columnas_faltantes = columnas_obligatorias_ot - set(df_ot.columns)
        if columnas_faltantes:
            raise ValueError(f"Columnas faltantes en ordenes_trabajo.csv: {sorted(list(columnas_faltantes))}")

        # Validar integridad referencial: activo_id debe existir en activos
        activos_validos = set(df_activos['activo_id'].values)
        activos_en_ot = set(df_ot['activo_id'].unique())
        activos_no_existentes = activos_en_ot - activos_validos

        if activos_no_existentes:
            raise ValueError(f"❌ IDs de activos no válidos en ordenes_trabajo: {sorted(list(activos_no_existentes))}")

        # Limpiar NaN
        df_ot = df_ot.where(pd.notna(df_ot), None)

        # Cargar a BD
        df_ot.to_sql(
            "ordenes_trabajo",
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000
        )
        print(f"✅ {len(df_ot)} órdenes de trabajo cargadas exitosamente")

        # ===== PASO 3: CARGAR REPUESTOS CONSUMIDOS =====
        print("\n🔧 Cargando REPUESTOS_CONSUMIDOS...")
        df_repuestos = pd.read_csv(ruta_csv_repuestos)

        # Validar columna obligatoria
        if 'ot_id' not in df_repuestos.columns:
            raise ValueError("Columna 'ot_id' faltante en repuestos_consumidos.csv")

        # Validar integridad referencial: ot_id debe existir en ordenes_trabajo
        ot_validos = set(df_ot['ot_id'].values)
        ot_en_repuestos = set(df_repuestos['ot_id'].unique())
        ot_no_existentes = ot_en_repuestos - ot_validos

        if ot_no_existentes:
            raise ValueError(f"❌ IDs de órdenes de trabajo no válidos en repuestos: {sorted(list(ot_no_existentes))}")

        # Limpiar NaN
        df_repuestos = df_repuestos.where(pd.notna(df_repuestos), None)

        # Cargar a BD (NO incluir consumo_id ni created_at - se generan automáticamente)
        df_repuestos.to_sql(
            "repuestos_consumidos",
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000
        )
        print(f"✅ {len(df_repuestos)} repuestos cargados exitosamente")

        # ===== RESUMEN FINAL =====
        print("\n" + "="*70)
        print("✅ CARGA DE DATOS COMPLETADA EXITOSAMENTE")
        print("="*70)
        print(f"  • Activos: {len(df_activos)}")
        print(f"  • Órdenes de Trabajo: {len(df_ot)}")
        print(f"  • Repuestos: {len(df_repuestos)}")
        print("="*70)

    except ValueError as e:
        print(f"\n❌ ERROR DE VALIDACIÓN: {str(e)}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR AL CARGAR DATOS: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
