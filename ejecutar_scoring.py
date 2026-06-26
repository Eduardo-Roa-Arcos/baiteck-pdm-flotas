# src/pipelines/scoring_diario.py
import sys
import json
from datetime import date
from typing import Optional
import numpy as np
import pandas as pd
import joblib
from sqlalchemy import text
from src.features.build_features import construir_features
from src.db import engine

# ============================================================================
# UMBRALES DE PRIORIDAD
# ============================================================================

DEFAULT_UMBRALES = {
    "P1_critica": 0.85,
    "P2_alta": 0.75,
    "P3_media": 0.50,
}

# ============================================================================
# RUTAS DEL MODELO ENTRENADO
# ============================================================================

MODEL_PATH = "models/modelo_xgb_v1.0.joblib"
METADATA_PATH = "models/metadata_xgb_v1.0.json"
MODELO_VERSION = "xgboost_v1.0"

# ============================================================================
# MAPEO DE COLUMNAS: Nombres Cortos (Modelo) → Nombres Largos (BD)
# ============================================================================
# El modelo fue entrenado con nombres cortos (ot_30d, ot_90d, etc.)
# Pero la BD y construir_features() devuelven nombres largos (count_ot_30d, etc.)
# Este mapeo traduce entre ambos mundos.
# ============================================================================

# Ventanas dinámicas (coinciden con build_features.py)
VENTANAS_POR_HORIZONTE = {
    7: [7, 14, 30],
    30: [30, 60, 90],
    90: [30, 60, 90],
}

def generar_mapeo_columnas(horizonte_dias: int) -> dict:
    """Genera mapeo dinámico según las ventanas reales [7, 30, 90]."""
    ventanas = [7, 30, 90]  # SIEMPRE [7, 30, 90]
    mapeo = {}
    for ventana in ventanas:
        mapeo[f'ot_{ventana}d'] = f'count_ot_{ventana}d'
        mapeo[f'corr_{ventana}d'] = f'count_correctivas_{ventana}d'
        mapeo[f'costo_{ventana}d'] = f'costo_total_{ventana}d'
    mapeo['mtbf_90d'] = 'mtbf_90d'  # MTBF también usa máxima ventana (90)
    return mapeo

# ============================================================================
# ATENUACIÓN POST-INTERVENCIÓN
# ============================================================================
# Regla operacional: una unidad en P1/P2 que pasó por taller con una OT
# correctiva o predictiva CERRADA recientemente debe bajar su probabilidad.
# El modelo XGBoost actual no lo refleja porque sus features
# (count_ot_30d, count_correctivas_30d, ...) son ventanas móviles que no
# distinguen "intervención reciente".
#
# Esta capa es un POST-PROCESAMIENTO DETERMINÍSTICO que se aplica entre la
# predicción del modelo y la persistencia en scoring_resultados.
#
# OPCIÓN A: La atenuación se aplica a cualquier unidad P1/P2 que tuvo OT
# correctiva o predictiva cerrada recientemente, SIN importar qué sistema
# se intervino. La justificación: una intervención correctiva es evidencia
# de que "conocemos mejor la unidad ahora"; el riesgo baja globalmente
# hasta que reporte nuevos síntomas.
#
# Granularidad: la atenuación se evalúa a nivel de OT, no de evento. Una
# OT (ordenes_trabajo) puede tener N eventos (ot_falla_evento) con
# distintos tipos. Para asignar UN único tipo a la OT se usa la jerarquía:
#
#   - Si la OT tiene ALGÚN evento con tipo_mantenimiento predictivo
#     → tipo_dominante = 'predictiva'.
#   - Si no, si tiene ALGÚN evento correctivo → 'correctiva'.
#   - Si no, si tiene algún evento preventivo o de inspección → 'preventiva'.
#     (preventivas se descartan en OPCIÓN A; solo correctiva/predictiva)
#
# Reglas adicionales:
#   - Solo se evalúa para activos en P1_critica o P2_alta.
#   - Se requiere fecha_cierre IS NOT NULL en ordenes_trabajo. Las fechas
#     de ot_falla_evento NO se consideran; la fecha de cierre válida es
#     siempre ordenes_trabajo.fecha_cierre.
#   - Solo entra en la atenuación si tipo_dominante IN ('correctiva',
#     'predictiva'). Preventivas se ignoran (no atienden el problema del
#     cliente: "no tiene sentido entrar todos los días al taller").
#   - dias_desde_cierre debe estar dentro de la ventana del tipo dominante.
#   - Si aplica, probabilidad_falla *= FACTOR_ATENUACION[tipo_dominante].
#   - La prioridad se recalcula con los mismos umbrales.
#
# Asume "presunción de éxito" de la intervención correctiva/predictiva.
# Cuando feedback_taller esté poblado, esta lógica puede refinarse para
# excluir intervenciones marcadas como "falsa alarma". Es una solución de
# corto plazo hasta que Fase 2 (features por sistema en build_features.py
# + reentrenamiento) entregue la solución estructural.
# ============================================================================

