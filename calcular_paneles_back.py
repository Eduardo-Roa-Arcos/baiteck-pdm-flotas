#!/usr/bin/env python3
"""
CALCULAR MÉTRICAS PANELES
==========================

Calcula TODAS las métricas del dashboard y las guarda en tabla 'paneles'
con historial de valores anteriores para visualizar tendencias.

Flujo:
  1. Lee valores actuales de paneles → asigna a valor_anterior
  2. Calcula todas las métricas del dashboard
  3. Inserta/actualiza en paneles (valor, valor_anterior, fecha_calculo)
  4. Manejo graceful de tablas faltantes (continúa, no falla)

Uso:
    uv run python calcular_metricas_paneles.py

Output:
    - Inserciones en tabla 'paneles'
    - Log detallado de cada métrica
    - Resumen final con conteo y tiempos

Tablas requeridas:
    - paneles (schema definido en create_table_paneles.sql)
    - scoring_resultados, ordenes_trabajo, activos
    
Tablas opcionales (activan funciones específicas):
    - disponibilidad_diaria, feedback_taller, ot_falla_evento, taxonomia_fallas
"""

import os
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import logging

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no configurada en .env")
    sys.exit(1)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('calcular_metricas_paneles.log')
    ]
)
log = logging.getLogger(__name__)

# ============================================================================
# CONEXIÓN A BD
# ============================================================================

def get_connection():
    """Obtiene conexión a Supabase."""
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        return conn
    except Exception as e:
        log.error(f"Error conectando a BD: {e}")
        return None


def query_db(query_sql, params=None):
    """Ejecuta query y retorna resultado como dict list o None si error."""
    conn = get_connection()
    if conn is None:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query_sql, params)
            result = cur.fetchall()
        return result
    except Exception as e:
        log.warning(f"Query fallida: {str(e)[:100]}")
        return None
    finally:
        conn.close()


def execute_sql(query_sql, params=None):
    """Ejecuta INSERT/UPDATE sin retorno."""
    conn = get_connection()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(query_sql, params)
        conn.commit()
        return True
    except Exception as e:
        log.error(f"Execute fallido: {str(e)[:100]}")
        return False
    finally:
        conn.close()


def table_exists(table_name: str) -> bool:
    """Verifica si una tabla existe."""
    result = query_db("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        ) AS existe;
    """, (table_name,))
    if result:
        return result[0]['existe']
    return False


def column_exists(table_name: str, column_name: str) -> bool:
    """Verifica si una columna existe en una tabla."""
    result = query_db("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        ) AS existe;
    """, (table_name, column_name))
    if result:
        return result[0]['existe']
    return False


# ============================================================================
# FUNCIONES DE LECTURA PREVIAS (para valor_anterior)
# ============================================================================

def get_valor_anterior(vista: str, metrica: str, horizonte_dias: int = None) -> float:
    """Lee el valor actual de paneles (será valor_anterior en nueva inserción)."""
    try:
        if horizonte_dias:
            q = """
                SELECT valor FROM paneles 
                WHERE vista = %s AND metrica = %s AND horizonte_dias = %s
                ORDER BY fecha_calculo DESC LIMIT 1
            """
            result = query_db(q, (vista, metrica, horizonte_dias))
        else:
            q = """
                SELECT valor FROM paneles 
                WHERE vista = %s AND metrica = %s
                ORDER BY fecha_calculo DESC LIMIT 1
            """
            result = query_db(q, (vista, metrica))
        
        if result and result[0]['valor'] is not None:
            return float(result[0]['valor'])
    except Exception:
        pass
    return None


# ============================================================================
# FUNCIONES DE CÁLCULO — VISTA 1: ESTADO Y RIESGO
# ============================================================================

def calc_unidades_operativas() -> dict:
    """Unidades activas (no dadas de baja)."""
    result = query_db("""
        SELECT COUNT(*) AS n FROM activos
        WHERE COALESCE(LOWER(estado_actual), 'operativo') 
              NOT IN ('baja', 'fuera_servicio', 'inactivo');
    """)
    if result:
        return {'valor': float(result[0]['n']), 'tipo': 'COUNT'}
    return {'valor': 0, 'tipo': 'COUNT'}


