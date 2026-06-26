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


def check_table_exists(table_name: str) -> bool:
    """Verifica si una tabla existe en el schema public."""
    result = query_db("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        ) AS existe;
    """, (table_name,))
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
       SELECT COUNT(DISTINCT sr.activo_id) AS n
       FROM scoring_resultados sr
       JOIN activos a ON sr.activo_id = a.activo_id
       WHERE sr.prioridad = %s
         AND sr.horizonte_dias = %s
         AND sr.fecha_scoring = (
             SELECT MAX(fecha_scoring) FROM scoring_resultados
             WHERE horizonte_dias = %s
         )
         AND UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
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
        FROM feedback_taller ft
        JOIN activos a ON ft.activo_id = a.activo_id
        WHERE ft.falla_confirmada = TRUE
          AND ft.fecha_alerta >= CURRENT_DATE - INTERVAL '30 days'
          AND UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
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
            SELECT SUM(COALESCE(dd.horas_operativas, 0)) AS h_op
            FROM disponibilidad_diaria dd
            JOIN activos a ON dd.activo_id = a.activo_id
            WHERE dd.fecha >= CURRENT_DATE - INTERVAL '90 days'
              AND UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
        ),
        fallas AS (
            SELECT COUNT(*)::numeric AS n
            FROM ordenes_trabajo ot
            JOIN activos a ON ot.activo_id = a.activo_id
            WHERE LOWER(COALESCE(ot.tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')
              AND ot.fecha_apertura >= CURRENT_DATE - INTERVAL '90 days'
              AND UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
        )
        SELECT
            CASE WHEN fallas.n > 0 THEN horas.h_op / fallas.n ELSE NULL END AS mtbf
        FROM horas, fallas;
    """)    

    if result and result[0]['mtbf'] is not None:
        return {'valor': float(result[0]['mtbf']), 'tipo': 'HORAS'}
    return {'valor': None, 'tipo': 'HORAS', 'nota': 'Sin datos suficientes'}


# FUNCIONES DE CÁLCULO — MAPA DE CALOR 
def calc_mapa_calor_sistemas() -> list:
    """
    Calcula fallas históricas por sistema y horizonte (discretos: 7, 30, 90 días).
    Retorna lista de dicts: [{'sistema': 'motor', 'horizonte': 7, 'valor': 3}, ...]
    """
    if not (check_table_exists("ot_falla_evento") and check_table_exists("taxonomia_fallas")):
        return []
    
    result = query_db("""
        WITH ventanas AS (
            SELECT
                COALESCE(NULLIF(LOWER(tf.sistema), ''), 'sin_clasificar') AS sistema,
                CASE
                    WHEN COALESCE(ofe.fecha_evento, ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '7 days'  THEN 7
                    WHEN COALESCE(ofe.fecha_evento, ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '30 days' THEN 30
                    WHEN COALESCE(ofe.fecha_evento, ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '90 days' THEN 90
                    ELSE NULL
                END AS horizonte
            FROM ot_falla_evento ofe
            JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
            LEFT JOIN ordenes_trabajo ot ON ofe.ot_id = ot.ot_id
        )
        SELECT sistema, horizonte, COUNT(*) AS n
        FROM ventanas
        WHERE horizonte IS NOT NULL
        GROUP BY sistema, horizonte
        ORDER BY sistema, horizonte;
    """)
    
    rows = []
    if result:
        for row in result:
            rows.append({
                'sistema': row['sistema'],
                'horizonte': int(row['horizonte']),
                'valor': int(row['n'])
            })
    return rows


# ============================================================================
# FUNCIONES DE CÁLCULO — VISTA 2: PLAN DE ACCIÓN
# ============================================================================