# Conjuntos de valores reconocidos para ofe.tipo_mantenimiento (case-insensitive).
TIPOS_PREDICTIVOS = {"predictiva", "predictivo"}
TIPOS_CORRECTIVOS = {"correctiva", "correctivo", "emergency"}
TIPOS_PREVENTIVOS = {"preventiva", "preventivo", "mantenimiento",
                     "inspeccion", "inspección"}

# Ventana temporal (en días) en la que una OT cerrada se considera reciente
# para efectos de atenuación, según su tipo dominante.
VENTANA_DIAS = {
    "predictiva": 30,
    "correctiva": 30,
    "preventiva": 14,
}

# Multiplicador sobre probabilidad_falla cuando la OT reciente toca el
# sistema en riesgo.
FACTOR_ATENUACION = {
    "predictiva": 0.20,
    "correctiva": 0.30,
    "preventiva": 0.50,
}


def obtener_umbrales(modelo_version: str) -> dict:
    """Carga umbrales desde Supabase. Si no existen, usa DEFAULT_UMBRALES."""
    try:
        query = text("""
            SELECT p1_critica, p2_alta, p3_media
            FROM umbrales_prioridad
            WHERE modelo_version = :version AND activo = TRUE
            ORDER BY fecha_vigencia DESC
            LIMIT 1
        """)
        with engine.connect() as conn:
            result = conn.execute(query, {"version": modelo_version}).fetchone()
        if result:
            return {
                "P1_critica": float(result[0]),
                "P2_alta": float(result[1]),
                "P3_media": float(result[2])
            }
    except Exception:
        pass
    return DEFAULT_UMBRALES


def prioridad(p: float, umbrales: dict) -> str:
    """Asigna prioridad segun umbrales configurables."""
    if p >= umbrales["P1_critica"]:
        return "P1_critica"
    if p >= umbrales["P2_alta"]:
        return "P2_alta"
    if p >= umbrales["P3_media"]:
        return "P3_media"
    return "P4_baja"


def asegurar_columna_sistema_en_riesgo() -> None:
    """Crea la columna sistema_en_riesgo en scoring_resultados si no existe."""
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE scoring_resultados
            ADD COLUMN IF NOT EXISTS sistema_en_riesgo TEXT;
        """))


def asegurar_columnas_trazabilidad() -> None:
    """Crea las columnas de trazabilidad de la atenuación post-intervención si
    no existen. Idempotente: se puede ejecutar en cada scoring sin efecto."""
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE scoring_resultados
            ADD COLUMN IF NOT EXISTS prioridad_pre_decay TEXT;
        """))
        conn.execute(text("""
            ALTER TABLE scoring_resultados
            ADD COLUMN IF NOT EXISTS ajuste_intervencion_reciente BOOLEAN DEFAULT FALSE;
        """))
        conn.execute(text("""
            ALTER TABLE scoring_resultados
            ADD COLUMN IF NOT EXISTS tipo_mant_atenuacion TEXT;
        """))
        conn.execute(text("""
            ALTER TABLE scoring_resultados
            ADD COLUMN IF NOT EXISTS dias_desde_intervencion INTEGER;
        """))