def calc_disponibilidad_30d() -> dict:
    """Disponibilidad últimos 30 días."""
    if not table_exists("disponibilidad_diaria"):
        log.warning("Tabla disponibilidad_diaria no existe → Disponibilidad = None")
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT
            SUM(COALESCE(horas_operativas, 0)) AS op,
            SUM(COALESCE(horas_operativas, 0) +
                COALESCE(horas_detenido_planificado, 0) +
                COALESCE(horas_detenido_no_planificado, 0)) AS tot
        FROM disponibilidad_diaria
        WHERE fecha >= CURRENT_DATE - INTERVAL '30 days';
    """)
    
    if result and result[0]['tot'] and float(result[0]['tot']) > 0:
        valor = float(result[0]['op']) / float(result[0]['tot']) * 100.0
        return {'valor': valor, 'tipo': 'PCT'}
    return {'valor': None, 'tipo': 'PCT', 'nota': 'Sin datos suficientes'}


def calc_conteo_prioridad(prioridad: str, horizonte_dias: int = 30) -> dict:
    """Cuenta unidades con prioridad en último scoring."""
    result = query_db("""
        SELECT COUNT(DISTINCT activo_id) AS n
        FROM scoring_resultados
        WHERE prioridad = %s
          AND horizonte_dias = %s
          AND fecha_scoring = (
              SELECT MAX(fecha_scoring) FROM scoring_resultados
              WHERE horizonte_dias = %s
          );
    """, (prioridad, horizonte_dias, horizonte_dias))
    
    if result:
        return {'valor': float(result[0]['n']), 'tipo': 'COUNT', 'horizonte': horizonte_dias}
    return {'valor': 0, 'tipo': 'COUNT', 'horizonte': horizonte_dias}


def calc_fallas_anticipadas_30d() -> dict:
    """Alertas confirmadas como falla real en últimos 30 días."""
    if not table_exists("feedback_taller"):
        log.warning("Tabla feedback_taller no existe → Fallas anticipadas = 0")
        return {'valor': 0, 'tipo': 'COUNT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT COUNT(*) AS n
        FROM feedback_taller
        WHERE falla_confirmada = TRUE
          AND fecha_alerta >= CURRENT_DATE - INTERVAL '30 days';
    """)
    
    if result:
        return {'valor': float(result[0]['n']), 'tipo': 'COUNT'}
    return {'valor': 0, 'tipo': 'COUNT'}