def calc_intervenciones_proximas(dias: int) -> dict:
    """Cuenta P1+P2 en horizonte dado."""
    p1_result = query_db("""
        SELECT COUNT(DISTINCT sr.activo_id) AS n
        FROM scoring_resultados sr
        JOIN activos a ON sr.activo_id = a.activo_id
        WHERE sr.prioridad = 'P1_critica'
          AND sr.horizonte_dias = %s
          AND sr.fecha_scoring = (SELECT MAX(fecha_scoring) FROM scoring_resultados WHERE horizonte_dias = %s)
          AND UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
    """, (dias, dias))
    p1 = float(p1_result[0]['n']) if p1_result else 0
    
    p2_result = query_db("""
        SELECT COUNT(DISTINCT sr.activo_id) AS n
        FROM scoring_resultados sr
        JOIN activos a ON sr.activo_id = a.activo_id
        WHERE sr.prioridad = 'P2_alta'
          AND sr.horizonte_dias = %s
          AND sr.fecha_scoring = (
              SELECT MAX(fecha_scoring) FROM scoring_resultados 
              WHERE horizonte_dias = %s
          )
          AND UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
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

def calc_pm_vencidos_tabla() -> list:
    """Obtiene lista de 10 activos con PM vencida (>90 días o nunca tuvieron)."""
    if not table_exists("ot_falla_evento") or not table_exists("taxonomia_fallas"):
        result = query_db("""
            WITH ultima_pm AS (
                SELECT activo_id, MAX(fecha_apertura) AS ultima_pm_fecha
                FROM ordenes_trabajo
                WHERE LOWER(COALESCE(tipo_ot, '')) IN ('preventiva', 'preventivo')
                GROUP BY activo_id
            )
            SELECT
                a.patente,
                COALESCE((CURRENT_DATE - up.ultima_pm_fecha::date)::text || ' días', 'Nunca') AS pm_vencida,
                'Sin clasificar' AS proximo_sistema,
                ROW_NUMBER() OVER (ORDER BY up.ultima_pm_fecha NULLS FIRST) AS orden
            FROM activos a
            LEFT JOIN ultima_pm up ON up.activo_id = a.activo_id
            WHERE UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
              AND (up.ultima_pm_fecha IS NULL OR (CURRENT_DATE - up.ultima_pm_fecha::date) > 90)
            ORDER BY up.ultima_pm_fecha NULLS FIRST
            LIMIT 10;
        """)
    else:
        result = query_db("""
            WITH ultima_pm AS (
                SELECT activo_id, MAX(fecha_apertura) AS ultima_pm_fecha
                FROM ordenes_trabajo
                WHERE LOWER(COALESCE(tipo_ot, '')) IN ('preventiva', 'preventivo')
                GROUP BY activo_id
            ),
            ultimo_evento AS (
                SELECT DISTINCT ON (activo_id) activo_id, sistema
                FROM ot_falla_evento ofe
                JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
                WHERE activo_id IS NOT NULL
                ORDER BY activo_id, ofe.fecha_evento DESC NULLS LAST
            )
            SELECT
                a.patente,
                COALESCE((CURRENT_DATE - up.ultima_pm_fecha::date)::text || ' días', 'Nunca') AS pm_vencida,
                COALESCE(ue.sistema, 'Sin clasificar') AS proximo_sistema,
                ROW_NUMBER() OVER (ORDER BY up.ultima_pm_fecha NULLS FIRST) AS orden
            FROM activos a
            LEFT JOIN ultima_pm up ON up.activo_id = a.activo_id
            LEFT JOIN ultimo_evento ue ON ue.activo_id = a.activo_id
            WHERE UPPER(COALESCE(a.estado_actual, 'Activo')) = 'ACTIVO'
              AND (up.ultima_pm_fecha IS NULL OR (CURRENT_DATE - up.ultima_pm_fecha::date) > 90)
            ORDER BY up.ultima_pm_fecha NULLS FIRST
            LIMIT 10;
        """)
    
    if result is None or len(result) == 0:
        return []
    
    return list(result)

def guardar_pm_vencidos_tabla(registros: list) -> bool:
    """Guarda lista de PM vencidos en tabla paneles_pm_vencidos."""
    if not table_exists("paneles_pm_vencidos"):
        log.warning("⚠ Tabla 'paneles_pm_vencidos' no existe en Supabase")
        return False
    
    conn = get_connection()
    if conn is None:
        log.error("Guardar PM vencidos: sin conexión a BD")
        return False
    
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM paneles_pm_vencidos")
                if registros:
                    for idx, reg in enumerate(registros, 1):
                        cur.execute("""
                            INSERT INTO paneles_pm_vencidos 
                            (patente, pm_vencida, proximo_sistema, orden, fecha_calculo)
                            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        """, (reg['patente'], reg['pm_vencida'], reg['proximo_sistema'], idx))
        
        log.info(f"✓ PM vencidos tabla: {len(registros)} activos vencidos guardados")
        return True
    except Exception as e:
        log.error(f"Error guardando PM vencidos tabla: {str(e)[:100]}")
        return False
    finally:
        conn.close()

# ============================================================================
# FUNCIONES DE CÁLCULO — VISTA 2: SKU EN QUIEBRE E INTERVENCIONES SUGERIDAS
# ============================================================================

def calc_sku_en_quiebre() -> dict:
    """SKU con stock actual <= stock mínimo.
    
    Requiere tabla repuestos_maestro.
    Si no existe, retorna 0 con nota.
    """
    if not table_exists("repuestos_maestro"):
        log.warning("Tabla repuestos_maestro no existe → SKU en quiebre = 0")
        return {'valor': 0, 'tipo': 'COUNT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT COUNT(*) AS n 
        FROM repuestos_maestro
        WHERE stock_actual <= COALESCE(stock_minimo, 0);
    """)
    
    if result and result[0]['n'] is not None:
        valor = float(result[0]['n'])
        return {'valor': valor, 'tipo': 'COUNT'}
    
    return {'valor': 0, 'tipo': 'COUNT'}