def obtener_sistema_en_riesgo_por_activo(fecha_corte: str) -> pd.DataFrame:
    """
    Para cada activo, devuelve el sistema del ultimo evento de falla clasificado.

    Estrategia:
    - JOIN ot_falla_evento <-> taxonomia_fallas (solo eventos con sistema clasificado)
    - LEFT JOIN ordenes_trabajo (para fallback de activo_id y fecha cuando vienen NULL)
    - activo_id  = COALESCE(ot_falla_evento.activo_id, ordenes_trabajo.activo_id)
    - fecha_efectiva = COALESCE(ot_falla_evento.fecha_evento, ordenes_trabajo.fecha_apertura)
    - Por cada activo se queda el evento mas reciente <= fecha_corte
    """
    query = text("""
        WITH eventos_efectivos AS (
            SELECT
                COALESCE(ofe.activo_id, ot.activo_id) AS activo_id,
                COALESCE(ofe.fecha_evento::date, ot.fecha_apertura::date) AS fecha_efectiva,
                tf.sistema AS sistema
            FROM ot_falla_evento ofe
            JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
            LEFT JOIN ordenes_trabajo ot ON ofe.ot_id = ot.ot_id
            WHERE tf.sistema IS NOT NULL
              AND TRIM(tf.sistema) <> ''
        )
        SELECT DISTINCT ON (activo_id)
            activo_id,
            sistema AS sistema_en_riesgo
        FROM eventos_efectivos
        WHERE activo_id IS NOT NULL
          AND fecha_efectiva IS NOT NULL
          AND fecha_efectiva <= :fecha_corte
        ORDER BY activo_id, fecha_efectiva DESC;
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"fecha_corte": fecha_corte})


def obtener_ot_correctiva_predictiva_reciente_por_activo(fecha_corte: str) -> pd.DataFrame:
    """
    Para cada activo, devuelve la OT MÁS RECIENTE CERRADA cuyo tipo dominante
    es correctiva o predictiva (se ignoran preventivas e inspecciones).

    Trabaja a NIVEL OT. Deriva el tipo agregando todos los eventos de
    la OT en ot_falla_evento con la jerarquía:
      - predictiva: si AL MENOS UN evento es predictivo.
      - correctiva: si no hay predictivos pero AL MENOS UNO es correctivo.
      - preventiva: si no hay predictivos ni correctivos, y hay preventivos
        o inspecciones.

    La fecha de cierre se lee SIEMPRE de ordenes_trabajo.fecha_cierre.
    Las fechas de ot_falla_evento no se consideran.

    Solo se incluyen OTs donde:
      - ordenes_trabajo.fecha_cierre IS NOT NULL y <= fecha_corte.
      - tipo_dominante IN ('predictiva', 'correctiva') — preventivas NO entran.

    A diferencia de la versión anterior, NO filtra por sistema. El retorno
    es una fila por activo (si la OT existe y cumple condiciones), no por
    combinación (activo, sistema). Esto porque OPCIÓN A: la atenuación
    aplica a cualquier P1/P2 si tuvo correctiva/predictiva reciente,
    independientemente del sistema en riesgo.

    El consumidor (aplicar_decay_post_intervencion) hace el match solo por
    activo_id y aplica la regla si el tipo es correctiva o predictiva.
    """
    query = text("""
        WITH eventos_ot_cerradas AS (
            -- Todos los eventos de OTs cerradas <= fecha_corte
            -- No filtramos por sistema; queremos cualquier evento de la OT
            SELECT
                ot.activo_id,
                ot.ot_id,
                ot.fecha_cierre::date AS fecha_cierre,
                LOWER(TRIM(COALESCE(ofe.tipo_mantenimiento, ''))) AS tipo_mant_lower
            FROM ordenes_trabajo ot
            JOIN ot_falla_evento ofe ON ofe.ot_id = ot.ot_id
            WHERE ot.fecha_cierre IS NOT NULL
              AND ot.fecha_cierre::date <= :fecha_corte
              AND ot.activo_id IS NOT NULL
        ),
        tipo_dominante_por_ot AS (
            -- Aplicar jerarquía: predictiva > correctiva > preventiva
            SELECT
                ot_id,
                CASE
                    WHEN BOOL_OR(tipo_mant_lower IN ('predictiva', 'predictivo'))
                        THEN 'predictiva'
                    WHEN BOOL_OR(tipo_mant_lower IN ('correctiva', 'correctivo', 'emergency'))
                        THEN 'correctiva'
                    WHEN BOOL_OR(tipo_mant_lower IN ('preventiva', 'preventivo', 'mantenimiento',
                                                    'inspeccion', 'inspección'))
                        THEN 'preventiva'
                    ELSE NULL
                END AS tipo_dominante
            FROM eventos_ot_cerradas
            GROUP BY ot_id
        ),
        ots_por_activo AS (
            -- Cruzar eventos con el tipo dominante de su OT
            -- Filtrar solo correctiva y predictiva (OPCIÓN A)
            SELECT
                e.activo_id,
                e.ot_id,
                e.fecha_cierre,
                t.tipo_dominante
            FROM eventos_ot_cerradas e
            JOIN tipo_dominante_por_ot t ON t.ot_id = e.ot_id
            WHERE t.tipo_dominante IN ('correctiva', 'predictiva')
        )
        SELECT DISTINCT ON (activo_id)
            activo_id,
            ot_id,
            fecha_cierre,
            tipo_dominante AS tipo_mant_lower
        FROM ots_por_activo
        ORDER BY
            activo_id,
            fecha_cierre DESC,
            CASE tipo_dominante
                WHEN 'predictiva' THEN 1
                WHEN 'correctiva' THEN 2
                ELSE 9
            END;
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"fecha_corte": fecha_corte})