def calc_mtbf_horas() -> dict:
    """MTBF de flota en horas (últimos 90 días)."""
    if not table_exists("disponibilidad_diaria"):
        log.warning("Tabla disponibilidad_diaria no existe → MTBF = None")
        return {'valor': None, 'tipo': 'HORAS', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        WITH horas AS (
            SELECT SUM(COALESCE(horas_operativas, 0)) AS h_op
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '90 days'
        ),
        fallas AS (
            SELECT COUNT(*)::numeric AS n
            FROM ordenes_trabajo
            WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')
              AND fecha_apertura >= CURRENT_DATE - INTERVAL '90 days'
        )
        SELECT
            CASE WHEN fallas.n > 0 THEN horas.h_op / fallas.n ELSE NULL END AS mtbf
        FROM horas, fallas;
    """)
    
    if result and result[0]['mtbf'] is not None:
        return {'valor': float(result[0]['mtbf']), 'tipo': 'HORAS'}
    return {'valor': None, 'tipo': 'HORAS', 'nota': 'Sin datos suficientes'}


# ============================================================================
# FUNCIONES DE CÁLCULO — VISTA 2: PLAN DE ACCIÓN
# ============================================================================

def calc_intervenciones_proximas(dias: int) -> dict:
    """Cuenta P1+P2 en horizonte dado."""
    p1_result = query_db("""
        SELECT COUNT(DISTINCT activo_id) AS n
        FROM scoring_resultados
        WHERE prioridad = 'P1_critica'
          AND horizonte_dias = %s
          AND fecha_scoring = (SELECT MAX(fecha_scoring) FROM scoring_resultados WHERE horizonte_dias = %s);
    """, (dias, dias))
    p1 = float(p1_result[0]['n']) if p1_result else 0
    
    p2_result = query_db("""
        SELECT COUNT(DISTINCT activo_id) AS n
        FROM scoring_resultados
        WHERE prioridad = 'P2_alta'
          AND horizonte_dias = %s
          AND fecha_scoring = (SELECT MAX(fecha_scoring) FROM scoring_resultados WHERE horizonte_dias = %s);
    """, (dias, dias))
    p2 = float(p2_result[0]['n']) if p2_result else 0
    
    return {'valor': p1 + p2, 'tipo': 'COUNT', 'horizonte': dias}


def calc_backlog_ot() -> dict:
    """OT abiertas (sin fecha_cierre)."""
    result = query_db("SELECT COUNT(*) AS n FROM ordenes_trabajo WHERE fecha_cierre IS NULL;")
    if result:
        return {'valor': float(result[0]['n']), 'tipo': 'COUNT'}
    return {'valor': 0, 'tipo': 'COUNT'}


def calc_cumplimiento_pm() -> dict:
    """% de OT PM cerradas en últimos 90 días."""
    result = query_db("""
        SELECT
            COUNT(*) FILTER (WHERE fecha_cierre IS NOT NULL)::numeric AS cerradas,
            COUNT(*)::numeric AS total
        FROM ordenes_trabajo
        WHERE LOWER(COALESCE(tipo_ot, '')) IN ('preventiva', 'preventivo')
          AND fecha_apertura >= CURRENT_DATE - INTERVAL '90 days';
    """)
    
    if result and result[0]['total'] and float(result[0]['total']) > 0:
        valor = float(result[0]['cerradas']) / float(result[0]['total']) * 100.0
        return {'valor': valor, 'tipo': 'PCT'}
    return {'valor': None, 'tipo': 'PCT', 'nota': 'Sin datos'}


# ============================================================================
# FUNCIONES DE CÁLCULO — VISTA 3: IMPACTO Y DESEMPEÑO
# ============================================================================

def calc_costo_evitado_acumulado() -> dict:
    """Costo evitado: SUM de costo en OTs donde feedback confirmó falla.
    
    Lógica: Para cada alerta confirmada en feedback_taller, obtenemos la OT asociada
    y sumamos su costo_total_clp.
    """
    if not table_exists("feedback_taller"):
        log.warning("Tabla feedback_taller no existe → Costo evitado = None")
        return {'valor': None, 'tipo': 'CLP', 'nota': 'Tabla faltante'}
    
    # Verificar si ordenes_trabajo existe y tiene costo_total_clp
    if not table_exists("ordenes_trabajo"):
        return {'valor': None, 'tipo': 'CLP', 'nota': 'Tabla ordenes_trabajo faltante'}
    
    col_costo = "costo_total_clp" if column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    
    result = query_db(f"""
        SELECT COALESCE(SUM(ot.{col_costo}), 0) AS total
        FROM feedback_taller ft
        LEFT JOIN ordenes_trabajo ot ON ft.ot_id = ot.ot_id
        WHERE ft.falla_confirmada = TRUE
          AND ot.{col_costo} IS NOT NULL;
    """)
    
    if result:
        valor = float(result[0]['total'] or 0)
        return {'valor': valor if valor > 0 else None, 'tipo': 'CLP'}
    return {'valor': None, 'tipo': 'CLP'}


def calc_downtime_evitado_horas() -> dict:
    """Downtime evitado: Tiempo promedio de OT por sistema × alertas confirmadas del sistema.
    
    Lógica:
      1. Para cada sistema afectado en alertas confirmadas
      2. Buscar TODAS las OTs históricas del mismo sistema
      3. Calcular AVG(fecha_cierre - fecha_apertura) en horas
      4. Multiplicar por cantidad de alertas confirmadas para ese sistema
      5. Sumar todos los sistemas
    """
    if not table_exists("feedback_taller"):
        log.warning("Tabla feedback_taller no existe → Downtime evitado = None")
        return {'valor': None, 'tipo': 'HORAS', 'nota': 'Tabla faltante'}
    
    if not table_exists("ordenes_trabajo"):
        return {'valor': None, 'tipo': 'HORAS', 'nota': 'Tabla ordenes_trabajo faltante'}
    
    if not (table_exists("ot_falla_evento") and table_exists("taxonomia_fallas")):
        log.warning("Tablas taxonomía faltantes → Downtime evitado = None")
        return {'valor': None, 'tipo': 'HORAS', 'nota': 'Tablas taxonomía faltantes'}
    
    # Query compleja que:
    # 1. Obtiene alertas confirmadas con su sistema en riesgo
    # 2. Para cada sistema, calcula duración promedio de OTs históricas
    # 3. Multiplica por cantidad de alertas confirmadas
    result = query_db("""
        WITH alertas_confirmadas AS (
            -- Obtener sistema en riesgo para cada alerta confirmada
            SELECT 
                ft.feedback_id,
                COALESCE(
                    (SELECT tf.sistema FROM ot_falla_evento ofe
                     JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
                     WHERE ofe.ot_id = ft.ot_id
                     ORDER BY ofe.fecha_evento DESC NULLS LAST LIMIT 1),
                    'sin_sistema'
                ) AS sistema
            FROM feedback_taller ft
            WHERE ft.falla_confirmada = TRUE
        ),
        duraciones_por_sistema AS (
            -- Para cada sistema, calcular duración promedio de OTs
            SELECT 
                COALESCE(
                    (SELECT tf.sistema FROM ot_falla_evento ofe
                     JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
                     WHERE ofe.ot_id = ot.ot_id
                     ORDER BY ofe.fecha_evento DESC NULLS LAST LIMIT 1),
                    'sin_sistema'
                ) AS sistema,
                AVG(EXTRACT(EPOCH FROM (ot.fecha_cierre - ot.fecha_apertura)) / 3600)::numeric AS duracion_promedio_horas
            FROM ordenes_trabajo ot
            WHERE ot.fecha_cierre IS NOT NULL
              AND ot.fecha_apertura IS NOT NULL
            GROUP BY sistema
        ),
        downtime_por_sistema AS (
            -- Multiplicar duración promedio × cantidad de alertas confirmadas por sistema
            SELECT 
                ac.sistema,
                COUNT(*) AS n_alertas,
                COALESCE(dps.duracion_promedio_horas, 0) AS duracion_promedio,
                COUNT(*) * COALESCE(dps.duracion_promedio_horas, 0) AS downtime_sistema
            FROM alertas_confirmadas ac
            LEFT JOIN duraciones_por_sistema dps ON ac.sistema = dps.sistema
            GROUP BY ac.sistema, dps.duracion_promedio_horas
        )
        SELECT COALESCE(SUM(downtime_sistema), 0) AS total_horas
        FROM downtime_por_sistema;
    """)
    
    if result:
        valor = float(result[0]['total_horas'] or 0)
        return {'valor': valor if valor > 0 else None, 'tipo': 'HORAS'}
    return {'valor': None, 'tipo': 'HORAS'}


def calc_costo_mantenimiento_km() -> dict:
    """Costo de mantenimiento por kilómetro recorrido (últimos 30 días).
    
    Fórmula: Σ(costo_total) / Σ(km_recorridos) en OT de últimos 30 días
    """
    col_costo = "costo_total_clp" if column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    
    result = query_db(f"""
        SELECT
            COALESCE(SUM(CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                             THEN {col_costo} ELSE 0 END), 0) AS costo_total,
            COALESCE(SUM(CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                             THEN COALESCE(odometro_km, 0) ELSE 0 END), 0) AS km_total
        FROM ordenes_trabajo;
    """)
    
    if result and result[0]['km_total'] and float(result[0]['km_total']) > 0:
        valor = float(result[0]['costo_total']) / float(result[0]['km_total'])
        return {'valor': valor, 'tipo': 'CLP/km'}
    return {'valor': None, 'tipo': 'CLP/km'}


def calc_costo_mantenimiento_unidad() -> dict:
    """Costo de mantenimiento por unidad (últimos 30 días).
    
    Fórmula: Σ(costo_total) / COUNT(DISTINCT activos) en OT de últimos 30 días
    """
    col_costo = "costo_total_clp" if column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    
    result = query_db(f"""
        SELECT
            COALESCE(SUM(CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                             THEN {col_costo} ELSE 0 END), 0) AS costo_total,
            COALESCE(COUNT(DISTINCT CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                                        THEN activo_id END), 0) AS n_unidades
        FROM ordenes_trabajo;
    """)
    
    if result and result[0]['n_unidades'] and result[0]['n_unidades'] > 0:
        valor = float(result[0]['costo_total']) / float(result[0]['n_unidades'])
        return {'valor': valor, 'tipo': 'CLP'}
    return {'valor': None, 'tipo': 'CLP'}


def calc_costo_mantenimiento_30d() -> dict:
    """Costo promedio mantenimiento últimos 30 días."""
    col_costo = "costo_total_clp" if column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    
    result = query_db(f"""
        SELECT
            COALESCE(SUM(CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                             THEN {col_costo} ELSE 0 END), 0) AS costo,
            COALESCE(COUNT(DISTINCT CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                                        THEN activo_id END), 0) AS n_activos
        FROM ordenes_trabajo;
    """)
    
    if result and result[0]['n_activos'] and result[0]['n_activos'] > 0:
        valor = float(result[0]['costo']) / float(result[0]['n_activos'])
        return {'valor': valor, 'tipo': 'CLP'}
    return {'valor': None, 'tipo': 'CLP'}


def calc_costo_mantenimiento_90d() -> dict:
    """Costo promedio mantenimiento últimos 90 días."""
    col_costo = "costo_total_clp" if column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    
    result = query_db(f"""
        SELECT
            COALESCE(SUM(CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '90 days' 
                             THEN {col_costo} ELSE 0 END), 0) AS costo,
            COALESCE(COUNT(DISTINCT CASE WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '90 days' 
                                        THEN activo_id END), 0) AS n_activos
        FROM ordenes_trabajo;
    """)
    
    if result and result[0]['n_activos'] and result[0]['n_activos'] > 0:
        valor = float(result[0]['costo']) / float(result[0]['n_activos'])
        return {'valor': valor, 'tipo': 'CLP'}
    return {'valor': None, 'tipo': 'CLP'}


# ============================================================================
# INSERTAR EN TABLA PANELES
# ============================================================================

def insert_metrica(vista: str, metrica: str, valor, valor_anterior=None, 
                   horizonte_dias=None, nota=''):
    """Inserta métrica en tabla paneles.
    
    Estrategia: Elimina registro anterior (si existe) y luego inserta nuevo,
    AMBOS dentro de la MISMA transacción (atómico: si el INSERT falla, el
    DELETE se revierte y la métrica anterior se conserva).
    Esto asegura que siempre haya un solo registro "actual" por métrica.
    """
    delete_q = """
        DELETE FROM paneles 
        WHERE vista = %s AND metrica = %s 
          AND COALESCE(horizonte_dias, -1) = COALESCE(%s, -1)
    """
    insert_q = """
        INSERT INTO paneles 
        (vista, metrica, valor, valor_anterior, fecha_calculo, horizonte_dias, nota)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s)
    """

    conn = get_connection()
    if conn is None:
        log.error(f"Insert fallido [{vista}][{metrica}]: sin conexión a BD")
        return False
    try:
        # 'with conn' = transacción: commit al salir OK, rollback ante excepción
        with conn:
            with conn.cursor() as cur:
                cur.execute(delete_q, (vista, metrica, horizonte_dias))
                cur.execute(insert_q, (vista, metrica, valor, valor_anterior,
                                       horizonte_dias, nota))
        log.info(f"✓ {vista:30s} | {metrica:30s} | valor={valor} | anterior={valor_anterior}")
        return True
    except Exception as e:
        log.error(f"Insert fallido [{vista}][{metrica}]: {str(e)[:80]}")
        return False
    finally:
        conn.close()


# ============================================================================
# ORQUESTADOR PRINCIPAL
# ============================================================================

def calcular_todas_metricas():
    """Calcula TODAS las métricas y las inserta en paneles."""
    
    log.info("=" * 90)
    log.info("INICIANDO CÁLCULO DE MÉTRICAS PARA TABLA PANELES")
    log.info("=" * 90)
    
    inicio = datetime.now()
    conteo = {'exitosas': 0, 'fallidas': 0}
    
    # Validaciones previas
    if not table_exists("paneles"):
        log.error("❌ Tabla 'paneles' no existe. Crea primero con: CREATE TABLE paneles (...)")
        return False
    
    # ========== VISTA 1: ESTADO Y RIESGO ==========
    log.info("\n📊 VISTA 1: ESTADO Y RIESGO")
    log.info("-" * 90)
    
    vista = "Estado y Riesgo"
    
    # Unidades operativas
    metric = calc_unidades_operativas()
    valor_anterior = get_valor_anterior(vista, "Unidades operativas")
    if insert_metrica(vista, "Unidades operativas", metric['valor'], valor_anterior):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Disponibilidad 30d
    metric = calc_disponibilidad_30d()
    valor_anterior = get_valor_anterior(vista, "Disponibilidad")
    if insert_metrica(vista, "Disponibilidad", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # P1, P2 para horizonte 7, 30, 90
    for horizonte in [7, 30, 90]:
        # P1 Crítica
        metric = calc_conteo_prioridad("P1_critica", horizonte)
        valor_anterior = get_valor_anterior(vista, "P1 Crítica", horizonte)
        if insert_metrica(vista, "P1 Crítica", metric['valor'], valor_anterior, horizonte_dias=horizonte):
            conteo['exitosas'] += 1
        else:
            conteo['fallidas'] += 1
        
        # P2 Alta
        metric = calc_conteo_prioridad("P2_alta", horizonte)
        valor_anterior = get_valor_anterior(vista, "P2 Alta", horizonte)
        if insert_metrica(vista, "P2 Alta", metric['valor'], valor_anterior, horizonte_dias=horizonte):
            conteo['exitosas'] += 1
        else:
            conteo['fallidas'] += 1
    
    # Fallas anticipadas
    metric = calc_fallas_anticipadas_30d()
    valor_anterior = get_valor_anterior(vista, "Fallas anticipadas")
    if insert_metrica(vista, "Fallas anticipadas", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # MTBF
    metric = calc_mtbf_horas()
    valor_anterior = get_valor_anterior(vista, "MTBF")
    if insert_metrica(vista, "MTBF", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== VISTA 2: PLAN DE ACCIÓN ==========
    log.info("\n🔧 VISTA 2: PLAN DE ACCIÓN")
    log.info("-" * 90)
    
    vista = "Plan de Acción"
    
    # Intervenciones próximas (7, 30, 90 días)
    for dias in [7, 30, 90]:
        metric = calc_intervenciones_proximas(dias)
        valor_anterior = get_valor_anterior(vista, f"Intervenciones próximas {dias}d", dias)
        if insert_metrica(vista, f"Intervenciones próximas {dias}d", metric['valor'], 
                         valor_anterior, horizonte_dias=dias):
            conteo['exitosas'] += 1
        else:
            conteo['fallidas'] += 1
    
    # Backlog OT
    metric = calc_backlog_ot()
    valor_anterior = get_valor_anterior(vista, "Backlog OT")
    if insert_metrica(vista, "Backlog OT", metric['valor'], valor_anterior):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Cumplimiento PM
    metric = calc_cumplimiento_pm()
    valor_anterior = get_valor_anterior(vista, "Cumplimiento PM")
    if insert_metrica(vista, "Cumplimiento PM", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== VISTA 3: IMPACTO Y DESEMPEÑO ==========
    log.info("\n💼 VISTA 3: IMPACTO Y DESEMPEÑO")
    log.info("-" * 90)
    
    vista = "Impacto y Desempeño"
    
    # Costo evitado
    metric = calc_costo_evitado_acumulado()
    valor_anterior = get_valor_anterior(vista, "Costo evitado")
    if insert_metrica(vista, "Costo evitado", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Downtime evitado
    metric = calc_downtime_evitado_horas()
    valor_anterior = get_valor_anterior(vista, "Downtime evitado")
    if insert_metrica(vista, "Downtime evitado", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Costo mantenimiento por km
    metric = calc_costo_mantenimiento_km()
    valor_anterior = get_valor_anterior(vista, "Costo mantenimiento km")
    if insert_metrica(vista, "Costo mantenimiento km", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Costo mantenimiento por unidad
    metric = calc_costo_mantenimiento_unidad()
    valor_anterior = get_valor_anterior(vista, "Costo mantenimiento unidad")
    if insert_metrica(vista, "Costo mantenimiento unidad", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== RESUMEN ==========
    duracion = (datetime.now() - inicio).total_seconds()
    
    log.info("\n" + "=" * 90)
    log.info("✅ CÁLCULO COMPLETADO")
    log.info("=" * 90)
    log.info(f"Métricas exitosas:  {conteo['exitosas']}")
    log.info(f"Métricas fallidas:  {conteo['fallidas']}")
    log.info(f"Duración total:     {duracion:.2f} segundos")
    log.info("=" * 90)
    
    return True


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    try:
        calcular_todas_metricas()
    except KeyboardInterrupt:
        log.info("\n⚠️  Interrumpido por usuario")
        sys.exit(0)
    except Exception as e:
        log.error(f"\n❌ Error fatal: {e}", exc_info=True)
        sys.exit(1)