def calcular_intervenciones_sugeridas() -> bool:
    """Calcula intervenciones sugeridas para h7, h30, h90 y las almacena.
    
    Lógica:
    1. Obtiene intervenciones P1+P2 para cada horizonte
    2. Para cada patente, determina si aplica a h7, h30, h90
    3. Calcula costos estimados
    4. Inserta en tabla intervenciones_sugeridas
    
    Retorna: True si exitoso, False si falla
    """
    
    if not table_exists("intervenciones_sugeridas"):
        log.warning("Tabla intervenciones_sugeridas no existe. Crear con:")
        log.warning("  CREATE TABLE intervenciones_sugeridas (...)")
        return False
    
    if not table_exists("scoring_resultados"):
        log.warning("Tabla scoring_resultados no existe → Sin intervenciones")
        return False
    
    try:
        # ====================================================================
        # PASO 1: Obtener intervenciones para TODOS los horizontes (7, 30, 90)
        # ====================================================================
        
        intervenciones = {}  # {patente: {h7, h30, h90, tipo, sistema, urgencia, costos}}
        
        for horizonte in [7, 30, 90]:
            log.info(f"  Procesando intervenciones h{horizonte}...")
            
            # Query para obtener intervenciones P1+P2 en este horizonte
            query = f"""
                WITH ultimo_scoring AS (
                    SELECT DISTINCT ON (activo_id)
                        activo_id, 
                        prioridad, 
                        probabilidad_falla,
                        sistema_en_riesgo
                    FROM scoring_resultados
                    WHERE horizonte_dias = {horizonte}
                    ORDER BY activo_id, fecha_scoring DESC
                )
                SELECT
                    a.patente,
                    a.activo_id,
                    us.prioridad AS urgencia,
                    us.probabilidad_falla,
                    COALESCE(us.sistema_en_riesgo, 'Sin clasificar') AS sistema,
                    CASE
                        WHEN us.sistema_en_riesgo = 'sin_historial_ot'
                            THEN 'Inspección inicial'
                        WHEN us.prioridad = 'P1_critica'
                            THEN 'Correctivo programado'
                        WHEN us.prioridad = 'P2_alta'
                            THEN 'Preventivo anticipado'
                        ELSE 'Inspección'
                    END AS tipo
                FROM activos a
                INNER JOIN ultimo_scoring us ON us.activo_id = a.activo_id
                WHERE us.prioridad IN ('P1_critica', 'P2_alta')
                  AND COALESCE(LOWER(a.estado_actual), 'operativo') 
                      NOT IN ('baja', 'fuera_servicio', 'inactivo')
                ORDER BY us.probabilidad_falla DESC;
            """
            
            result = query_db(query)
            
            if not result:
                log.warning(f"    Sin intervenciones para h{horizonte}")
                continue
            
            # ================================================================
            # PASO 2: Procesar intervenciones obtenidas
            # ================================================================
            
            for row in result:
                patente = row['patente']
                
                if patente not in intervenciones:
                    intervenciones[patente] = {
                        'activo_id': row['activo_id'],
                        'tipo': row['tipo'],
                        'sistema': row['sistema'],
                        'urgencia': row['urgencia'],
                        'probabilidad': row['probabilidad_falla'],
                        'h7': 0,
                        'h30': 0,
                        'h90': 0,
                        'costo_estimado': None,
                        'costo_no_intervenir': None
                    }
                
                # Marcar qué horizonte aplica
                if horizonte == 7:
                    intervenciones[patente]['h7'] = 1
                elif horizonte == 30:
                    intervenciones[patente]['h30'] = 1
                elif horizonte == 90:
                    intervenciones[patente]['h90'] = 1
            
            log.info(f"    ✅ {len(result)} intervenciones para h{horizonte}")
        
        
        # ====================================================================
        # PASO 3: Calcular costos estimados
        # ====================================================================
        
        log.info("  Calculando costos estimados...")
        
        # Obtener costos promedio por sistema desde OT históricas
        costos_query = """
            SELECT
                COALESCE(LOWER(
                    COALESCE(
                        (SELECT tf.sistema FROM ot_falla_evento ofe
                         JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
                         WHERE ofe.ot_id = ot.ot_id
                         ORDER BY ofe.fecha_evento DESC NULLS LAST LIMIT 1),
                        'sin_sistema'
                    )
                ), 'sin_sistema') AS sistema,
                AVG(COALESCE(ot.costo_total_clp, 0))::numeric(12,0) AS costo_promedio
            FROM ordenes_trabajo ot
            WHERE ot.fecha_cierre IS NOT NULL
              AND LOWER(COALESCE(ot.tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')
            GROUP BY sistema;
        """
        
        costos_result = query_db(costos_query)
        costos_por_sistema = {}
        
        if costos_result:
            for row in costos_result:
                sistema_key = (row['sistema'] or 'sin_sistema').lower()
                costo = float(row['costo_promedio'] or 0)
                costos_por_sistema[sistema_key] = costo
        
        log.info(f"    ✅ Costos obtenidos para {len(costos_por_sistema)} sistemas")
        
        
        # ====================================================================
        # PASO 4: Asignar costos a intervenciones
        # ====================================================================
        
        for patente, datos in intervenciones.items():
            sistema_key = (datos['sistema'] or 'sin_sistema').lower()
            
            # Costo estimado = costo promedio del sistema
            costo_estimado = costos_por_sistema.get(sistema_key, 0)
            datos['costo_estimado'] = costo_estimado if costo_estimado > 0 else None
            
            # Costo de NO intervenir = costo_estimado × probabilidad × factor downtime
            # Factor downtime: penalización por no intervenir (3 = 3 veces más costoso)
            if datos['costo_estimado']:
                prob = float(datos['probabilidad'] or 0)
                datos['costo_no_intervenir'] = datos['costo_estimado'] * prob * 3
            else:
                datos['costo_no_intervenir'] = None
        
        
        # ====================================================================
        # PASO 5: Truncar e insertar en tabla intervenciones_sugeridas
        # ====================================================================
        
        log.info("  Actualizando tabla intervenciones_sugeridas...")
        
        conn = get_connection()
        if conn is None:
            log.error("  ❌ Sin conexión a BD")
            return False
        
        try:
            with conn:
                with conn.cursor() as cur:
                    # Truncar tabla (borra todos los registros)
                    cur.execute("TRUNCATE TABLE intervenciones_sugeridas")
                    log.info("    ✅ Tabla truncada")
                    
                    # Insertar nuevos registros
                    insert_count = 0
                    
                    for patente, datos in intervenciones.items():
                        cur.execute("""
                            INSERT INTO intervenciones_sugeridas 
                            (patente, activo_id, tipo, sistema, urgencia, 
                             costo_estimado, costo_no_intervenir, h7, h30, h90, fecha_calculo)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        """, (
                            patente,
                            datos['activo_id'],
                            datos['tipo'],
                            datos['sistema'],
                            datos['urgencia'],
                            datos['costo_estimado'],
                            datos['costo_no_intervenir'],
                            datos['h7'],
                            datos['h30'],
                            datos['h90']
                        ))
                        insert_count += 1
                    
                    log.info(f"    ✅ {insert_count} registros insertados")
            
            return True
        
        except Exception as e:
            log.error(f"  ❌ Error insertando intervenciones: {e}")
            return False
    
    except Exception as e:
        log.error(f"  ❌ Error en calcular_intervenciones_sugeridas: {e}")
        return False


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
        return {'valor': valor, 'tipo': 'CLP'}
    return {'valor': 0.0, 'tipo': 'CLP'}


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
        return {'valor': valor, 'tipo': 'HORAS'}
    return {'valor': 0.0, 'tipo': 'HORAS'}


