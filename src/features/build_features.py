import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.db import engine

def construir_features(fecha_corte: str, horizonte_dias: int = 30) -> pd.DataFrame:
    """
    Construye dataset de features para modelado predictivo.
    Una fila = un activo en una fecha de corte.
    Solo información ANTES de fecha_corte (evita fuga de información).
    
    Devuelve SOLO columnas que existen en features_activo_fecha de BD.
    
    ⭐ FIX FASE 1.1: Target corregido para evitar leakage
       - Antes: [t, t+N) → incluía día t
       - Ahora: (t, t+N] → desde t+1 hasta t+N inclusive
    """
    fecha = pd.Timestamp(fecha_corte)

    # Cargar datos
    activos = pd.read_sql("""
        SELECT * FROM activos
        WHERE UPPER(COALESCE(estado_actual, 'Activo')) = 'ACTIVO' 
    """, engine)    
    ots = pd.read_sql("SELECT * FROM ordenes_trabajo", engine)

    # Convertir fechas a datetime SIN timezone (para evitar conflictos)
    activos["fecha_alta_flota"] = pd.to_datetime(activos["fecha_alta_flota"], errors="coerce").dt.tz_localize(None)
    ots["fecha_apertura"] = pd.to_datetime(ots["fecha_apertura"], errors="coerce").dt.tz_localize(None)
    ots["fecha_cierre"] = pd.to_datetime(ots["fecha_cierre"], errors="coerce").dt.tz_localize(None)

    # Filtrar OTs ANTES de fecha_corte (estrictamente < t)
    ots_pasado = ots[ots["fecha_apertura"] < fecha].copy()

    # Base: información de activos (solo activo_id)
    features = activos[["activo_id"]].copy()

    features["fecha_corte"] = fecha.date()
    features["horizonte_dias"] = horizonte_dias

    # Features: edad
    features["edad_dias"] = (fecha - activos["fecha_alta_flota"]).dt.days.fillna(-1).astype(int)
    features["edad_anos"] = features["edad_dias"] / 365.25

    # Última OT
    if len(ots_pasado) > 0:
        ultima_ot = (ots_pasado
                     .sort_values("fecha_apertura")
                     .groupby("activo_id")
                     .agg(fecha_ultima_ot=("fecha_apertura", "last"),
                          odometro_actual=("odometro_km", "last"),
                          horometro_actual=("horometro_h", "last")))
        features = features.merge(ultima_ot, on="activo_id", how="left")
        features["dias_desde_ultima_ot"] = (fecha - features["fecha_ultima_ot"]).dt.days.fillna(-1).astype(int)
        features = features.drop(columns=["fecha_ultima_ot"])
    else:
        features["odometro_actual"] = -1
        features["horometro_actual"] = -1
        features["dias_desde_ultima_ot"] = -1

    # km_dia_promedio y horas_dia_promedio
    features["km_dia_promedio"] = -1
    features["horas_dia_promedio"] = -1

    # Ventanas FIJAS: [7, 30, 90] para TODOS los horizontes
    dias_ventanas = [7, 30, 90]   

    # Conteo de OTs por ventana
    for dias in dias_ventanas:
        inicio = fecha - pd.Timedelta(days=dias)
        ots_ventana = ots_pasado[ots_pasado["fecha_apertura"] >= inicio]

        # Total OTs
        total_ots = ots_ventana.groupby("activo_id").size().rename(f"count_ot_{dias}d")
        features = features.merge(total_ots, on="activo_id", how="left")

        # OTs correctivas
        if len(ots_ventana) > 0:
            ots_correctivas = ots_ventana[
                ots_ventana["tipo_ot"].str.lower().isin(["correctiva", "correctivo", "emergency"])
            ]
            count_correctivas = ots_correctivas.groupby("activo_id").size().rename(f"count_correctivas_{dias}d")
            features = features.merge(count_correctivas, on="activo_id", how="left")
        
        # Costo total
        if len(ots_ventana) > 0:
            costo_total = ots_ventana.groupby("activo_id")["costo_total_clp"].sum().rename(f"costo_total_{dias}d")
            features = features.merge(costo_total, on="activo_id", how="left")
        else:
            features[f"costo_total_{dias}d"] = 0

    # MTBF
    # ⚠️ TODO FASE 2.1: Calcular en lugar de hardcodear
    # MTBF basado en la mayor ventana del horizonte
    max_ventana = max(dias_ventanas)
    features[f"mtbf_{max_ventana}d"] = -1

    # Días desde última correctiva por sistema
    # ⚠️ TODO FASE 2.1: Calcular con JOIN a taxonomia_fallas
    for sistema, col_name in [("motor", "dias_ult_correctiva_motor"),
                               ("frenos", "dias_ult_correctiva_frenos"),
                               ("transmision", "dias_ult_correctiva_transmision")]:
        features[col_name] = -1

    # ========================================================================
    # ⭐ TARGET CORREGIDO (FASE 1.1)
    # ========================================================================
    # Pregunta: "¿Habrá correctiva entre t+1 y t+N?"
    #
    # ANTES (bug):  [fecha, fecha+N)  →  incluía día t (leakage sutil)
    # AHORA (fix): (fecha, fecha+N]   →  desde t+1 hasta t+N inclusive
    #
    # Esto evita que una OT que se abre EN fecha_corte se use para predecir
    # a sí misma (data leakage).
    # ========================================================================
    
    fin = fecha + pd.Timedelta(days=horizonte_dias)
    ots_futuras = ots[
        (ots["fecha_apertura"] > fecha) &       # ⭐ FIX: > en lugar de >=
        (ots["fecha_apertura"] <= fin)          # ⭐ FIX: <= en lugar de <
    ]
    ots_correctivas_futuras = ots_futuras[
        ots_futuras["tipo_ot"].str.lower().isin(["correctiva", "correctivo", "emergency"])
    ]

    activos_con_falla = set(ots_correctivas_futuras["activo_id"].unique())
    features["target"] = features["activo_id"].isin(activos_con_falla).astype(int)

    # Rellenar NaNs
    numeric_cols = features.select_dtypes(include=[np.number]).columns
    features[numeric_cols] = features[numeric_cols].fillna(-1)

    # ORDEN FINAL DE COLUMNAS (exacto a la BD)
    # GENERAR COLUMNAS DINÁMICAMENTE SEGÚN VENTANAS
    columnas_count_ot = [f"count_ot_{d}d" for d in dias_ventanas]
    columnas_count_correctivas = [f"count_correctivas_{d}d" for d in dias_ventanas]
    columnas_costo = [f"costo_total_{d}d" for d in dias_ventanas]
    max_ventana = max(dias_ventanas)
    
    columnas_orden = [
        "activo_id", "fecha_corte", "horizonte_dias",
        "edad_dias", "edad_anos",
        "odometro_actual", "horometro_actual",
        "km_dia_promedio", "horas_dia_promedio",
        "dias_desde_ultima_ot",
    ] + columnas_count_ot + columnas_count_correctivas + columnas_costo + [
        f"mtbf_{max_ventana}d",
        "dias_ult_correctiva_motor", "dias_ult_correctiva_frenos", "dias_ult_correctiva_transmision",
        "target"
    ]
    # Seleccionar solo las columnas que existen
    features = features[[col for col in columnas_orden if col in features.columns]]

    return features

def generar_reporte_features(df: pd.DataFrame) -> None:
    print("\n" + "="*70)
    print("📊 REPORTE DE FEATURE ENGINEERING")
    print("="*70)
    print(f"\nDataset shape: {df.shape[0]} filas × {df.shape[1]} columnas")
    if len(df) > 0:
        print(f"Fecha de corte: {df['fecha_corte'].iloc[0]}")
        print(f"Target distribution:\n{df['target'].value_counts()}")
        print(f"Tasa de eventos: {df['target'].mean()*100:.2f}%")
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    df_features = construir_features("2024-05-15", horizonte_dias=5)
    print(df_features[["activo_id", "edad_dias", "count_ot_30d", "target"]].head(10))
    generar_reporte_features(df_features)