def _validar_tipo_dominante(tipo_lower: str) -> Optional[str]:
    """Acepta 'predictiva' | 'correctiva' | 'preventiva' tal como viene de la
    query (que ya hizo la normalización vía CASE). Devuelve None si no es
    uno de los tres valores reconocidos."""
    if tipo_lower in ("predictiva", "correctiva", "preventiva"):
        return tipo_lower
    return None


def aplicar_decay_post_intervencion(output: pd.DataFrame,
                                    df_ots_recientes: pd.DataFrame,
                                    umbrales: dict,
                                    fecha_scoring: str) -> pd.DataFrame:
    """
    Aplica atenuación a probabilidad_falla y recalcula prioridad para activos
    en P1/P2 que tuvieron OT correctiva o predictiva cerrada recientemente
    (OPCIÓN A: independientemente del sistema en riesgo).

    Agrega 4 columnas a output (siempre, aunque queden NULL/False):
      - prioridad_pre_decay: prioridad original antes de la atenuación.
      - ajuste_intervencion_reciente: True si se aplicó atenuación.
      - tipo_mant_atenuacion: 'predictiva' | 'correctiva' | None.
      - dias_desde_intervencion: días entre ordenes_trabajo.fecha_cierre y fecha_scoring.

    Activos sin OT correctiva/predictiva reciente no se tocan; su prioridad
    y probabilidad quedan idénticas, y los 4 campos quedan con valores
    neutros (False / None).

    Lógica:
      - Solo aplica a P1_critica y P2_alta.
      - Si el activo tuvo OT correctiva o predictiva cerrada dentro de la
        ventana (30 días para ambas), atenúa sin importar qué sistema se
        tocó en la intervención.
      - Factor: 0.20 para predictiva, 0.30 para correctiva.
      - El sistema en riesgo actual no influye en la decisión (OPCIÓN A).
    """
    fecha_scoring_date = pd.to_datetime(fecha_scoring).date()

    # Inicializar las 4 columnas de trazabilidad con valores neutros.
    output = output.copy()
    output["prioridad_pre_decay"] = output["prioridad"]
    output["ajuste_intervencion_reciente"] = False
    output["tipo_mant_atenuacion"] = None
    output["dias_desde_intervencion"] = pd.NA

    if df_ots_recientes is None or df_ots_recientes.empty:
        return output

    # Merge solo por activo_id (sin restricción de sistema).
    output = output.merge(
        df_ots_recientes[["activo_id", "fecha_cierre", "tipo_mant_lower"]],
        on=["activo_id"],
        how="left",
    )

    # Calcular días desde cierre solo donde hay match.
    def _dias_desde(fc):
        if pd.isna(fc):
            return pd.NA
        try:
            return (fecha_scoring_date - pd.to_datetime(fc).date()).days
        except Exception:
            return pd.NA

    output["_dias_desde_cierre"] = output["fecha_cierre"].apply(_dias_desde)

    # Aplicar la regla fila por fila.
    def _atenuar(row):
        # Solo P1/P2 son accionables.
        if row["prioridad"] not in ("P1_critica", "P2_alta"):
            return row["probabilidad_falla"], False, None, pd.NA

        # Sin OT correctiva/predictiva → sin atenuación.
        if pd.isna(row.get("fecha_cierre")) or pd.isna(row.get("_dias_desde_cierre")):
            return row["probabilidad_falla"], False, None, pd.NA

        tipo_cat = _validar_tipo_dominante(row.get("tipo_mant_lower") or "")
        if tipo_cat is None or tipo_cat == "preventiva":
            # Nota: tipo_cat nunca debe ser "preventiva" porque la query
            # ya filtra correctiva/predictiva. Pero lo dejamos explícito
            # para ser defensivo.
            return row["probabilidad_falla"], False, None, pd.NA

        dias = int(row["_dias_desde_cierre"])
        ventana = VENTANA_DIAS[tipo_cat]
        if dias > ventana or dias < 0:
            return row["probabilidad_falla"], False, None, pd.NA

        factor = FACTOR_ATENUACION[tipo_cat]
        prob_atenuada = float(row["probabilidad_falla"]) * factor
        return prob_atenuada, True, tipo_cat, dias

    resultados = output.apply(_atenuar, axis=1, result_type="expand")
    resultados.columns = ["_prob_nueva", "_ajuste", "_tipo_cat", "_dias_aplicado"]

    # Aplicar resultados solo donde hubo atenuación, preservando lo demás.
    mask = resultados["_ajuste"] == True  # noqa: E712
    output.loc[mask, "probabilidad_falla"] = resultados.loc[mask, "_prob_nueva"].astype(float)
    output.loc[mask, "ajuste_intervencion_reciente"] = True
    output.loc[mask, "tipo_mant_atenuacion"] = resultados.loc[mask, "_tipo_cat"]
    output.loc[mask, "dias_desde_intervencion"] = resultados.loc[mask, "_dias_aplicado"]

    # Recalcular prioridad con la nueva probabilidad.
    output["prioridad"] = [prioridad(float(p), umbrales) for p in output["probabilidad_falla"]]

    # Limpiar columnas auxiliares del merge antes de devolver.
    output = output.drop(columns=["fecha_cierre", "tipo_mant_lower", "_dias_desde_cierre"],
                         errors="ignore")
    return output