def calc_costo_mantenimiento_km() -> dict:
    """Costo de mantenimiento por kilometro últimos 30 días."""
    col_costo = "costo_total_clp" if column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    result = query_db(f"""
        SELECT
            COALESCE(SUM(CASE WHEN ot.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                             THEN ot.{col_costo} ELSE 0 END), 0) AS costo_total,
            COALESCE(MAX(CASE WHEN ot.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                             THEN odometro_km ELSE NULL END), 0) -
            COALESCE(MIN(CASE WHEN ot.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                             THEN odometro_km ELSE NULL END), 0) AS km_recorridos
        FROM ordenes_trabajo ot;
    """)
    
    km = float(result[0]['km_recorridos'])
    if km > 0:
        valor = float(result[0]['costo_total']) / km
        return {'valor': valor, 'tipo': 'CLP'}
    return {'valor': None, 'tipo': 'CLP'}

def calc_costo_mantenimiento_unidad() -> dict:
    """Costo de mantenimiento por unidad operativa (últimos 30 días)."""
    col_costo = "costo_total_clp" if column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    result = query_db(f"""
    SELECT
        COALESCE(SUM(CASE WHEN ot.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                         THEN ot.{col_costo} ELSE 0 END), 0) AS costo_total,
        COALESCE(COUNT(DISTINCT CASE WHEN ot.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' 
                                    THEN ot.activo_id END), 0) AS n_unidades
    FROM ordenes_trabajo ot;
    """)
    
    n_unidades = float(result[0]['n_unidades'])
    if n_unidades > 0:
        valor = float(result[0]['costo_total']) / n_unidades
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
# FUNCIONES DE CÁLCULO — VISTA 3: IMPACTO Y DESEMPEÑO
# ============================================================================

