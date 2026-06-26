"""
Módulo para cargar datos ordenadamente respetando integridad referencial
Usa SQLAlchemy engine de main.py
"""

import pandas as pd


def carga_datos_ordenado(ruta_csv_activos, ruta_csv_ot, ruta_csv_repuestos,
                         ruta_csv_falla='data/raw/ot_falla_evento.csv'):
    """
    Carga datos de cuatro CSVs en orden respetando integridad referencial

    Args:
        ruta_csv_activos: Ruta al archivo activos.csv
        ruta_csv_ot: Ruta al archivo ordenes_trabajo.csv
        ruta_csv_repuestos: Ruta al archivo repuestos_consumidos.csv
        ruta_csv_falla: Ruta al archivo ot_falla_evento.csv
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

        # ===== PASO 4: CARGAR OT_FALLA_EVENTO =====
        # Esquema real:
        #   id_evento     bigint   PK (autogenerado, NO incluir)
        #   ot_id         text     FK -> ordenes_trabajo (nullable)
        #   taxonomia_id  uuid     FK -> taxonomia_fallas (NOT NULL, obligatoria)
        #   activo_id     text     (sin FK declarada)
        #   ... resto de columnas de contexto
        print("\n⚠️  Cargando OT_FALLA_EVENTO...")
        df_falla = pd.read_csv(ruta_csv_falla)

        # Validar columnas obligatorias del esquema real
        columnas_obligatorias_falla = {'taxonomia_id'}
        columnas_faltantes_falla = columnas_obligatorias_falla - set(df_falla.columns)
        if columnas_faltantes_falla:
            raise ValueError(
                f"Columnas obligatorias faltantes en ot_falla_evento.csv: "
                f"{sorted(list(columnas_faltantes_falla))}. "
                f"'taxonomia_id' es NOT NULL con FK a taxonomia_fallas."
            )

        # id_evento es PK bigint autogenerada: si viene en el CSV, descartarla
        # para evitar colisiones con la secuencia de la BD.
        if 'id_evento' in df_falla.columns:
            print("   ℹ️  Columna 'id_evento' presente en CSV → se descarta (PK autogenerada)")
            df_falla = df_falla.drop(columns=['id_evento'])

        # Validar integridad referencial: ot_id (cuando no es nulo) debe existir en ordenes_trabajo
        if 'ot_id' in df_falla.columns:
            ot_en_falla = set(df_falla['ot_id'].dropna().unique())
            ot_falla_no_existentes = ot_en_falla - ot_validos
            if ot_falla_no_existentes:
                raise ValueError(f"❌ IDs de órdenes de trabajo no válidos en ot_falla_evento: {sorted(list(ot_falla_no_existentes))}")

        # Validar integridad referencial: taxonomia_id debe existir en el catálogo persistente.
        # taxonomia_fallas NO se carga aquí (es catálogo de referencia); se valida contra la BD.
        taxonomias_validas = set(
            pd.read_sql("SELECT taxonomia_id FROM taxonomia_fallas", engine)['taxonomia_id']
            .astype(str)
            .values
        )
        if not taxonomias_validas:
            raise ValueError(
                "❌ La tabla taxonomia_fallas está vacía. Es un catálogo de referencia "
                "y debe estar poblado antes de cargar ot_falla_evento."
            )

        tax_en_falla = set(df_falla['taxonomia_id'].dropna().astype(str).unique())
        tax_no_existentes = tax_en_falla - taxonomias_validas
        if tax_no_existentes:
            raise ValueError(f"❌ taxonomia_id no válidos en ot_falla_evento (no existen en taxonomia_fallas): {sorted(list(tax_no_existentes))}")

        # Validar que no haya taxonomia_id nulos (columna NOT NULL)
        n_tax_nulos = int(df_falla['taxonomia_id'].isna().sum())
        if n_tax_nulos > 0:
            raise ValueError(f"❌ {n_tax_nulos} filas en ot_falla_evento.csv tienen taxonomia_id nulo (columna NOT NULL)")

        # Limpiar NaN
        df_falla = df_falla.where(pd.notna(df_falla), None)

        # Cargar a BD
        df_falla.to_sql(
            "ot_falla_evento",
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000
        )
        print(f"✅ {len(df_falla)} eventos de falla cargados exitosamente")

        # ===== RESUMEN FINAL =====
        print("\n" + "="*70)
        print("✅ CARGA DE DATOS COMPLETADA EXITOSAMENTE")
        print("="*70)
        print(f"  • Activos: {len(df_activos)}")
        print(f"  • Órdenes de Trabajo: {len(df_ot)}")
        print(f"  • Repuestos: {len(df_repuestos)}")
        print(f"  • Eventos de Falla: {len(df_falla)}")
        print("="*70)

    except ValueError as e:
        print(f"\n❌ ERROR DE VALIDACIÓN: {str(e)}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR AL CARGAR DATOS: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