def main(fecha_scoring: str):
    print(f"Fecha de scoring: {fecha_scoring}")

    # 1) Umbrales de prioridad
    umbrales = obtener_umbrales(MODELO_VERSION)
    print(f"Umbrales de prioridad: {umbrales}")

    # =========================================================================
    # GENERAR SCORING PARA MÚLTIPLES HORIZONTES (7, 30, 90 días)
    # =========================================================================
    horizontes = [7, 30, 90]
    resultados_totales = []

    for horizonte_dias in horizontes:
        print(f"\n{'='*70}")
        print(f"🎯 PROCESANDO HORIZONTE: {horizonte_dias} DÍAS")
        print(f"{'='*70}")

        # 2) Cargar modelo y metadata para este horizonte
        modelo_suffix = f"_h{horizonte_dias}"
        model_path = f"models/modelo_xgb_v1.0{modelo_suffix}.joblib"
        metadata_path = f"models/metadata_xgb_v1.0{modelo_suffix}.json"

        try:
            model = joblib.load(model_path)
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
        except FileNotFoundError as e:
            print(f"❌ Modelo para horizonte {horizonte_dias} no encontrado: {model_path}")
            print(f"   Saltando este horizonte. Error: {str(e)}")
            continue

        feature_cols = metadata["feature_cols"]
        umbral_clasificacion = float(metadata.get("threshold_optimo", 0.5))
        print(f"Modelo: {model_path}")
        print(f"Threshold de clasificacion: {umbral_clasificacion:.4f}")
        print(f"N features: {len(feature_cols)}")

        # 3) Construir features
        print(f"\nConstruyendo features para {fecha_scoring}...")
        features = construir_features(fecha_scoring, horizonte_dias=horizonte_dias)
        
        if features is None or len(features) == 0:
            print(f"❌ ERROR: construir_features() devolvió DataFrame vacío para horizonte {horizonte_dias}")
            continue
        
        print(f"✅ Features construidas: {len(features)} activos, {len(features.columns)} columnas")

        # 4) MAPEO DE COLUMNAS
        print(f"\n🔄 Mapeando {len(generar_mapeo_columnas(horizonte_dias))} columnas (largas → cortas)...")
        
        mapeo_columnas = generar_mapeo_columnas(horizonte_dias)
        mapeo_largo_a_corto = {v: k for k, v in mapeo_columnas.items()}        
        feature_cols_largos = []
        for col_corto in feature_cols:
            if col_corto in mapeo_columnas:
                feature_cols_largos.append(mapeo_columnas[col_corto])
            else:
                feature_cols_largos.append(col_corto)
        
        columnas_faltantes = [col for col in feature_cols_largos if col not in features.columns]
        if columnas_faltantes:
            print(f"❌ ERROR: Columnas faltantes en features: {columnas_faltantes}")
            print(f"   Saltando horizonte {horizonte_dias}")
            continue
        
        print(f"✅ Mapeo validado: todas las columnas existen")

        # 5) PREDICCIÓN
        print(f"\nRealizando predicción...")
        X = features[feature_cols_largos].copy()
        X = X.rename(columns=mapeo_largo_a_corto)

        X = X.fillna(-1)
        
        proba = model.predict_proba(X)[:, 1]
        print(f"✅ Predicción completada: {len(proba)} predicciones generadas")

        # 6) Armar output base — probabilidad_falla DEBE ser float64 para evitar warnings
        output = pd.DataFrame({
            "activo_id": features["activo_id"],
            "fecha_scoring": pd.to_datetime(fecha_scoring).date(),
            "horizonte_dias": horizonte_dias,
            "probabilidad_falla": proba.astype(np.float64),
            "prediccion": (proba >= umbral_clasificacion).astype(int),
            "prioridad": [prioridad(float(p), umbrales) for p in proba],
            "modelo_version": MODELO_VERSION,
        })

        # 7) Enriquecer con sistema_en_riesgo
        asegurar_columna_sistema_en_riesgo()
        df_sistema = obtener_sistema_en_riesgo_por_activo(fecha_scoring)
        n_clasificados = df_sistema["activo_id"].nunique() if not df_sistema.empty else 0
        print(f"Activos con sistema clasificado por taxonomia: {n_clasificados}")
        output = output.merge(df_sistema, on="activo_id", how="left")
        output["sistema_en_riesgo"] = output["sistema_en_riesgo"].fillna("sin_historial_ot")

        # 7.5) ATENUACIÓN POST-INTERVENCIÓN
        print(f"\n🔧 Evaluando atenuación post-intervención...")
        asegurar_columnas_trazabilidad()
        df_ots_recientes = obtener_ot_correctiva_predictiva_reciente_por_activo(fecha_scoring)
        print(f"   Activos con OT correctiva/predictiva cerrada: {len(df_ots_recientes)}")
        output = aplicar_decay_post_intervencion(output, df_ots_recientes, umbrales, fecha_scoring)

        n_atenuadas = int(output["ajuste_intervencion_reciente"].sum())
        print(f"   ✅ Atenuaciones aplicadas: {n_atenuadas}")

        # Acumular resultado
        resultados_totales.append(output)

        # Resumen parcial
        print(f"\n📊 RESUMEN HORIZONTE {horizonte_dias} DÍAS")
        print(f"{'='*70}")
        print("\nDistribucion de prioridades (final, post-atenuación):")
        print(output["prioridad"].value_counts().to_string())

    # =========================================================================
    # PERSISTIR TODOS LOS HORIZONTES EN BD
    # =========================================================================
    if not resultados_totales:
        print("\n❌ ERROR: No se generó scoring para ningún horizonte")
        sys.exit(1)

    print(f"\n💾 Guardando resultados en BD...")
    resultado_final = pd.concat(resultados_totales, ignore_index=True)

    # =========================================================================
    # AJUSTE DE COHERENCIA: h30 NO PUEDE TENER MENOR RIESGO QUE h7
    # =========================================================================
    # Lógica: si un activo tiene mayor probabilidad de falla en h7 que en h30,
    # se reemplaza h30 con los valores de h7 (prioridad y probabilidad).
    # No se puede predecir falla a 7 días y "olvidar" esa falla a 30 días.
    # =========================================================================
    print(f"\n🔄 Aplicando ajuste de coherencia h7 → h30...")
    
    df_h7 = resultado_final[resultado_final['horizonte_dias'] == 7].set_index('activo_id')
    df_h30 = resultado_final[resultado_final['horizonte_dias'] == 30].set_index('activo_id')
    
    activos_ajustados = 0
    for activo_id in df_h30.index:
        if activo_id in df_h7.index:
            prob_h7 = df_h7.loc[activo_id, 'probabilidad_falla']
            prob_h30 = df_h30.loc[activo_id, 'probabilidad_falla']
            
            if prob_h7 > prob_h30:
                # Reemplazar probabilidad, prioridad y sistema_en_riesgo en h30 con valores de h7
                mask = (resultado_final['horizonte_dias'] == 30) & (resultado_final['activo_id'] == activo_id)
                resultado_final.loc[mask, 'probabilidad_falla'] = prob_h7
                resultado_final.loc[mask, 'prioridad'] = df_h7.loc[activo_id, 'prioridad']
                resultado_final.loc[mask, 'sistema_en_riesgo'] = df_h7.loc[activo_id, 'sistema_en_riesgo']
                activos_ajustados += 1
    
    print(f"✅ {activos_ajustados} activos ajustados en h30 (usando valores de h7)")

    with engine.begin() as conn:
        conn.execute(
            text("""
                DELETE FROM scoring_resultados
                WHERE fecha_scoring = :fecha
                  AND modelo_version = :version
            """),
            {"fecha": pd.to_datetime(fecha_scoring).date(), "version": MODELO_VERSION},
        )

    resultado_final.to_sql(
        "scoring_resultados",
        engine,
        if_exists="append",
        index=False,
        method="multi",
    )
    print(f"✅ {len(resultado_final)} resultados guardados en scoring_resultados")
    print(f"   - Horizonte 7 días:  {len(resultado_final[resultado_final['horizonte_dias']==7])} registros")
    print(f"   - Horizonte 30 días: {len(resultado_final[resultado_final['horizonte_dias']==30])} registros")
    print(f"   - Horizonte 90 días: {len(resultado_final[resultado_final['horizonte_dias']==90])} registros")

    # =========================================================================
    # RESUMEN FINAL CONSOLIDADO
    # =========================================================================
    print("\n" + "="*70)
    print("📊 RESUMEN FINAL — MÚLTIPLES HORIZONTES")
    print("="*70)
    
    for horizonte_dias in horizontes:
        subset = resultado_final[resultado_final['horizonte_dias'] == horizonte_dias]
        if not subset.empty:
            print(f"\n🎯 HORIZONTE {horizonte_dias} DÍAS:")
            print(f"   Total activos: {len(subset)}")
            print("   Distribución de prioridades:")
            for pri in ["P1_critica", "P2_alta", "P3_media", "P4_baja"]:
                n = len(subset[subset["prioridad"] == pri])
                pct = 100.0 * n / len(subset) if len(subset) > 0 else 0
                print(f"     {pri}: {n} ({pct:.1f}%)")

    print("\n" + "="*70)
    print(f"✅ SCORING COMPLETADO EXITOSAMENTE ({fecha_scoring})")
    print(f"   Generados 3 horizontes × {len(features)} activos = {len(resultado_final)} predicciones")
    print("="*70)


if __name__ == "__main__":
    # Fecha por defecto: hoy. Override opcional: pasar fecha como argumento.
    # Uso:
    #   uv run python ejecutar_scoring.py                 -> usa fecha de hoy
    #   uv run python ejecutar_scoring.py 2026-05-30      -> usa fecha indicada
    
    print("\n" + "="*70)
    print("🎯 EJECUTAR SCORING - BAITECK PDM-FLOTAS")
    print("="*70)
    
    try:
        fecha = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
        main(fecha)
    except Exception as e:
        print(f"\n❌ ERROR EN SCORING: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