def calc_p1_feedback() -> dict:
    """M1: Unidades con P1 confirmado en feedback."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'COUNT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT COUNT(DISTINCT f.activo_id) as valor
        FROM feedback_taller f
        WHERE f.falla_confirmada = TRUE
          AND EXISTS (
              SELECT 1 FROM scoring_resultados s 
              WHERE s.scoring_id = f.scoring_id 
              AND s.prioridad = 'P1_critica'
          )
    """)
    valor = int(result[0]['valor']) if result and result[0]['valor'] else 0
    return {'valor': valor, 'tipo': 'COUNT'}


def calc_p2_feedback() -> dict:
    """M2: Unidades con P2 confirmado en feedback."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'COUNT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT COUNT(DISTINCT f.activo_id) as valor
        FROM feedback_taller f
        WHERE f.falla_confirmada = TRUE
          AND EXISTS (
              SELECT 1 FROM scoring_resultados s 
              WHERE s.scoring_id = f.scoring_id 
              AND s.prioridad = 'P2_alta'
          )
    """)
    valor = int(result[0]['valor']) if result and result[0]['valor'] else 0
    return {'valor': valor, 'tipo': 'COUNT'}


def calc_disponibilidad_operacional_30d() -> dict:
    """M3: Disponibilidad operacional últimos 30 días (%)."""
    if not check_table_exists("disponibilidad_diaria"):
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
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
    """)
    valor = float(result[0]['valor']) if result and result[0]['valor'] else 0.0
    return {'valor': valor, 'tipo': 'PCT'}


def calc_mtbf_90d() -> dict:
    """M4: MTBF flota últimos 90 días (horas)."""
    if not check_table_exists("ordenes_trabajo"):
        return {'valor': None, 'tipo': 'NUMERIC', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        WITH activos_activos AS (
            SELECT DISTINCT activo_id
            FROM activos
            WHERE UPPER(COALESCE(estado_actual, 'Activo')) = 'ACTIVO'
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
    """)
    valor = float(result[0]['valor']) if result and result[0]['valor'] else 0.0
    return {'valor': valor, 'tipo': 'NUMERIC'}


