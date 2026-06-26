"""
BAITECK — Calcular Métricas Vista 3 (Impacto y Desempeño)
========================================================

Script para calcular las 15 métricas de Vista 3 e insertar en tabla `paneles`.

Métricas incluidas:
  - M1–M6:  KPIs hero (P1/P2 feedback, disponibilidad, MTBF, MTTR, tasa alertas)
  - M14–M16, M17–M20: Desempeño IA (Recall, Precision, Anticipación, % estados, Matriz confusión)
  - M21: Feedback (Alertas por estado)

No incluye (fase 2):
  - M7–M10: Series mensuales (requieren estructura temporal)
  - M22–M25: Bloqueadas/pospuestas (no existe captura de motivos, candado mes 6, costo)

Ejecución:
  uv run python calcular_metricas_vista3.py

Autor: BAITECK — junio 2026
"""

import os
from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import logging

# ============================================================================
# CONFIG
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s — %(message)s'
)
logger = logging.getLogger(__name__)


def get_engine():
    """Crear engine SQLAlchemy con Supabase."""
    try:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL no encontrada en .env")
        return create_engine(url, pool_pre_ping=True)
    except Exception as e:
        logger.error(f"Error conectando a Supabase: {e}")
        raise


def execute_query(engine, query_sql, params=None):
    """Ejecutar query SQL y retornar resultado."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query_sql), params or {})
            return result.fetchall()
    except Exception as e:
        logger.error(f"Error en query: {e}")
        return None


def insert_metrica(engine, vista, metrica, horizonte_dias, valor, delta_color=None, fuente_sql=None):
    """Insertar (o actualizar) una métrica en tabla paneles."""
    try:
        with engine.begin() as conn:
            # Verificar si existe registro anterior para calcular delta
            check_query = text("""
                SELECT valor FROM paneles
                WHERE vista = :vista AND metrica = :metrica 
                  AND horizonte_dias IS NOT DISTINCT FROM :horizonte
                ORDER BY fecha_calculo DESC
                LIMIT 1
            """)
            result = conn.execute(check_query, {
                "vista": vista,
                "metrica": metrica,
                "horizonte": horizonte_dias
            }).scalar()
            
            valor_anterior = float(result) if result else None
            
            # Insertar nuevo registro
            insert_query = text("""
                INSERT INTO paneles (vista, metrica, horizonte_dias, valor, valor_anterior, delta_color, fecha_calculo, fuente_sql)
                VALUES (:vista, :metrica, :horizonte, :valor, :valor_anterior, :delta_color, NOW(), :fuente_sql)
            """)
            conn.execute(insert_query, {
                "vista": vista,
                "metrica": metrica,
                "horizonte": horizonte_dias,
                "valor": valor,
                "valor_anterior": valor_anterior,
                "delta_color": delta_color,
                "fuente_sql": fuente_sql
            })
            logger.info(f"✅ {metrica} = {valor} (delta: {delta_color})")
    except Exception as e:
        logger.error(f"❌ Error insertando {metrica}: {e}")


# ============================================================================
# M1–M6: KPIs HERO
# ============================================================================

def calcular_m1_p1_feedback(engine):
    """M1: Unidades con P1 confirmado en feedback."""
    query = """
        SELECT COUNT(DISTINCT f.activo_id) as valor
        FROM feedback_taller f
        WHERE f.falla_confirmada = TRUE
          AND EXISTS (
              SELECT 1 FROM scoring_resultados s 
              WHERE s.scoring_id = f.scoring_id 
              AND s.prioridad = 'P1_critica'
          )
    """
    result = execute_query(engine, query)
    return int(result[0][0]) if result and result[0][0] else 0


def calcular_m2_p2_feedback(engine):
    """M2: Unidades con P2 confirmado en feedback."""
    query = """
        SELECT COUNT(DISTINCT f.activo_id) as valor
        FROM feedback_taller f
        WHERE f.falla_confirmada = TRUE
          AND EXISTS (
              SELECT 1 FROM scoring_resultados s 
              WHERE s.scoring_id = f.scoring_id 
              AND s.prioridad = 'P2_alta'
          )
    """
    result = execute_query(engine, query)
    return int(result[0][0]) if result and result[0][0] else 0


def calcular_m3_disponibilidad_30d(engine):
    """M3: Disponibilidad operacional últimos 30 días (%)."""
    query = """
        SELECT 
            AVG(
                CASE 
                    WHEN (horas_operativas + horas_detenido_no_planificado) > 0 
                    THEN (horas_operativas / (horas_operativas + horas_detenido_no_planificado)) * 100
                    ELSE 100
                END
            ) as valor
        FROM disponibilidad_diaria
        WHERE fecha >= CURRENT_DATE - INTERVAL '30 days'
    """
    result = execute_query(engine, query)
    return float(result[0][0]) if result and result[0][0] else 0.0


def calcular_m4_mtbf_90d(engine):
    """M4: MTBF flota últimos 90 días (horas)."""
    # Consistente con cálculo de Vista 1
    query = """
        WITH activos_activos AS (
            SELECT DISTINCT a.activo_id
            FROM activos a
            WHERE UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
        ),
        horas_totales AS (
            SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura))/3600), 0) as horas
            FROM ordenes_trabajo o
            INNER JOIN activos_activos aa ON o.activo_id = aa.activo_id
            WHERE o.fecha_cierre >= CURRENT_DATE - INTERVAL '90 days'
              AND o.fecha_cierre IS NOT NULL
        ),
        fallas_totales AS (
            SELECT COUNT(*) as n_fallas
            FROM ordenes_trabajo o
            INNER JOIN activos_activos aa ON o.activo_id = aa.activo_id
            WHERE o.fecha_cierre >= CURRENT_DATE - INTERVAL '90 days'
              AND LOWER(COALESCE(o.tipo_ot, '')) = 'correctiva'
        )
        SELECT 
            CASE 
                WHEN ft.n_fallas > 0 THEN ht.horas / ft.n_fallas::NUMERIC
                ELSE 0
            END as valor
        FROM horas_totales ht, fallas_totales ft
    """
    result = execute_query(engine, query)
    return float(result[0][0]) if result and result[0][0] else 0.0


def calcular_m5_mttr_90d(engine):
    """M5: MTTR flota últimos 90 días (horas), solo activos activos."""
    query = """
        WITH activos_activos AS (
            SELECT DISTINCT a.activo_id
            FROM activos a
            WHERE UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
        ),
        reparaciones AS (
            SELECT 
                COALESCE(SUM(EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura))/3600), 0) as horas_total,
                COUNT(*) as n_reparaciones
            FROM ordenes_trabajo o
            INNER JOIN activos_activos aa ON o.activo_id = aa.activo_id
            WHERE o.fecha_cierre >= CURRENT_DATE - INTERVAL '90 days'
              AND LOWER(COALESCE(o.tipo_ot, '')) = 'correctiva'
              AND o.fecha_cierre IS NOT NULL
        )
        SELECT 
            CASE 
                WHEN n_reparaciones > 0 THEN horas_total / n_reparaciones::NUMERIC
                ELSE 0
            END as valor
        FROM reparaciones
    """
    result = execute_query(engine, query)
    return float(result[0][0]) if result and result[0][0] else 0.0


def calcular_m6_tasa_alertas_confirmadas(engine):
    """M6: Tasa de alertas confirmadas (%), confiabilidad del modelo."""
    query = """
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falla_confirmada = TRUE THEN 1 END) as confirmadas
        FROM feedback_taller
    """
    result = execute_query(engine, query)
    if result and result[0]:
        total = result[0][0]
        confirmadas = result[0][1] or 0
        if total > 0:
            return (confirmadas / total) * 100
    return 0.0


# ============================================================================
# M14–M16: DESEMPEÑO IA (RECALL, PRECISION, ANTICIPACION)
# ============================================================================

def calcular_m14_recall(engine):
    """M14: Recall del modelo desde modelos_registro."""
    query = """
        SELECT recall as valor
        FROM modelos_registro
        WHERE es_activo = TRUE
        ORDER BY fecha_creacion DESC
        LIMIT 1
    """
    result = execute_query(engine, query)
    return float(result[0][0]) * 100 if result and result[0][0] else 0.0  # Convertir a porcentaje


def calcular_m15_precision(engine):
    """M15: Precision del modelo desde modelos_registro."""
    query = """
        SELECT precision as valor
        FROM modelos_registro
        WHERE es_activo = TRUE
        ORDER BY fecha_creacion DESC
        LIMIT 1
    """
    result = execute_query(engine, query)
    return float(result[0][0]) * 100 if result and result[0][0] else 0.0


def calcular_m16_anticipacion_promedio(engine):
    """M16: Anticipación promedio (días) — desde fecha_alerta a fecha_apertura OT correctiva."""
    query = """
        SELECT 
            AVG(EXTRACT(DAY FROM (
                (SELECT MIN(o.fecha_apertura)
                 FROM ordenes_trabajo o
                 WHERE o.activo_id = f.activo_id
                   AND o.fecha_apertura > f.fecha_alerta
                   AND LOWER(COALESCE(o.tipo_ot, '')) = 'correctiva'
                ) - f.fecha_alerta::timestamp
            ))) as valor
        FROM feedback_taller f
        WHERE f.falla_confirmada = TRUE
          AND f.fecha_alerta IS NOT NULL
    """
    result = execute_query(engine, query)
    return float(result[0][0]) if result and result[0][0] else 0.0


# ============================================================================
# M17–M19: DISTRIBUCIÓN DE FEEDBACK (%)
# ============================================================================

def calcular_m17_pct_confirmadas(engine):
    """M17: % Alertas confirmadas."""
    query = """
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falla_confirmada = TRUE THEN 1 END) as confirmadas
        FROM feedback_taller
    """
    result = execute_query(engine, query)
    if result and result[0]:
        total = result[0][0]
        confirmadas = result[0][1] or 0
        if total > 0:
            return (confirmadas / total) * 100
    return 0.0


def calcular_m18_pct_rechazadas(engine):
    """M18: % Alertas rechazadas (falsa_alarma = TRUE)."""
    query = """
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falsa_alarma = TRUE THEN 1 END) as rechazadas
        FROM feedback_taller
    """
    result = execute_query(engine, query)
    if result and result[0]:
        total = result[0][0]
        rechazadas = result[0][1] or 0
        if total > 0:
            return (rechazadas / total) * 100
    return 0.0


def calcular_m19_pct_pendientes(engine):
    """M19: % Alertas pendientes (falla_confirmada IS NULL AND falsa_alarma IS FALSE)."""
    query = """
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falla_confirmada IS NULL AND falsa_alarma IS FALSE THEN 1 END) as pendientes
        FROM feedback_taller
    """
    result = execute_query(engine, query)
    if result and result[0]:
        total = result[0][0]
        pendientes = result[0][1] or 0
        if total > 0:
            return (pendientes / total) * 100
    return 0.0


# ============================================================================
# M20: MATRIZ CONFUSIÓN (4 MÉTRICAS ESCALARES)
# ============================================================================

def calcular_m20_matriz_confusión(engine):
    """M20: Matriz confusión — retorna dict con TP, FP, FN, TN."""
    query = """
        WITH alertas AS (
            SELECT s.scoring_id, s.prioridad,
                   CASE WHEN s.prioridad IN ('P1_critica', 'P2_alta') THEN 1 ELSE 0 END AS alertamos
            FROM scoring_resultados s
        ),
        feedback AS (
            SELECT scoring_id,
                   CASE WHEN falla_confirmada = TRUE THEN 1 ELSE 0 END AS hubo_falla
            FROM feedback_taller
        )
        SELECT
            SUM(CASE WHEN a.alertamos = 1 AND f.hubo_falla = 1 THEN 1 ELSE 0 END) AS tp,
            SUM(CASE WHEN a.alertamos = 1 AND f.hubo_falla = 0 THEN 1 ELSE 0 END) AS fp,
            SUM(CASE WHEN a.alertamos = 0 AND f.hubo_falla = 1 THEN 1 ELSE 0 END) AS fn,
            SUM(CASE WHEN a.alertamos = 0 AND f.hubo_falla = 0 THEN 1 ELSE 0 END) AS tn
        FROM alertas a
        INNER JOIN feedback f ON f.scoring_id = a.scoring_id
    """
    result = execute_query(engine, query)
    if result and result[0]:
        return {
            'tp': int(result[0][0] or 0),
            'fp': int(result[0][1] or 0),
            'fn': int(result[0][2] or 0),
            'tn': int(result[0][3] or 0)
        }
    return {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0}


# ============================================================================
# M21: ALERTAS POR ESTADO (CONTEO)
# ============================================================================

def calcular_m21_alertas_confirmadas_count(engine):
    """M21a: Conteo de alertas confirmadas."""
    query = """
        SELECT COUNT(*) as valor
        FROM feedback_taller
        WHERE falla_confirmada = TRUE
    """
    result = execute_query(engine, query)
    return int(result[0][0]) if result and result[0][0] else 0


def calcular_m21_alertas_rechazadas_count(engine):
    """M21b: Conteo de alertas rechazadas."""
    query = """
        SELECT COUNT(*) as valor
        FROM feedback_taller
        WHERE falsa_alarma = TRUE
    """
    result = execute_query(engine, query)
    return int(result[0][0]) if result and result[0][0] else 0


def calcular_m21_alertas_pendientes_count(engine):
    """M21c: Conteo de alertas pendientes."""
    query = """
        SELECT COUNT(*) as valor
        FROM feedback_taller
        WHERE falla_confirmada IS NULL AND falsa_alarma IS FALSE
    """
    result = execute_query(engine, query)
    return int(result[0][0]) if result and result[0][0] else 0


# ============================================================================
# MAIN: ORQUESTADOR
# ============================================================================

def main():
    """Calcular todas las métricas Vista 3 e insertar en paneles."""
    
    logger.info("="*70)
    logger.info("CALCULAR MÉTRICAS VISTA 3 — Impacto y Desempeño")
    logger.info("="*70)
    
    engine = get_engine()
    
    try:
        # M1–M6: KPIs Hero
        logger.info("\n[KPIs HERO]")
        m1 = calcular_m1_p1_feedback(engine)
        insert_metrica(engine, 'Vista3', 'unidades_p1_feedback', None, m1, delta_color='inverse')
        
        m2 = calcular_m2_p2_feedback(engine)
        insert_metrica(engine, 'Vista3', 'unidades_p2_feedback', None, m2, delta_color='inverse')
        
        m3 = calcular_m3_disponibilidad_30d(engine)
        insert_metrica(engine, 'Vista3', 'disponibilidad_operacional_30d', 30, m3, delta_color='positive')
        
        m4 = calcular_m4_mtbf_90d(engine)
        insert_metrica(engine, 'Vista3', 'mtbf_flota_90d', 90, m4, delta_color='positive')
        
        m5 = calcular_m5_mttr_90d(engine)
        insert_metrica(engine, 'Vista3', 'mttr_flota_90d', 90, m5, delta_color='inverse')
        
        m6 = calcular_m6_tasa_alertas_confirmadas(engine)
        insert_metrica(engine, 'Vista3', 'tasa_alertas_confirmadas_pct', None, m6, delta_color='positive')
        
        # M14–M16: Desempeño IA
        logger.info("\n[DESEMPEÑO IA]")
        m14 = calcular_m14_recall(engine)
        insert_metrica(engine, 'Vista3', 'recall_pct', None, m14, delta_color='positive')
        
        m15 = calcular_m15_precision(engine)
        insert_metrica(engine, 'Vista3', 'precision_pct', None, m15, delta_color='positive')
        
        m16 = calcular_m16_anticipacion_promedio(engine)
        insert_metrica(engine, 'Vista3', 'anticipacion_promedio_dias', None, m16, delta_color='positive')
        
        # M17–M19: Distribución Feedback
        logger.info("\n[FEEDBACK — DISTRIBUCIÓN]")
        m17 = calcular_m17_pct_confirmadas(engine)
        insert_metrica(engine, 'Vista3', 'pct_alertas_confirmadas', None, m17, delta_color='positive')
        
        m18 = calcular_m18_pct_rechazadas(engine)
        insert_metrica(engine, 'Vista3', 'pct_alertas_rechazadas', None, m18, delta_color='inverse')
        
        m19 = calcular_m19_pct_pendientes(engine)
        insert_metrica(engine, 'Vista3', 'pct_alertas_pendientes', None, m19, delta_color='neutral')
        
        # M20: Matriz Confusión (4 métricas)
        logger.info("\n[MATRIZ CONFUSIÓN]")
        m20 = calcular_m20_matriz_confusión(engine)
        insert_metrica(engine, 'Vista3', 'confusion_tp', None, m20['tp'])
        insert_metrica(engine, 'Vista3', 'confusion_fp', None, m20['fp'])
        insert_metrica(engine, 'Vista3', 'confusion_fn', None, m20['fn'])
        insert_metrica(engine, 'Vista3', 'confusion_tn', None, m20['tn'])
        
        # M21: Alertas por estado (3 métricas)
        logger.info("\n[ALERTAS POR ESTADO]")
        m21a = calcular_m21_alertas_confirmadas_count(engine)
        insert_metrica(engine, 'Vista3', 'alertas_confirmadas_count', None, m21a)
        
        m21b = calcular_m21_alertas_rechazadas_count(engine)
        insert_metrica(engine, 'Vista3', 'alertas_rechazadas_count', None, m21b)
        
        m21c = calcular_m21_alertas_pendientes_count(engine)
        insert_metrica(engine, 'Vista3', 'alertas_pendientes_count', None, m21c)
        
        logger.info("\n" + "="*70)
        logger.info("✅ TODAS LAS MÉTRICAS CALCULADAS E INSERTADAS")
        logger.info("="*70)
        
    except Exception as e:
        logger.error(f"\n❌ ERROR CRÍTICO: {e}")
        raise


if __name__ == "__main__":
    main()