def calc_mttr_90d() -> dict:
    """M5: MTTR flota últimos 90 días (horas), solo activos activos."""
    if not check_table_exists("ordenes_trabajo"):
        return {'valor': None, 'tipo': 'NUMERIC', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        WITH activos_activos AS (
            SELECT DISTINCT activo_id
            FROM activos
            WHERE UPPER(COALESCE(estado_actual, 'Activo')) = 'ACTIVO'
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
    """)
    valor = float(result[0]['valor']) if result and result[0]['valor'] else 0.0
    return {'valor': valor, 'tipo': 'NUMERIC'}


def calc_tasa_alertas_confirmadas() -> dict:
    """M6: Tasa de alertas confirmadas (%), confiabilidad del modelo."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falla_confirmada = TRUE THEN 1 END) as confirmadas
        FROM feedback_taller
    """)
    
    if result and result[0]:
        total = result[0]['total_feedback']
        confirmadas = result[0]['confirmadas'] or 0
        if total and total > 0:
            valor = (confirmadas / total) * 100
            return {'valor': valor, 'tipo': 'PCT'}
    return {'valor': 0.0, 'tipo': 'PCT', 'nota': 'Sin datos'}


def calc_recall() -> dict:
    """M14: Recall del modelo desde modelos_registro."""
    if not check_table_exists("modelos_registro"):
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT recall as valor
        FROM modelos_registro
        WHERE es_activo = TRUE
        ORDER BY fecha_creacion DESC
        LIMIT 1
    """)
    
    valor = float(result[0]['valor']) * 100 if result and result[0]['valor'] else 0.0
    return {'valor': valor, 'tipo': 'PCT'}


def calc_precision() -> dict:
    """M15: Precision del modelo desde modelos_registro."""
    if not check_table_exists("modelos_registro"):
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT precision as valor
        FROM modelos_registro
        WHERE es_activo = TRUE
        ORDER BY fecha_creacion DESC
        LIMIT 1
    """)
    
    valor = float(result[0]['valor']) * 100 if result and result[0]['valor'] else 0.0
    return {'valor': valor, 'tipo': 'PCT'}


def calc_anticipacion_promedio() -> dict:
    """M16: Anticipación promedio (días) — desde fecha_alerta a fecha_apertura OT correctiva."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'NUMERIC', 'nota': 'Tabla faltante'}
    
    result = query_db("""
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
    """)
    
    valor = float(result[0]['valor']) if result and result[0]['valor'] else 0.0
    return {'valor': valor, 'tipo': 'NUMERIC'}


def calc_pct_alertas_confirmadas() -> dict:
    """M17: % Alertas confirmadas."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falla_confirmada = TRUE THEN 1 END) as confirmadas
        FROM feedback_taller
    """)
    
    if result and result[0]:
        total = result[0]['total_feedback']
        confirmadas = result[0]['confirmadas'] or 0
        if total and total > 0:
            valor = (confirmadas / total) * 100
            return {'valor': valor, 'tipo': 'PCT'}
    return {'valor': 0.0, 'tipo': 'PCT', 'nota': 'Sin datos'}


def calc_pct_alertas_rechazadas() -> dict:
    """M18: % Alertas rechazadas (falsa_alarma = TRUE)."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falsa_alarma = TRUE THEN 1 END) as rechazadas
        FROM feedback_taller
    """)
    
    if result and result[0]:
        total = result[0]['total_feedback']
        rechazadas = result[0]['rechazadas'] or 0
        if total and total > 0:
            valor = (rechazadas / total) * 100
            return {'valor': valor, 'tipo': 'PCT'}
    return {'valor': 0.0, 'tipo': 'PCT', 'nota': 'Sin datos'}


def calc_pct_alertas_pendientes() -> dict:
    """M19: % Alertas pendientes (falla_confirmada IS NULL AND falsa_alarma IS FALSE)."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT 
            COUNT(*) as total_feedback,
            COUNT(CASE WHEN falla_confirmada IS NULL AND falsa_alarma IS FALSE THEN 1 END) as pendientes
        FROM feedback_taller
    """)
    
    if result and result[0]:
        total = result[0]['total_feedback']
        pendientes = result[0]['pendientes'] or 0
        if total and total > 0:
            valor = (pendientes / total) * 100
            return {'valor': valor, 'tipo': 'PCT'}
    return {'valor': 0.0, 'tipo': 'PCT', 'nota': 'Sin datos'}


def calc_matriz_confusion() -> dict:
    """M20: Matriz confusión — retorna dict con TP, FP, FN, TN."""
    if not check_table_exists("feedback_taller") or not check_table_exists("scoring_resultados"):
        return {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0, 'nota': 'Tabla faltante'}
    
    result = query_db("""
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
    """)
    
    if result and result[0]:
        return {
            'tp': int(result[0]['tp'] or 0),
            'fp': int(result[0]['fp'] or 0),
            'fn': int(result[0]['fn'] or 0),
            'tn': int(result[0]['tn'] or 0)
        }
    return {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0}


def calc_alertas_confirmadas_count() -> dict:
    """M21a: Conteo de alertas confirmadas."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'COUNT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT COUNT(*) as valor
        FROM feedback_taller
        WHERE falla_confirmada = TRUE
    """)
    
    valor = int(result[0]['valor']) if result and result[0]['valor'] else 0
    return {'valor': valor, 'tipo': 'COUNT'}


def calc_alertas_rechazadas_count() -> dict:
    """M21b: Conteo de alertas rechazadas."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'COUNT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT COUNT(*) as valor
        FROM feedback_taller
        WHERE falsa_alarma = TRUE
    """)
    
    valor = int(result[0]['valor']) if result and result[0]['valor'] else 0
    return {'valor': valor, 'tipo': 'COUNT'}


def calc_alertas_pendientes_count() -> dict:
    """M21c: Conteo de alertas pendientes."""
    if not check_table_exists("feedback_taller"):
        return {'valor': None, 'tipo': 'COUNT', 'nota': 'Tabla faltante'}
    
    result = query_db("""
        SELECT COUNT(*) as valor
        FROM feedback_taller
        WHERE falla_confirmada IS NULL AND falsa_alarma IS FALSE
    """)
    
    valor = int(result[0]['valor']) if result and result[0]['valor'] else 0
    return {'valor': valor, 'tipo': 'COUNT'}


def calc_cobertura_stock() -> dict:
    """% de demanda P1/P2 cubierta por stock disponible.
    
    Lee de repuestos_panel_criticos (tabla de demanda con acciones).
    Mide: (SKUs que alcanzan cobertura de lead_time) / (SKUs totales con demanda P1/P2) × 100%
    """
    if not table_exists("repuestos_panel_criticos"):
        log.warning("Tabla repuestos_panel_criticos no existe → Cobertura stock = None")
        return {'valor': None, 'tipo': 'PCT', 'nota': 'Panel de demanda no disponible'}
    
    result = query_db("""
        SELECT 
            COUNT(*) AS total_skus,
            COUNT(CASE WHEN cobertura_dias >= lead_time_dias THEN 1 END) AS skus_cubiertos
        FROM repuestos_panel_criticos
        WHERE demanda_30d_prediccion > 0;
    """)
    
    if result and len(result) > 0 and result[0]['total_skus'] and int(result[0]['total_skus']) > 0:
        valor = float(result[0]['skus_cubiertos']) / float(result[0]['total_skus']) * 100.0
        return {'valor': valor, 'tipo': 'PCT'}
    return {'valor': None, 'tipo': 'PCT', 'nota': 'Sin demanda P1/P2'}

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
    
    # Mapa de calor: una fila por cada (sistema, horizonte)
    log.info("\n🗺️ MAPA DE CALOR: Fallas por sistema")
    vista = "Mapa de calor"
    metricas_calor = calc_mapa_calor_sistemas()
    for metrica_calor in metricas_calor:
        sistema = metrica_calor['sistema']
        horizonte = metrica_calor['horizonte']
        valor = metrica_calor['valor']
        
        valor_anterior = get_valor_anterior(vista, sistema, horizonte_dias=horizonte)
        if insert_metrica(vista, sistema, valor, valor_anterior, horizonte_dias=horizonte):
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
    
    # SKU en quiebre
    metric = calc_sku_en_quiebre()
    valor_anterior = get_valor_anterior(vista, "SKU en quiebre")
    if insert_metrica(vista, "SKU en quiebre", metric['valor'], valor_anterior, 
                     nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Intervenciones sugeridas (tabla completa)
    log.info("  Calculando intervenciones sugeridas...")
    if calcular_intervenciones_sugeridas():
        log.info("    ✅ Intervenciones sugeridas calculadas")
        conteo['exitosas'] += 1
    else:
        log.error("    ❌ Error calculando intervenciones sugeridas")
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
    
    # PM vencidos (tabla de 10 activos)
    registros_pm_vencidos = calc_pm_vencidos_tabla()
    if guardar_pm_vencidos_tabla(registros_pm_vencidos):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== VISTA 3: IMPACTO Y DESEMPEÑO ==========    
    # ========== VISTA 3: IMPACTO Y DESEMPEÑO ==========
    log.info("\n💼 VISTA 3: IMPACTO Y DESEMPEÑO")
    log.info("-" * 90)
    
    vista = "Impacto y Desempeño"
    
    # ========== MÉTRICAS ECONÓMICAS ==========
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
    
    # Costo mantenimiento por km y por unidad
    metric = calc_costo_mantenimiento_km()
    valor_anterior = get_valor_anterior(vista, "Costo mantenimiento km")
    if insert_metrica(vista, "Costo mantenimiento km", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1

    metric = calc_costo_mantenimiento_unidad()
    valor_anterior = get_valor_anterior(vista, "Costo mantenimiento unidad")
    if insert_metrica(vista, "Costo mantenimiento unidad", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== MÉTRICAS OPERACIONALES ==========
    # Disponibilidad 30d
    metric = calc_disponibilidad_operacional_30d()
    valor_anterior = get_valor_anterior(vista, "Disponibilidad 30d")
    if insert_metrica(vista, "Disponibilidad 30d", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # MTBF 90d
    metric = calc_mtbf_90d()
    valor_anterior = get_valor_anterior(vista, "MTBF 90d")
    if insert_metrica(vista, "MTBF 90d", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # MTTR 90d
    metric = calc_mttr_90d()
    valor_anterior = get_valor_anterior(vista, "MTTR 90d")
    if insert_metrica(vista, "MTTR 90d", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Tasa alertas confirmadas
    metric = calc_tasa_alertas_confirmadas()
    valor_anterior = get_valor_anterior(vista, "Tasa alertas confirmadas")
    if insert_metrica(vista, "Tasa alertas confirmadas", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== FEEDBACK TALLER ==========
    # P1 confirmadas
    metric = calc_p1_feedback()
    valor_anterior = get_valor_anterior(vista, "P1 confirmadas")
    if insert_metrica(vista, "P1 confirmadas", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # P2 confirmadas
    metric = calc_p2_feedback()
    valor_anterior = get_valor_anterior(vista, "P2 confirmadas")
    if insert_metrica(vista, "P2 confirmadas", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== DESEMPEÑO DEL MODELO ==========
    # Recall
    metric = calc_recall()
    valor_anterior = get_valor_anterior(vista, "Recall")
    if insert_metrica(vista, "Recall", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Precision
    metric = calc_precision()
    valor_anterior = get_valor_anterior(vista, "Precision")
    if insert_metrica(vista, "Precision", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Anticipación promedio
    metric = calc_anticipacion_promedio()
    valor_anterior = get_valor_anterior(vista, "Anticipacion promedio")
    if insert_metrica(vista, "Anticipacion promedio", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # % Confirmadas
    metric = calc_pct_alertas_confirmadas()
    valor_anterior = get_valor_anterior(vista, "% Alertas confirmadas")
    if insert_metrica(vista, "% Alertas confirmadas", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # % Rechazadas
    metric = calc_pct_alertas_rechazadas()
    valor_anterior = get_valor_anterior(vista, "% Alertas rechazadas")
    if insert_metrica(vista, "% Alertas rechazadas", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # % Pendientes
    metric = calc_pct_alertas_pendientes()
    valor_anterior = get_valor_anterior(vista, "% Alertas pendientes")
    if insert_metrica(vista, "% Alertas pendientes", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Conteos de alertas
    metric = calc_alertas_confirmadas_count()
    valor_anterior = get_valor_anterior(vista, "Alertas confirmadas (count)")
    if insert_metrica(vista, "Alertas confirmadas (count)", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    metric = calc_alertas_rechazadas_count()
    valor_anterior = get_valor_anterior(vista, "Alertas rechazadas (count)")
    if insert_metrica(vista, "Alertas rechazadas (count)", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    metric = calc_alertas_pendientes_count()
    valor_anterior = get_valor_anterior(vista, "Alertas pendientes (count)")
    if insert_metrica(vista, "Alertas pendientes (count)", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # Matriz de confusión
    matriz = calc_matriz_confusion()
    valor_anterior = get_valor_anterior(vista, "Matriz TP")
    if insert_metrica(vista, "Matriz TP", matriz['tp'], valor_anterior):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    if insert_metrica(vista, "Matriz FP", matriz['fp'], None):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    if insert_metrica(vista, "Matriz FN", matriz['fn'], None):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    if insert_metrica(vista, "Matriz TN", matriz['tn'], None):
        conteo['exitosas'] += 1
    else:
        conteo['fallidas'] += 1
    
    # ========== OPERACIONES ==========
    # Cobertura stock
    metric = calc_cobertura_stock()
    valor_anterior = get_valor_anterior(vista, "Cobertura stock")
    if insert_metrica("Plan de Acción", "Cobertura stock", metric['valor'], valor_anterior, nota=metric.get('nota', '')):
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
