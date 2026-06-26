"""
BAITECK — Dashboard Predictivo de Flotas — Versión conectada a Supabase
========================================================================

Migración de dashboard_com.py a fuente real de datos (Supabase / PostgreSQL).

Filosofía de esta versión:
  - Look and feel IDÉNTICO a dashboard_com.py (3 vistas, layout, logo, CSS)
  - TODOS los datos vienen de Supabase. Nada de np.random ni listas ficticias.
  - Si una tabla no existe o está vacía, se muestra estado vacío controlado:
      * El componente visual se mantiene
      * Se renderiza con cero / "Sin datos disponibles" / banner informativo
      * El dashboard NUNCA cae por un dato faltante
  - Conexión: psycopg2 directo (decisión heredada del v2.0 — intentos previos
    de migrar a SQLAlchemy en el dashboard fallaron; ver obs. 12.8).
  - Las funciones de lectura están agrupadas y separadas de la lógica visual.

Estado esperado de Supabase al ejecutarse este dashboard:
  - activos (5 registros confirmados)
  - ordenes_trabajo (25 registros confirmados)
  - repuestos_consumidos (5 registros confirmados)
  - modelos_registro
  - scoring_resultados

Tablas que aún NO existen pero el dashboard ya está preparado para consumirlas:
  - feedback_alertas
  - taxonomia_fallas / ot_sistemas_afectados
  - disponibilidad_diaria
  - repuestos_maestro

Variables de entorno requeridas en .env:
  DATABASE_URL=postgresql://postgres.<ref>:<pass>@<host>.pooler.supabase.com:5432/postgres?sslmode=require

Autor: BAITECK — mayo 2026
"""

import os
from dotenv import load_dotenv
load_dotenv()  # Cargar variables de .env

import pandas as pd
import numpy as np  # se mantiene importado por compatibilidad con plotly, no se usa para inventar datos
import psycopg2
import streamlit as st
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from typing import Optional, Dict, Tuple

# ============================================================================
# CONFIG Y CONEXIÓN
# ============================================================================

st.set_page_config(
    page_title="BAITECK — Dashboard PDM",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personalizado — IDÉNTICO a dashboard_com.py
st.markdown("""
    <style>
    .hero-metric {
        font-size: 28px;
        font-weight: bold;
        text-align: center;
        padding: 10px;
        border-radius: 5px;
    }
    .metric-green { background-color: #d4edda; color: #155724; }
    .metric-yellow { background-color: #fff3cd; color: #856404; }
    .metric-red { background-color: #f8d7da; color: #721c24; }
    .candado { color: #ccc; font-size: 12px; }

    /* Estilos para el logo en esquina superior derecha */
    .logo-container {
        display: flex;
        justify-content: flex-end;
        padding: 10px 15px 0 0;
        margin: 0 0 -80px 0;
    }
    .logo-baiteck {
        width: 100px;
        height: auto;
        object-fit: contain;
    }
    .empty-state {
        background-color: #f8f9fa;
        border: 1px dashed #adb5bd;
        border-radius: 6px;
        padding: 20px;
        text-align: center;
        color: #6c757d;
        font-size: 13px;
    }
    </style>
""", unsafe_allow_html=True)


def get_db_connection():
    """Conexión a Supabase vía psycopg2.

    Mantiene el patrón silencioso de dashboard_com.py: si no hay DATABASE_URL
    o la conexión falla, retorna None y el dashboard sigue operando con
    estados vacíos en lugar de explotar.
    
    No emite mensajes — los mensajes de estado se muestran UNA SOLA VEZ en main().
    """
    try:
        url = os.getenv("DATABASE_URL")
        if not url:
            return None
        conn = psycopg2.connect(url, connect_timeout=5)
        return conn
    except Exception:
        return None


def query_db(query_sql, params=None):
    """Ejecuta query SQL y retorna DataFrame.

    Retorna DataFrame vacío si:
      - No hay conexión
      - La query falla (tabla inexistente, columna inexistente, etc.)
    Esto permite que cada bloque visual decida cómo renderizar el estado
    vacío sin que el dashboard se detenga.
    """
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    try:
        # Usamos una conexión nueva por query para evitar el problema
        # de conexión muerta cuando Streamlit recarga
        df = pd.read_sql(query_sql, conn, params=params)
        return df
    except Exception:
        # Reset de la conexión si la query falló (puede dejar transacción rota)
        try:
            conn.rollback()
        except Exception:
            pass
        return pd.DataFrame()


def check_table_exists(table_name: str) -> bool:
    """Verifica si una tabla existe en el schema public de Supabase."""
    q = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %(t)s
        ) AS existe;
    """
    df = query_db(q, params={"t": table_name})
    if df.empty:
        return False
    return bool(df.iloc[0]["existe"])


def check_column_exists(table_name: str, column_name: str) -> bool:
    """Verifica si una columna existe en una tabla del schema public."""
    q = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %(t)s
              AND column_name = %(c)s
        ) AS existe;
    """
    df = query_db(q, params={"t": table_name, "c": column_name})
    if df.empty:
        return False
    return bool(df.iloc[0]["existe"])


# ============================================================================
# FUNCIONES DE LECTURA DESDE SUPABASE
# ----------------------------------------------------------------------------
# Cada función está separada de la lógica visual. Devuelven DataFrame.
# Si la tabla no existe o no hay datos, devuelven DataFrame vacío.
# ============================================================================

@st.cache_data(ttl=300)
def fetch_unidades_operativas() -> int:
    """Cuenta de unidades activas (no dadas de baja)."""
    df = query_db("""
        SELECT COUNT(*) AS n
        FROM activos
        WHERE COALESCE(LOWER(estado_actual), 'operativo') NOT IN ('baja', 'fuera_servicio', 'inactivo');
    """)
    if df.empty:
        return 0
    return int(df.iloc[0]["n"])


@st.cache_data(ttl=300)
def fetch_unidades_total() -> int:
    """Cuenta total de unidades en la flota (sin filtrar por estado)."""
    df = query_db("SELECT COUNT(*) AS n FROM activos;")
    if df.empty:
        return 0
    return int(df.iloc[0]["n"])


@st.cache_data(ttl=300)
def fetch_disponibilidad_30d() -> Optional[float]:
    """Disponibilidad operacional últimos 30 días.

    Estrategia jerárquica:
      1. Si existe tabla disponibilidad_diaria → cálculo directo
      2. Si no, retorna None (el visual debe manejar el caso)
    """
    if check_table_exists("disponibilidad_diaria"):
        df = query_db("""
            SELECT
                SUM(COALESCE(horas_operativas, 0)) AS op,
                SUM(COALESCE(horas_operativas, 0) +
                    COALESCE(horas_detenido_planificado, 0) +
                    COALESCE(horas_detenido_no_planificado, 0)) AS tot
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '30 days';
        """)
        if not df.empty and df.iloc[0]["tot"] and float(df.iloc[0]["tot"]) > 0:
            return float(df.iloc[0]["op"]) / float(df.iloc[0]["tot"]) * 100.0
    return None


@st.cache_data(ttl=300)
def fetch_conteo_prioridad(prioridad: str, horizonte_dias: int = 30) -> int:
    """Cuenta unidades con scoring más reciente en la prioridad dada."""
    df = query_db("""
        SELECT COUNT(DISTINCT activo_id) AS n
        FROM scoring_resultados
        WHERE prioridad = %(p)s
          AND horizonte_dias = %(h)s
          AND fecha_scoring = (
              SELECT MAX(fecha_scoring) FROM scoring_resultados
              WHERE horizonte_dias = %(h)s
          );
    """, params={"p": prioridad, "h": horizonte_dias})
    if df.empty:
        return 0
    return int(df.iloc[0]["n"])


@st.cache_data(ttl=300)
def fetch_fallas_anticipadas_30d() -> int:
    """Cuenta de alertas P1/P2 confirmadas como falla real en últimos 30 días.

    Requiere feedback_alertas. Si no existe, retorna 0.
    """
    if not check_table_exists("feedback_alertas"):
        return 0
    df = query_db("""
        SELECT COUNT(*) AS n
        FROM feedback_alertas
        WHERE falla_real = TRUE
          AND fecha_feedback >= CURRENT_DATE - INTERVAL '30 days';
    """)
    if df.empty:
        return 0
    return int(df.iloc[0]["n"])


@st.cache_data(ttl=300)
def fetch_mtbf_horas() -> Optional[float]:
    """MTBF de flota en horas.

    Si hay tabla disponibilidad_diaria → cálculo correcto (horas operativas / N fallas)
    Si no → None (el visual maneja el caso)
    """
    if check_table_exists("disponibilidad_diaria"):
        df = query_db("""
            WITH horas AS (
                SELECT SUM(COALESCE(horas_operativas, 0)) AS h_op
                FROM disponibilidad_diaria
                WHERE fecha >= CURRENT_DATE - INTERVAL '90 days'
            ),
            fallas AS (
                SELECT COUNT(*)::numeric AS n
                FROM ordenes_trabajo
                WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')
                  AND fecha_apertura >= CURRENT_DATE - INTERVAL '90 days'
            )
            SELECT
                CASE WHEN fallas.n > 0 THEN horas.h_op / fallas.n ELSE NULL END AS mtbf
            FROM horas, fallas;
        """)
        if not df.empty and df.iloc[0]["mtbf"] is not None:
            return float(df.iloc[0]["mtbf"])
    return None

# ============================================================================
# TENDENCIAS DE HERO METRICS
# ----------------------------------------------------------------------------
# Cada función compara el período actual contra el período anterior equivalente.
# Devuelven None cuando no hay base de datos suficiente — en ese caso st.metric
# omite el delta automáticamente (no se inventa nada).
# ============================================================================

@st.cache_data(ttl=300)
def fetch_unidades_operativas_tendencia() -> Optional[float]:
    """Variación % de unidades operativas vs hace 30 días.

    Requiere que activos tenga alguna columna de fecha de alta/creación.
    Si no existe, devuelve None (no se inventa tendencia).
    """
    # Probar columnas candidatas en orden de probabilidad
    for col in ("fecha_alta", "fecha_ingreso", "created_at", "fecha_creacion"):
        if check_column_exists("activos", col):
            df = query_db(f"""
                WITH actual AS (
                    SELECT COUNT(*)::numeric AS n
                    FROM activos
                    WHERE COALESCE(LOWER(estado_actual), 'operativo')
                          NOT IN ('baja', 'fuera_servicio', 'inactivo')
                ),
                previo AS (
                    SELECT COUNT(*)::numeric AS n
                    FROM activos
                    WHERE {col} <= CURRENT_DATE - INTERVAL '30 days'
                      AND COALESCE(LOWER(estado_actual), 'operativo')
                          NOT IN ('baja', 'fuera_servicio', 'inactivo')
                )
                SELECT actual.n AS act, previo.n AS prev FROM actual, previo;
            """)
            if not df.empty and df.iloc[0]["prev"] and float(df.iloc[0]["prev"]) > 0:
                act = float(df.iloc[0]["act"])
                prev = float(df.iloc[0]["prev"])
                return (act - prev) / prev * 100.0
            return None
    return None


@st.cache_data(ttl=300)
def fetch_disponibilidad_30d_tendencia() -> Optional[float]:
    """Variación de disponibilidad: últimos 30 días vs 30 días previos.

    Devuelve diferencia en puntos porcentuales (pp).
    Requiere ≥60 días de historia en disponibilidad_diaria.
    """
    if not check_table_exists("disponibilidad_diaria"):
        return None
    df = query_db("""
        WITH actual AS (
            SELECT
                SUM(COALESCE(horas_operativas, 0)) AS op,
                SUM(COALESCE(horas_operativas, 0) +
                    COALESCE(horas_detenido_planificado, 0) +
                    COALESCE(horas_detenido_no_planificado, 0)) AS tot
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '30 days'
        ),
        previo AS (
            SELECT
                SUM(COALESCE(horas_operativas, 0)) AS op,
                SUM(COALESCE(horas_operativas, 0) +
                    COALESCE(horas_detenido_planificado, 0) +
                    COALESCE(horas_detenido_no_planificado, 0)) AS tot
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '60 days'
              AND fecha <  CURRENT_DATE - INTERVAL '30 days'
        )
        SELECT
            CASE WHEN actual.tot > 0 THEN actual.op / actual.tot * 100 ELSE NULL END AS act,
            CASE WHEN previo.tot > 0 THEN previo.op / previo.tot * 100 ELSE NULL END AS prev
        FROM actual, previo;
    """)
    if df.empty:
        return None
    act = df.iloc[0]["act"]
    prev = df.iloc[0]["prev"]
    if act is None or prev is None:
        return None
    return float(act) - float(prev)  # diferencia en pp


@st.cache_data(ttl=300)
def fetch_conteo_prioridad_tendencia(prioridad: str, horizonte_dias: int = 30) -> Optional[float]:
    """Variación % del conteo de una prioridad vs el scoring inmediatamente anterior.

    Compara última fecha_scoring con la penúltima.
    Si solo hay un scoring registrado → None.
    """
    df = query_db("""
        WITH fechas AS (
            SELECT DISTINCT fecha_scoring
            FROM scoring_resultados
            WHERE horizonte_dias = %(h)s
            ORDER BY fecha_scoring DESC
            LIMIT 2
        ),
        ranked AS (
            SELECT fecha_scoring,
                   ROW_NUMBER() OVER (ORDER BY fecha_scoring DESC) AS rn
            FROM fechas
        ),
        actual AS (
            SELECT COUNT(DISTINCT activo_id)::numeric AS n
            FROM scoring_resultados
            WHERE prioridad = %(p)s
              AND horizonte_dias = %(h)s
              AND fecha_scoring = (SELECT fecha_scoring FROM ranked WHERE rn = 1)
        ),
        previo AS (
            SELECT COUNT(DISTINCT activo_id)::numeric AS n
            FROM scoring_resultados
            WHERE prioridad = %(p)s
              AND horizonte_dias = %(h)s
              AND fecha_scoring = (SELECT fecha_scoring FROM ranked WHERE rn = 2)
        )
        SELECT actual.n AS act, previo.n AS prev,
               (SELECT COUNT(*) FROM ranked) AS n_fechas
        FROM actual, previo;
    """, params={"p": prioridad, "h": horizonte_dias})
    if df.empty or int(df.iloc[0]["n_fechas"] or 0) < 2:
        return None
    act = float(df.iloc[0]["act"] or 0)
    prev = float(df.iloc[0]["prev"] or 0)
    if prev == 0:
        # Si antes había 0 y ahora hay algo, devolver None evita un +∞ engañoso.
        # Si querés mostrarlo igual: return 100.0 si act > 0 else 0.0
        return None
    return (act - prev) / prev * 100.0


@st.cache_data(ttl=300)
def fetch_fallas_anticipadas_30d_tendencia() -> Optional[float]:
    """Variación % de fallas anticipadas: últimos 30d vs 30d previos."""
    if not check_table_exists("feedback_alertas"):
        return None
    df = query_db("""
        WITH actual AS (
            SELECT COUNT(*)::numeric AS n
            FROM feedback_alertas
            WHERE falla_real = TRUE
              AND fecha_feedback >= CURRENT_DATE - INTERVAL '30 days'
        ),
        previo AS (
            SELECT COUNT(*)::numeric AS n
            FROM feedback_alertas
            WHERE falla_real = TRUE
              AND fecha_feedback >= CURRENT_DATE - INTERVAL '60 days'
              AND fecha_feedback <  CURRENT_DATE - INTERVAL '30 days'
        )
        SELECT actual.n AS act, previo.n AS prev FROM actual, previo;
    """)
    if df.empty:
        return None
    act = float(df.iloc[0]["act"] or 0)
    prev = float(df.iloc[0]["prev"] or 0)
    if prev == 0:
        return None
    return (act - prev) / prev * 100.0


@st.cache_data(ttl=300)
def fetch_mtbf_horas_tendencia() -> Optional[float]:
    """Variación % de MTBF: ventana 90d actual vs ventana 90d previa (días 91–180).

    Requiere disponibilidad_diaria con al menos 180 días de historia.
    """
    if not check_table_exists("disponibilidad_diaria"):
        return None
    df = query_db("""
        WITH horas_act AS (
            SELECT SUM(COALESCE(horas_operativas, 0)) AS h
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '90 days'
        ),
        fallas_act AS (
            SELECT COUNT(*)::numeric AS n
            FROM ordenes_trabajo
            WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')
              AND fecha_apertura >= CURRENT_DATE - INTERVAL '90 days'
        ),
        horas_prev AS (
            SELECT SUM(COALESCE(horas_operativas, 0)) AS h
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '180 days'
              AND fecha <  CURRENT_DATE - INTERVAL '90 days'
        ),
        fallas_prev AS (
            SELECT COUNT(*)::numeric AS n
            FROM ordenes_trabajo
            WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')
              AND fecha_apertura >= CURRENT_DATE - INTERVAL '180 days'
              AND fecha_apertura <  CURRENT_DATE - INTERVAL '90 days'
        )
        SELECT
            CASE WHEN fallas_act.n  > 0 THEN horas_act.h  / fallas_act.n  ELSE NULL END AS act,
            CASE WHEN fallas_prev.n > 0 THEN horas_prev.h / fallas_prev.n ELSE NULL END AS prev
        FROM horas_act, fallas_act, horas_prev, fallas_prev;
    """)
    if df.empty:
        return None
    act = df.iloc[0]["act"]
    prev = df.iloc[0]["prev"]
    if act is None or prev is None or float(prev) == 0:
        return None
    return (float(act) - float(prev)) / float(prev) * 100.0

@st.cache_data(ttl=300)
def fetch_ranking_riesgo(horizonte_dias: int = 30, top_n: int = 15) -> pd.DataFrame:
    """Top N unidades con mayor probabilidad de falla en horizonte dado.

    Une scoring_resultados (último scoring por activo) con activos.
    Trae también la última OT por activo y opcionalmente el sistema más reciente.
    """
    # Detectar si ordenes_trabajo tiene columna 'sistema'
    tiene_sistema = check_column_exists("ordenes_trabajo", "sistema")
    sistema_select = "(SELECT o.sistema FROM ordenes_trabajo o WHERE o.activo_id = a.activo_id ORDER BY o.fecha_apertura DESC LIMIT 1)" if tiene_sistema else "NULL"

    q = f"""
        WITH ultimo_scoring AS (
            SELECT DISTINCT ON (activo_id)
                activo_id, fecha_scoring, probabilidad_falla, prediccion,
                prioridad, modelo_version, horizonte_dias
            FROM scoring_resultados
            WHERE horizonte_dias = %(h)s
            ORDER BY activo_id, fecha_scoring DESC
        ),
        ultima_ot AS (
            SELECT DISTINCT ON (activo_id)
                activo_id, fecha_apertura, COALESCE(odometro_km, NULL) AS odometro_ot
            FROM ordenes_trabajo
            ORDER BY activo_id, fecha_apertura DESC
        )
        SELECT
            a.activo_id,
            a.patente,
            a.marca,
            a.modelo,
            us.prioridad,
            us.probabilidad_falla,
            us.fecha_scoring,
            COALESCE(uo.fecha_apertura::date::text, 'Sin OT') AS ultima_ot,
            COALESCE(a.odometro_km, uo.odometro_ot, 0) AS km_actual,
            {sistema_select} AS sistema_riesgo,
            CASE
                WHEN uo.fecha_apertura IS NOT NULL
                THEN (CURRENT_DATE - uo.fecha_apertura::date)
                ELSE NULL
            END AS dias_ultima_ot
        FROM activos a
        INNER JOIN ultimo_scoring us ON us.activo_id = a.activo_id
        LEFT JOIN ultima_ot uo ON uo.activo_id = a.activo_id
        ORDER BY us.probabilidad_falla DESC NULLS LAST
        LIMIT %(n)s;
    """
    df = query_db(q, params={"h": horizonte_dias, "n": top_n})
    return df


@st.cache_data(ttl=300)
def fetch_distribucion_prioridad_por_tipo(horizonte_dias: int = 30) -> pd.DataFrame:
    """Distribución P1-P4 por tipo de vehículo según último scoring."""
    df = query_db("""
        WITH ultimo_scoring AS (
            SELECT DISTINCT ON (activo_id)
                activo_id, prioridad
            FROM scoring_resultados
            WHERE horizonte_dias = %(h)s
            ORDER BY activo_id, fecha_scoring DESC
        )
        SELECT
            COALESCE(a.tipo_vehiculo, 'Sin clasificar') AS tipo,
            us.prioridad,
            COUNT(*) AS n
        FROM activos a
        LEFT JOIN ultimo_scoring us ON us.activo_id = a.activo_id
        GROUP BY a.tipo_vehiculo, us.prioridad
        ORDER BY tipo;
    """, params={"h": horizonte_dias})
    return df


@st.cache_data(ttl=300)
def fetch_evolucion_alertas_30d() -> pd.DataFrame:
    """Conteo diario de alertas P1+P2 en últimos 30 días."""
    df = query_db("""
        SELECT
            fecha_scoring::date AS fecha,
            COUNT(*) FILTER (WHERE prioridad IN ('P1_critica', 'P2_alta')) AS alertas_altas
        FROM scoring_resultados
        WHERE fecha_scoring >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY fecha_scoring
        ORDER BY fecha_scoring;
    """)
    return df


@st.cache_data(ttl=300)
def fetch_riesgo_promedio_por_marca() -> pd.DataFrame:
    """Probabilidad promedio de falla por marca (último scoring por activo)."""
    df = query_db("""
        WITH ultimo_scoring AS (
            SELECT DISTINCT ON (activo_id)
                activo_id, probabilidad_falla
            FROM scoring_resultados
            ORDER BY activo_id, fecha_scoring DESC
        )
        SELECT
            a.marca,
            AVG(us.probabilidad_falla)::numeric(5,3) AS prob_promedio
        FROM activos a
        INNER JOIN ultimo_scoring us ON us.activo_id = a.activo_id
        WHERE a.marca IS NOT NULL
        GROUP BY a.marca
        ORDER BY prob_promedio DESC
        LIMIT 5;
    """)
    return df


@st.cache_data(ttl=300)
def fetch_mapa_calor_sistemas() -> pd.DataFrame:
    """Mapa de calor de fallas históricas por sistema y horizonte.

    En v1 del modelo (binario) no hay riesgo predictivo por sistema. Lo que SÍ
    se puede mostrar es la distribución descriptiva de fallas históricas por
    sistema, agrupadas en ventanas que aproximan los horizontes.

    Requiere columna 'sistema' en ordenes_trabajo. Si no existe, retorna vacío.
    """
    if not check_column_exists("ordenes_trabajo", "sistema"):
        return pd.DataFrame()

    df = query_db("""
        WITH ventanas AS (
            SELECT
                COALESCE(NULLIF(LOWER(sistema), ''), 'sin_clasificar') AS sistema,
                CASE
                    WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '7 days' THEN '7 días'
                    WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '30 days' THEN '30 días'
                    WHEN fecha_apertura >= CURRENT_DATE - INTERVAL '90 days' THEN '90 días'
                    ELSE NULL
                END AS horizonte
            FROM ordenes_trabajo
            WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')
        )
        SELECT sistema, horizonte, COUNT(*) AS n
        FROM ventanas
        WHERE horizonte IS NOT NULL
        GROUP BY sistema, horizonte;
    """)
    return df


@st.cache_data(ttl=300)
def fetch_intervenciones_recomendadas(horizonte_dias: int = 30) -> pd.DataFrame:
    """Lista de intervenciones sugeridas para próximos N días.

    Toma activos con P1/P2 en último scoring del horizonte dado.
    """
    tiene_sistema = check_column_exists("ordenes_trabajo", "sistema")
    sistema_select = "COALESCE((SELECT o.sistema FROM ordenes_trabajo o WHERE o.activo_id = a.activo_id ORDER BY o.fecha_apertura DESC LIMIT 1), 'Sin clasificar')" if tiene_sistema else "'Sin clasificar'"

    q = f"""
        WITH ultimo_scoring AS (
            SELECT DISTINCT ON (activo_id)
                activo_id, prioridad, probabilidad_falla
            FROM scoring_resultados
            WHERE horizonte_dias = %(h)s
            ORDER BY activo_id, fecha_scoring DESC
        )
        SELECT
            a.patente,
            CASE
                WHEN us.prioridad = 'P1_critica' THEN 'Correctivo programado'
                WHEN us.prioridad = 'P2_alta'    THEN 'Preventivo anticipado'
                ELSE 'Inspección'
            END AS tipo,
            {sistema_select} AS sistema,
            us.prioridad AS urgencia,
            us.probabilidad_falla
        FROM activos a
        INNER JOIN ultimo_scoring us ON us.activo_id = a.activo_id
        WHERE us.prioridad IN ('P1_critica', 'P2_alta')
        ORDER BY us.probabilidad_falla DESC;
    """
    return query_db(q, params={"h": horizonte_dias})


@st.cache_data(ttl=300)
def fetch_costo_promedio_por_sistema() -> pd.DataFrame:
    """Costo promedio de OT correctiva por sistema.

    Maneja la inconsistencia: el costo puede estar en 'costo' o 'costo_total_clp'.
    """
    tiene_sistema = check_column_exists("ordenes_trabajo", "sistema")
    if not tiene_sistema:
        return pd.DataFrame()

    col_costo = "costo_total_clp" if check_column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    if not check_column_exists("ordenes_trabajo", col_costo):
        return pd.DataFrame()

    q = f"""
        SELECT
            COALESCE(NULLIF(LOWER(sistema), ''), 'sin_clasificar') AS sistema,
            AVG(COALESCE({col_costo}, 0))::numeric(12,0) AS costo_promedio
        FROM ordenes_trabajo
        WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')
        GROUP BY sistema;
    """
    return query_db(q)


@st.cache_data(ttl=300)
def fetch_repuestos_estado() -> pd.DataFrame:
    """Estado de repuestos: maestro + consumo histórico.

    Si existe repuestos_maestro, retorna SKUs con stock y cobertura.
    Si no, retorna desde repuestos_consumidos (modo reducido sin stock).
    """
    if check_table_exists("repuestos_maestro"):
        return query_db("""
            SELECT
                sku,
                descripcion,
                stock_actual,
                lead_time_dias_promedio AS lead_time,
                criticidad,
                stock_actual::numeric / NULLIF(
                    GREATEST(1,
                        (SELECT COALESCE(SUM(cantidad), 0)
                         FROM repuestos_consumidos rc
                         JOIN ordenes_trabajo o ON o.ot_id = rc.ot_id
                         WHERE rc.sku = rm.sku
                           AND o.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days'
                        )
                    ), 0) * 30.0 AS cobertura_dias
            FROM repuestos_maestro rm;
        """)

    # Modo reducido — solo lo que se ha consumido
    return query_db("""
        SELECT
            sku,
            descripcion_repuesto AS descripcion,
            NULL::numeric AS stock_actual,
            NULL::numeric AS lead_time,
            'Sin clasificar'::text AS criticidad,
            NULL::numeric AS cobertura_dias,
            SUM(cantidad) AS cantidad_consumida_total,
            SUM(COALESCE(costo_unitario_clp, 0) * cantidad) AS costo_total_consumido
        FROM repuestos_consumidos
        WHERE sku IS NOT NULL
        GROUP BY sku, descripcion_repuesto
        ORDER BY costo_total_consumido DESC NULLS LAST;
    """)


@st.cache_data(ttl=300)
def fetch_pm_vencidos() -> pd.DataFrame:
    """PM vencidos: requiere un plan de PM. Por ahora se aproxima como
    activos sin OT preventiva en los últimos 90 días.
    """
    df = query_db("""
        WITH ultima_pm AS (
            SELECT activo_id, MAX(fecha_apertura) AS ultima_pm_fecha
            FROM ordenes_trabajo
            WHERE LOWER(COALESCE(tipo_ot, '')) IN ('preventiva', 'preventivo')
            GROUP BY activo_id
        )
        SELECT
            a.patente,
            COALESCE((CURRENT_DATE - up.ultima_pm_fecha::date)::text || ' días', 'Nunca') AS pm_vencida,
            COALESCE((
                SELECT o.sistema
                FROM ordenes_trabajo o
                WHERE o.activo_id = a.activo_id AND o.sistema IS NOT NULL
                ORDER BY o.fecha_apertura DESC LIMIT 1
            ), 'Sin clasificar') AS proximo_sistema
        FROM activos a
        LEFT JOIN ultima_pm up ON up.activo_id = a.activo_id
        WHERE up.ultima_pm_fecha IS NULL
           OR (CURRENT_DATE - up.ultima_pm_fecha::date) > 90
        ORDER BY up.ultima_pm_fecha NULLS FIRST
        LIMIT 10;
    """)
    # Si la columna sistema no existe, la query igual funciona porque devolverá 'Sin clasificar'
    return df


@st.cache_data(ttl=300)
def fetch_cumplimiento_pm() -> Optional[float]:
    """% de OT preventivas cerradas en los últimos 90 días sobre las abiertas."""
    df = query_db("""
        SELECT
            COUNT(*) FILTER (WHERE fecha_cierre IS NOT NULL)::numeric AS cerradas,
            COUNT(*)::numeric AS total
        FROM ordenes_trabajo
        WHERE LOWER(COALESCE(tipo_ot, '')) IN ('preventiva', 'preventivo')
          AND fecha_apertura >= CURRENT_DATE - INTERVAL '90 days';
    """)
    if df.empty or float(df.iloc[0]["total"] or 0) == 0:
        return None
    return float(df.iloc[0]["cerradas"]) / float(df.iloc[0]["total"]) * 100.0


@st.cache_data(ttl=300)
def fetch_backlog_ot() -> int:
    """OT abiertas (sin fecha_cierre)."""
    df = query_db("SELECT COUNT(*) AS n FROM ordenes_trabajo WHERE fecha_cierre IS NULL;")
    if df.empty:
        return 0
    return int(df.iloc[0]["n"])


@st.cache_data(ttl=300)
def fetch_intervenciones_proximas(dias: int) -> int:
    """Cuenta de unidades con P1/P2 en último scoring del horizonte dado."""
    p1 = fetch_conteo_prioridad("P1_critica", horizonte_dias=dias)
    p2 = fetch_conteo_prioridad("P2_alta", horizonte_dias=dias)
    return p1 + p2


@st.cache_data(ttl=300)
def fetch_costo_evitado_acumulado() -> Optional[float]:
    """Costo evitado = Σ (alertas confirmadas × costo promedio correctivo del sistema).

    Requiere feedback_alertas. Sin esto retorna None.
    """
    if not check_table_exists("feedback_alertas"):
        return None
    df = query_db("""
        SELECT COALESCE(SUM(costo_reparacion), 0) AS total
        FROM feedback_alertas
        WHERE falla_real = TRUE;
    """)
    if df.empty:
        return None
    return float(df.iloc[0]["total"] or 0)


@st.cache_data(ttl=300)
def fetch_downtime_evitado_horas() -> Optional[float]:
    """Horas de detención evitadas: Σ horas_detencion en alertas confirmadas."""
    if not check_table_exists("feedback_alertas"):
        return None
    df = query_db("""
        SELECT COALESCE(SUM(horas_detencion), 0) AS total
        FROM feedback_alertas
        WHERE falla_real = TRUE;
    """)
    if df.empty:
        return None
    return float(df.iloc[0]["total"] or 0)


@st.cache_data(ttl=300)
def fetch_costo_mantenimiento_por_km_unidad() -> Tuple[Optional[float], Optional[float]]:
    """Retorna (costo/km, costo/unidad) último mes."""
    col_costo = "costo_total_clp" if check_column_exists("ordenes_trabajo", "costo_total_clp") else "costo"
    if not check_column_exists("ordenes_trabajo", col_costo):
        return (None, None)

    q_total = f"""
        SELECT COALESCE(SUM({col_costo}), 0) AS costo_total
        FROM ordenes_trabajo
        WHERE fecha_apertura >= CURRENT_DATE - INTERVAL '30 days';
    """
    df = query_db(q_total)
    if df.empty:
        return (None, None)
    costo_total = float(df.iloc[0]["costo_total"] or 0)

    # km totales aproximados de las OT del periodo
    df_km = query_db("""
        SELECT COALESCE(SUM(odometro_km), 0) AS km
        FROM (
            SELECT DISTINCT ON (activo_id) activo_id, odometro_km
            FROM ordenes_trabajo
            WHERE fecha_apertura >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY activo_id, fecha_apertura DESC
        ) t;
    """) if check_column_exists("ordenes_trabajo", "odometro_km") else pd.DataFrame()

    km = float(df_km.iloc[0]["km"]) if not df_km.empty else 0.0

    # Unidades operativas
    n_unidades = fetch_unidades_operativas() or fetch_unidades_total()

    costo_km = (costo_total / km) if km > 0 else None
    costo_unidad = (costo_total / n_unidades) if n_unidades > 0 else None
    return (costo_km, costo_unidad)


@st.cache_data(ttl=300)
def fetch_mtbf_mttr_12m() -> pd.DataFrame:
    """Serie mensual de MTBF y MTTR de los últimos 12 meses."""
    df = query_db("""
        WITH meses AS (
            SELECT DATE_TRUNC('month', fecha_apertura)::date AS mes,
                   fecha_apertura, fecha_cierre, tipo_ot
            FROM ordenes_trabajo
            WHERE fecha_apertura >= CURRENT_DATE - INTERVAL '12 months'
        )
        SELECT
            mes,
            -- MTTR aproximado: media de duración de OT cerradas (horas)
            AVG(
                CASE
                    WHEN fecha_cierre IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura)) / 3600.0
                    ELSE NULL
                END
            )::numeric(10,2) AS mttr_h,
            -- MTBF aproximado: 720 horas/mes / N correctivas (cuando hay)
            CASE
                WHEN COUNT(*) FILTER (WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')) > 0
                THEN (720.0 / COUNT(*) FILTER (WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')))::numeric(10,2)
                ELSE NULL
            END AS mtbf_h
        FROM meses
        GROUP BY mes
        ORDER BY mes;
    """)
    return df


@st.cache_data(ttl=300)
def fetch_downtime_mensual() -> pd.DataFrame:
    """Downtime planificado vs no planificado mensual (12m).

    Aproximación: usa duración de OT preventivas (planificado) y correctivas
    (no planificado). Requiere fecha_cierre.
    """
    df = query_db("""
        SELECT
            DATE_TRUNC('month', fecha_apertura)::date AS mes,
            SUM(
                CASE
                    WHEN LOWER(COALESCE(tipo_ot, '')) IN ('preventiva', 'preventivo')
                     AND fecha_cierre IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura)) / 3600.0
                    ELSE 0
                END
            )::numeric(10,2) AS planificado_h,
            SUM(
                CASE
                    WHEN LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo')
                     AND fecha_cierre IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura)) / 3600.0
                    ELSE 0
                END
            )::numeric(10,2) AS no_planificado_h
        FROM ordenes_trabajo
        WHERE fecha_apertura >= CURRENT_DATE - INTERVAL '12 months'
        GROUP BY mes
        ORDER BY mes;
    """)
    return df


@st.cache_data(ttl=300)
def fetch_feedback_estados() -> pd.DataFrame:
    """Distribución de alertas por estado de feedback."""
    if not check_table_exists("feedback_alertas"):
        return pd.DataFrame()
    return query_db("""
        SELECT
            estado,
            COUNT(*) AS cantidad
        FROM feedback_alertas
        GROUP BY estado;
    """)


@st.cache_data(ttl=300)
def fetch_motivos_rechazo() -> pd.DataFrame:
    """Top motivos por los que el taller descarta alertas."""
    if not check_table_exists("feedback_alertas"):
        return pd.DataFrame()
    return query_db("""
        SELECT
            COALESCE(NULLIF(notas, ''), 'Sin especificar') AS motivo,
            COUNT(*) AS cantidad
        FROM feedback_alertas
        WHERE estado IN ('descartada', 'rechazada')
        GROUP BY motivo
        ORDER BY cantidad DESC
        LIMIT 5;
    """)


@st.cache_data(ttl=300)
def fetch_modelo_metricas() -> dict:
    """Trae métricas del modelo activo desde modelos_registro."""
    df = query_db("""
        SELECT version, recall, precision, f1_score, auc_score, fecha_entrenamiento
        FROM modelos_registro
        WHERE es_activo = TRUE
        LIMIT 1;
    """)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


@st.cache_data(ttl=300)
def fetch_tiempo_uso_meses() -> int:
    """Meses desde primer scoring registrado.

    Esta es la métrica que activa/desactiva los candados (mes 6).
    """
    df = query_db("SELECT MIN(fecha_scoring) AS primera FROM scoring_resultados;")
    if df.empty or df.iloc[0]["primera"] is None:
        return 0
    primera = pd.to_datetime(df.iloc[0]["primera"])
    delta_dias = (datetime.now() - primera).days
    return max(0, delta_dias // 30)


@st.cache_data(ttl=300)
def fetch_filtros_disponibles() -> dict:
    """Trae valores únicos para los filtros del sidebar."""
    df_tipo = query_db("SELECT DISTINCT tipo_vehiculo FROM activos WHERE tipo_vehiculo IS NOT NULL ORDER BY tipo_vehiculo;")
    df_marca = query_db("SELECT DISTINCT marca FROM activos WHERE marca IS NOT NULL ORDER BY marca;")
    return {
        "tipos": df_tipo["tipo_vehiculo"].tolist() if not df_tipo.empty else [],
        "marcas": df_marca["marca"].tolist() if not df_marca.empty else [],
    }


# ============================================================================
# HELPERS DE PRESENTACIÓN
# ============================================================================

def empty_state(message: str, height: int = 80):
    """Renderiza un bloque visual de estado vacío sin romper layout."""
    st.markdown(
        f"<div class='empty-state' style='min-height:{height}px; display:flex; "
        f"align-items:center; justify-content:center;'>{message}</div>",
        unsafe_allow_html=True
    )


def fmt_clp(valor: Optional[float]) -> str:
    if valor is None:
        return "Sin datos"
    try:
        return f"${valor:,.0f}".replace(",", ".")
    except Exception:
        return "Sin datos"


def fmt_pct(valor: Optional[float], decimales: int = 1) -> str:
    if valor is None:
        return "Sin datos"
    try:
        return f"{valor:.{decimales}f}%"
    except Exception:
        return "Sin datos"


def fmt_num(valor: Optional[float], decimales: int = 0) -> str:
    if valor is None:
        return "Sin datos"
    try:
        if decimales == 0:
            return f"{int(valor):,}".replace(",", ".")
        return f"{valor:,.{decimales}f}".replace(",", ".")
    except Exception:
        return "Sin datos"


def parse_horizonte(label: str) -> int:
    """Convierte '7 días'/'30 días'/'90 días' a entero."""
    return int(label.split()[0])


# ============================================================================
# VISTA 1 — ESTADO DE FLOTA Y RIESGO PREDICTIVO
# ============================================================================

def vista_1_estado_riesgo():
    """Vista 1: Estado actual de flota y ranking de riesgo predictivo"""
    st.markdown("### 📊 Estado de Flota y Riesgo Predictivo")

    # Filtros globales — alimentados desde Supabase
    filtros = fetch_filtros_disponibles()
    with st.sidebar:
        st.markdown("---")
        st.markdown("**Filtros globales**")
        st.date_input("Desde", datetime.now() - timedelta(days=30))
        st.date_input("Hasta", datetime.now())
        horizonte_label = st.selectbox("Horizonte predictivo", ["7 días", "30 días", "90 días"], index=1)
        st.multiselect("Tipo de vehículo", filtros["tipos"])
        st.multiselect("Marca", filtros["marcas"])

    horizonte_dias = parse_horizonte(horizonte_label)

    # BANDA SUPERIOR — Hero metrics (todos desde Supabase)
    st.markdown("#### 🎯 Indicadores principales")

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        n_op = fetch_unidades_operativas()
        delta_op = fetch_unidades_operativas_tendencia()  # Nueva función
        delta_str = f"{delta_op:.1f}%" if delta_op is not None else None
        st.metric("Unidades operativas", fmt_num(n_op), delta=delta_str)

    with col2:
        disp = fetch_disponibilidad_30d()
        delta_disp = fetch_disponibilidad_30d_tendencia()  # Nueva función
        delta_str = f"{delta_disp:.1f}pp" if delta_disp is not None else None
        st.metric("Disponibilidad", 
                  fmt_pct(disp) if disp is not None else "Sin datos",
                  delta=delta_str)
        if disp is None:
            st.caption("Requiere disponibilidad_diaria")

    with col3:
        n_p1 = fetch_conteo_prioridad("P1_critica", horizonte_dias=horizonte_dias)
        delta_p1 = fetch_conteo_prioridad_tendencia("P1_critica", horizonte_dias=horizonte_dias)
        delta_str = f"{delta_p1:.0f}%" if delta_p1 is not None else None
        st.metric("P1 crítica", fmt_num(n_p1), delta=delta_str)

    with col4:
        n_p2 = fetch_conteo_prioridad("P2_alta", horizonte_dias=horizonte_dias)
        delta_p2 = fetch_conteo_prioridad_tendencia("P2_alta", horizonte_dias=horizonte_dias)
        delta_str = f"{delta_p2:.0f}%" if delta_p2 is not None else None
        st.metric("P2 alta", fmt_num(n_p2), delta=delta_str)

    with col5:
        n_anticipadas = fetch_fallas_anticipadas_30d()
        delta_ant = fetch_fallas_anticipadas_30d_tendencia()
        delta_str = f"{delta_ant:.0f}%" if delta_ant is not None else None
        st.metric("Fallas anticipadas*", fmt_num(n_anticipadas), delta=delta_str)
        st.caption("*últimos 30 días, confirmadas")

    with col6:
        mtbf = fetch_mtbf_horas()
        delta_mtbf = fetch_mtbf_horas_tendencia()
        delta_str = f"{delta_mtbf:.0f}%" if delta_mtbf is not None else None
        st.metric("MTBF (horas)", fmt_num(mtbf, 0) if mtbf is not None else "Sin datos", delta=delta_str)
        if mtbf is None:
            st.caption("Requiere disponibilidad_diaria")

    st.markdown("---")
    # Ranking de unidades en riesgo — DATOS REALES
    st.markdown(f"#### ⚠️ Ranking de unidades en riesgo (Top 15, horizonte {horizonte_label})")

    ranking_df = fetch_ranking_riesgo(horizonte_dias=horizonte_dias, top_n=15)

    if ranking_df.empty:
        empty_state(
            "Sin scoring disponible para el horizonte seleccionado. "
            "Ejecute el pipeline de scoring_diario.py para poblar la tabla scoring_resultados.",
            height=100
        )
    else:
        # Mapeo de prioridad a semáforo visual
        prioridad_a_emoji = {
            "P1_critica": "🔴 P1 Crítica",
            "P2_alta": "🟠 P2 Alta",
            "P3_media": "🟡 P3 Media",
            "P4_baja": "🟢 P4 Baja",
        }
        ranking_df["Semáforo"] = ranking_df["prioridad"].map(prioridad_a_emoji).fillna(ranking_df["prioridad"])
        ranking_df[f"Prob {horizonte_label.replace(' ', '')}"] = (
            ranking_df["probabilidad_falla"].astype(float) * 100
        ).round(1).astype(str) + "%"

        display = ranking_df[[
            "patente", "marca", "modelo", "Semáforo",
            f"Prob {horizonte_label.replace(' ', '')}",
            "fecha_scoring", "sistema_riesgo", "dias_ultima_ot", "km_actual"
        ]].rename(columns={
            "patente": "Patente",
            "marca": "Marca",
            "modelo": "Modelo",
            "fecha_scoring": "Fecha scoring",
            "sistema_riesgo": "Sistema en riesgo",
            "dias_ultima_ot": "Días últim. OT",
            "km_actual": "Km actual",
        })

        st.dataframe(display, use_container_width=True, hide_index=True)
        st.markdown("*Haz clic en una fila para ver factores de riesgo*")

    # Bloques inferiores
    col_mapa, col_dist = st.columns(2)

    with col_mapa:
        st.markdown("#### 🗺️ Mapa de calor: Riesgo por sistema")
        df_calor = fetch_mapa_calor_sistemas()

        if df_calor.empty:
            empty_state(
                "Requiere columna 'sistema' en ordenes_trabajo. "
                "Sin esto no se puede agrupar fallas por sistema.",
                height=380
            )
        else:
            pivot = df_calor.pivot_table(index="sistema", columns="horizonte", values="n", fill_value=0)
            # Ordenar columnas por horizonte
            orden_cols = [c for c in ["7 días", "30 días", "90 días"] if c in pivot.columns]
            pivot = pivot[orden_cols]

            fig_heatmap = go.Figure(data=go.Heatmap(
                z=pivot.values,
                x=pivot.columns.tolist(),
                y=pivot.index.tolist(),
                colorscale='RdYlGn_r',
                text=pivot.values.round(0),
                texttemplate='%{text}',
                textfont={"size": 11}
            ))
            fig_heatmap.update_layout(height=400, margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_heatmap, use_container_width=True)
            st.caption("v1: muestra distribución descriptiva de fallas históricas (no riesgo predictivo por sistema)")

    with col_dist:
        st.markdown("#### 📊 Distribución P1–P4 por tipo de vehículo")
        df_dist = fetch_distribucion_prioridad_por_tipo(horizonte_dias=horizonte_dias)

        if df_dist.empty or df_dist["prioridad"].isna().all():
            empty_state(
                "Sin scoring disponible para mostrar distribución por tipo.",
                height=380
            )
        else:
            # Normalizar nombres de prioridad
            prio_map = {
                "P1_critica": "P1", "P2_alta": "P2",
                "P3_media": "P3", "P4_baja": "P4"
            }
            df_dist["prio_corta"] = df_dist["prioridad"].map(prio_map).fillna("P4")
            pivot_d = df_dist.pivot_table(index="tipo", columns="prio_corta", values="n", fill_value=0).reset_index()

            # Asegurar que existan todas las columnas P1-P4
            for col in ["P1", "P2", "P3", "P4"]:
                if col not in pivot_d.columns:
                    pivot_d[col] = 0

            fig_dist = px.bar(
                pivot_d, x="tipo", y=["P1", "P2", "P3", "P4"],
                barmode='stack',
                color_discrete_map={
                    'P1': '#d32f2f', 'P2': '#f57c00',
                    'P3': '#fbc02d', 'P4': '#388e3c'
                }
            )
            fig_dist.update_layout(
                height=400, margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
            )
            st.plotly_chart(fig_dist, use_container_width=True)

    col_evol, col_top5 = st.columns(2)

    with col_evol:
        st.markdown("#### 📈 Evolución alertas P1/P2 (últimos 30 días)")
        df_evol = fetch_evolucion_alertas_30d()

        if df_evol.empty:
            empty_state("Sin scoring histórico suficiente para construir la serie de 30 días.", height=280)
        else:
            fig_evol = px.line(
                df_evol, x="fecha", y="alertas_altas",
                labels={'fecha': 'Fecha', 'alertas_altas': 'Alertas P1+P2'},
                markers=True
            )
            fig_evol.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), hovermode='x')
            st.plotly_chart(fig_evol, use_container_width=True)

    with col_top5:
        st.markdown("#### 🚨 Top 5 marcas más riesgosas")
        df_marcas = fetch_riesgo_promedio_por_marca()

        if df_marcas.empty:
            empty_state("Sin scoring disponible para calcular riesgo por marca.", height=280)
        else:
            fig_top = px.bar(
                df_marcas, y='marca', x='prob_promedio',
                orientation='h', color='prob_promedio',
                color_continuous_scale='Reds',
                labels={'marca': 'Marca', 'prob_promedio': 'Prob promedio'}
            )
            fig_top.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
            st.plotly_chart(fig_top, use_container_width=True)


# ============================================================================
# VISTA 2 — PLAN DE ACCIÓN: MANTENIMIENTO Y REPUESTOS
# ============================================================================

def vista_2_plan_accion():
    """Vista 2: Plan de intervenciones y repuestos recomendados"""
    st.markdown("### 🔧 Plan de acción: mantenimiento y repuestos")

    # Hero metrics
    st.markdown("#### 📋 Intervenciones recomendadas")
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        n_7d = fetch_intervenciones_proximas(7)
        st.metric("Próx. 7 días", fmt_num(n_7d))

    with col2:
        n_30d = fetch_intervenciones_proximas(30)
        st.metric("Próx. 30 días", fmt_num(n_30d))

    with col3:
        # SKU en quiebre: requiere repuestos_maestro
        if check_table_exists("repuestos_maestro"):
            df_q = query_db("""
                SELECT COUNT(*) AS n FROM repuestos_maestro
                WHERE stock_actual <= COALESCE(stock_minimo, 0);
            """)
            quiebre = int(df_q.iloc[0]["n"]) if not df_q.empty else 0
            st.metric("SKU en quiebre", fmt_num(quiebre))
        else:
            st.metric("SKU en quiebre", "Sin datos")
            st.caption("Requiere repuestos_maestro")

    with col4:
        st.metric("Cobertura stock", "Sin datos")
        st.caption("Requiere repuestos_maestro")

    with col5:
        pm = fetch_cumplimiento_pm()
        st.metric("Cumpl. PM", fmt_pct(pm, 0) if pm is not None else "Sin datos")

    with col6:
        backlog = fetch_backlog_ot()
        st.metric("Backlog", f"{fmt_num(backlog)} OT")

    st.markdown("---")

    # Tabla de intervenciones recomendadas
    st.markdown("#### 🎯 Intervenciones sugeridas (próximos 30 días)")
    df_intervenciones = fetch_intervenciones_recomendadas(horizonte_dias=30)
    
    # FILTRO OPCIÓN A (Temporal): Excluir unidades sin histórico de OT correctivas en últimos 90 días
    # Estas unidades muestran "Sin clasificar" en Sistema y no tienen datos para calcular costos
    # TODO (Revisión futura): Cuando tengamos más datos históricos, evaluar si incluir unidades nuevas
    # con estimaciones. Por ahora, filtramos para mostrar solo unidades con datos reales.
    if not df_intervenciones.empty:
        df_intervenciones = df_intervenciones[df_intervenciones["sistema"].notna() & 
                                               (df_intervenciones["sistema"] != "Sin clasificar")]

    if df_intervenciones.empty:
        empty_state(
            "Sin alertas P1/P2 en el último scoring. Ejecute scoring_diario.py "
            "o revise que existan unidades con prioridad alta.",
            height=120
        )
    else:
        # Mapear costo estimado y costo de no intervenir desde costo promedio por sistema
        df_costos = fetch_costo_promedio_por_sistema()
        if not df_costos.empty:
            df_costos["sistema_norm"] = df_costos["sistema"].str.lower()
            df_intervenciones["sistema_norm"] = df_intervenciones["sistema"].str.lower()
            df_intervenciones = df_intervenciones.merge(
                df_costos[["sistema_norm", "costo_promedio"]],
                on="sistema_norm", how="left"
            )
            df_intervenciones["Costo estimado"] = df_intervenciones["costo_promedio"].apply(fmt_clp)
            df_intervenciones["Costo NO intervenir"] = (
                df_intervenciones["costo_promedio"].fillna(0) *
                df_intervenciones["probabilidad_falla"].fillna(0).astype(float) * 3
            ).apply(fmt_clp)
        else:
            df_intervenciones["Costo estimado"] = "Sin datos"
            df_intervenciones["Costo NO intervenir"] = "Sin datos"

        # Mapear urgencia legible
        urg_map = {
            "P1_critica": "P1", "P2_alta": "P2",
            "P3_media": "P3", "P4_baja": "P4"
        }
        df_intervenciones["Urgencia"] = df_intervenciones["urgencia"].map(urg_map).fillna(df_intervenciones["urgencia"])

        display = df_intervenciones.rename(columns={
            "patente": "Patente",
            "tipo": "Tipo",
            "sistema": "Sistema",
        })[["Patente", "Tipo", "Sistema", "Urgencia", "Costo estimado", "Costo NO intervenir"]]

        st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Sección de repuestos
    st.markdown("#### 📦 Repuestos críticos y abastecimiento")

    tiene_maestro = check_table_exists("repuestos_maestro")
    if not tiene_maestro:
        st.info(
            "⚠️ Esta sección requiere que el cliente tenga maestro de repuestos (SKU + stock). "
            "Actualmente se muestra en **modo reducido** a partir de repuestos_consumidos."
        )

    df_rep = fetch_repuestos_estado()

    if df_rep.empty:
        empty_state(
            "Sin datos de repuestos en la base. Verifique repuestos_consumidos.",
            height=120
        )
    else:
        if tiene_maestro:
            display_rep = df_rep[["sku", "descripcion", "stock_actual", "lead_time", "cobertura_dias", "criticidad"]]
            display_rep = display_rep.rename(columns={
                "sku": "SKU", "descripcion": "Descripción",
                "stock_actual": "Stock actual", "lead_time": "Lead time (días)",
                "cobertura_dias": "Cobertura (días)", "criticidad": "Criticidad"
            })
        else:
            display_rep = df_rep[["sku", "descripcion", "cantidad_consumida_total", "costo_total_consumido"]]
            display_rep = display_rep.rename(columns={
                "sku": "SKU", "descripcion": "Descripción",
                "cantidad_consumida_total": "Cantidad consumida",
                "costo_total_consumido": "Costo total"
            })
            if "Costo total" in display_rep.columns:
                display_rep["Costo total"] = display_rep["Costo total"].apply(fmt_clp)

        st.dataframe(display_rep, use_container_width=True, hide_index=True)

    col_riesgo, col_top_cost = st.columns(2)

    with col_riesgo:
        st.markdown("#### ⚠️ Repuestos en riesgo de quiebre")
        if tiene_maestro and not df_rep.empty:
            en_riesgo = df_rep[df_rep["cobertura_dias"].fillna(999) < 30]
            if len(en_riesgo) > 0:
                st.dataframe(
                    en_riesgo[["sku", "stock_actual", "cobertura_dias"]].rename(columns={
                        "sku": "SKU",
                        "stock_actual": "Stock actual",
                        "cobertura_dias": "Cobertura (días)"
                    }),
                    use_container_width=True, hide_index=True
                )
            else:
                st.success("✅ Ningún repuesto crítico en riesgo.")
        else:
            empty_state("Requiere repuestos_maestro con stock y lead time.", height=180)

    with col_top_cost:
        st.markdown("#### 💰 Top 5 repuestos por costo")
        if not df_rep.empty:
            col_costo_rep = "costo_total_consumido" if not tiene_maestro else None
            if col_costo_rep and col_costo_rep in df_rep.columns:
                top5 = df_rep.nlargest(5, col_costo_rep)[["sku", col_costo_rep]].copy()
                top5 = top5.rename(columns={"sku": "SKU", col_costo_rep: "Costo anual"})

                fig_cost = px.bar(
                    top5, y="SKU", x="Costo anual", orientation='h',
                    color="Costo anual", color_continuous_scale='Reds'
                )
                fig_cost.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
                st.plotly_chart(fig_cost, use_container_width=True)
            else:
                empty_state("Requiere maestro con costos para top 5.", height=280)
        else:
            empty_state("Sin datos de repuestos.", height=280)

    # Cumplimiento de PM
    st.markdown("---")
    st.markdown("#### 📅 Mantenimiento preventivo")
    col_gauge, col_pm = st.columns(2)

    with col_gauge:
        st.markdown("**% Cumplimiento global**")
        pm_pct = fetch_cumplimiento_pm()
        if pm_pct is not None:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=pm_pct,
                domain={'x': [0, 1], 'y': [0, 1]},
                gauge={'axis': {'range': [0, 100]},
                       'bar': {'color': "darkgreen"},
                       'steps': [
                           {'range': [0, 50], 'color': "#f8d7da"},
                           {'range': [50, 80], 'color': "#fff3cd"},
                           {'range': [80, 100], 'color': "#d4edda"}
                       ]}
            ))
            fig_gauge.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_gauge, use_container_width=True)
        else:
            empty_state(
                "Sin OT preventivas en últimos 90 días o sin fecha de cierre. "
                "No es posible calcular cumplimiento.",
                height=280
            )

    with col_pm:
        st.markdown("**PM vencidos**")
        df_pm = fetch_pm_vencidos()
        if df_pm.empty:
            empty_state("Sin PM vencidos detectados.", height=280)
        else:
            st.dataframe(
                df_pm.rename(columns={
                    "patente": "Patente",
                    "pm_vencida": "PM vencida",
                    "proximo_sistema": "Próximo sistema"
                }),
                use_container_width=True, hide_index=True
            )


# ============================================================================
# VISTA 3 — IMPACTO Y DESEMPEÑO DEL MODELO
# ============================================================================

def vista_3_impacto_desempeno():
    """Vista 3: Resultados económicos y desempeño del modelo"""
    st.markdown("### 📊 Impacto y desempeño del modelo")

    # Banda superior — económica
    st.markdown("#### 💰 Resultados económicos")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        costo_evitado = fetch_costo_evitado_acumulado()
        st.metric("Costo evitado acumulado", fmt_clp(costo_evitado))
        st.caption("*(solo alertas confirmadas)*" if costo_evitado is not None else "Requiere feedback_alertas")

    with col2:
        downtime_evitado = fetch_downtime_evitado_horas()
        st.metric(
            "Downtime evitado",
            f"{fmt_num(downtime_evitado, 0)} horas" if downtime_evitado is not None else "Sin datos"
        )
        st.caption("*(MTTR promedio × alertas)*" if downtime_evitado is not None else "Requiere feedback_alertas")

    with col3:
        costo_km, _ = fetch_costo_mantenimiento_por_km_unidad()
        st.metric(
            "Costo mantenimiento/km",
            fmt_clp(costo_km) if costo_km is not None else "Sin datos"
        )

    with col4:
        _, costo_unidad = fetch_costo_mantenimiento_por_km_unidad()
        st.metric(
            "Costo mantenimiento/unidad",
            fmt_clp(costo_unidad) if costo_unidad is not None else "Sin datos"
        )

    st.markdown("---")

    # Productividad de flota
    st.markdown("#### 📈 Productividad y eficiencia de flota")
    col_prod1, col_prod2 = st.columns(2)

    with col_prod1:
        st.markdown("**MTBF, MTTR, Disponibilidad — últimos 12 meses**")
        df_mtbf = fetch_mtbf_mttr_12m()

        if df_mtbf.empty:
            empty_state(
                "Sin OT en los últimos 12 meses o sin fecha_cierre. "
                "No es posible calcular MTBF/MTTR.",
                height=320
            )
        else:
            fig_prod = go.Figure()
            if "mtbf_h" in df_mtbf.columns:
                fig_prod.add_trace(go.Scatter(
                    x=df_mtbf['mes'], y=df_mtbf['mtbf_h'],
                    name='MTBF (horas)', yaxis='y'
                ))
            if "mttr_h" in df_mtbf.columns:
                fig_prod.add_trace(go.Scatter(
                    x=df_mtbf['mes'], y=df_mtbf['mttr_h'],
                    name='MTTR (horas)', yaxis='y2'
                ))
            fig_prod.update_layout(
                yaxis=dict(title='MTBF (horas)'),
                yaxis2=dict(title='MTTR (horas)', overlaying='y', side='right'),
                hovermode='x', height=350, margin=dict(l=0, r=0, t=30, b=0)
            )
            st.plotly_chart(fig_prod, use_container_width=True)

    with col_prod2:
        st.markdown("**Downtime planificado vs no planificado**")
        df_dt = fetch_downtime_mensual()

        if df_dt.empty:
            empty_state(
                "Sin OT con fecha de cierre en últimos 12 meses para calcular downtime.",
                height=320
            )
        else:
            df_dt = df_dt.rename(columns={
                "planificado_h": "Planificado (h)",
                "no_planificado_h": "No planificado (h)"
            })
            fig_down = px.bar(
                df_dt, x='mes', y=['Planificado (h)', 'No planificado (h)'],
                barmode='stack', color_discrete_map={
                    'Planificado (h)': '#4285F4', 'No planificado (h)': '#EA4335'
                }
            )
            fig_down.update_layout(
                height=350, margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
            )
            st.plotly_chart(fig_down, use_container_width=True)

    # Comparación antes/después — CANDADO HASTA MES 6
    st.markdown("---")
    st.markdown("#### 🔄 Comparación antes/después del modelo")

    tiempo_uso = fetch_tiempo_uso_meses()
    if tiempo_uso < 6:
        st.info(
            f"⏳ Esta métrica se activará en el **mes 6** de uso. "
            f"Actualmente en mes {tiempo_uso}. "
            f"Se necesita ≥6 meses de datos en producción para una comparación válida."
        )
    else:
        # Cuando exista mes 6, se calculará comparando OT de los 6 meses
        # previos vs los 6 con modelo activo. Por ahora, mantener vacío controlado.
        empty_state(
            "Comparación antes/después: requiere implementación del cálculo "
            "(periodo previo vs periodo con modelo activo).",
            height=120
        )

    # Desempeño del modelo
    st.markdown("---")
    st.markdown("#### 🧠 Desempeño del modelo de IA")
    col_perf1, col_perf2 = st.columns(2)

    metricas_modelo = fetch_modelo_metricas()

    with col_perf1:
        st.markdown("**Explicabilidad y confiabilidad**")
        if not metricas_modelo:
            empty_state("Sin modelo activo registrado en modelos_registro.", height=240)
        else:
            recall = metricas_modelo.get("recall")
            precision = metricas_modelo.get("precision")

            # Construir métricas legibles
            if recall is not None and not pd.isna(recall):
                st.write(f"**De cada 10 fallas, alertamos:** {float(recall)*10:.1f} con anticipación (Recall)")
            else:
                st.write("**De cada 10 fallas, alertamos:** Sin datos (no hay test set evaluable)")

            if precision is not None and not pd.isna(precision):
                st.write(f"**De cada 10 alertas, eran correctas:** {float(precision)*10:.1f} (Precision)")
            else:
                st.write("**De cada 10 alertas, eran correctas:** Sin datos")

            # Anticipación promedio: requiere feedback con timestamps
            if check_table_exists("feedback_alertas"):
                df_ant = query_db("""
                    SELECT AVG(
                        EXTRACT(DAY FROM (
                            (SELECT MIN(fecha_apertura)
                             FROM ordenes_trabajo o
                             WHERE o.activo_id = f.activo_id
                               AND o.fecha_apertura >= f.fecha_feedback
                               AND LOWER(COALESCE(o.tipo_ot, '')) IN ('correctiva', 'correctivo')
                            ) - f.fecha_feedback::timestamp
                        ))
                    ) AS dias_promedio
                    FROM feedback_alertas f
                    WHERE f.falla_real = TRUE;
                """)
                if not df_ant.empty and df_ant.iloc[0]["dias_promedio"] is not None:
                    st.write(f"**Anticipación promedio:** {float(df_ant.iloc[0]['dias_promedio']):.0f} días antes de falla")
                else:
                    st.write("**Anticipación promedio:** Sin datos suficientes")
            else:
                st.write("**Anticipación promedio:** Sin datos (requiere feedback_alertas)")

            # Distribución de feedback
            df_fb = fetch_feedback_estados()
            if not df_fb.empty:
                total_fb = df_fb["cantidad"].sum()
                conf = df_fb[df_fb["estado"].str.lower().isin(["confirmada", "revisada"])]["cantidad"].sum()
                rech = df_fb[df_fb["estado"].str.lower().isin(["descartada", "rechazada"])]["cantidad"].sum()
                pend = df_fb[df_fb["estado"].str.lower() == "pendiente"]["cantidad"].sum()

                if total_fb > 0:
                    st.write(f"**Alertas confirmadas por taller:** {conf/total_fb*100:.0f}%")
                    st.write(f"**Alertas rechazadas:** {rech/total_fb*100:.0f}%")
                    st.write(f"**Pendientes de revisión:** {pend/total_fb*100:.0f}%")
            else:
                st.write("**Alertas confirmadas por taller:** Sin datos")
                st.write("**Alertas rechazadas:** Sin datos")
                st.write("**Pendientes de revisión:** Sin datos")

    with col_perf2:
        st.markdown("**Matriz de confusión simplificada**")
        if not check_table_exists("feedback_alertas"):
            empty_state(
                "Requiere feedback_alertas para construir la matriz real "
                "(no se inventan números).",
                height=240
            )
        else:
            df_mc = query_db("""
                WITH alertas AS (
                    SELECT s.scoring_id, s.prioridad,
                           CASE WHEN s.prioridad IN ('P1_critica', 'P2_alta') THEN 1 ELSE 0 END AS alertamos
                    FROM scoring_resultados s
                ),
                feedback AS (
                    SELECT scoring_id,
                           CASE WHEN falla_real THEN 1 ELSE 0 END AS hubo_falla
                    FROM feedback_alertas
                )
                SELECT
                    SUM(CASE WHEN a.alertamos = 1 AND f.hubo_falla = 1 THEN 1 ELSE 0 END) AS tp,
                    SUM(CASE WHEN a.alertamos = 1 AND f.hubo_falla = 0 THEN 1 ELSE 0 END) AS fp,
                    SUM(CASE WHEN a.alertamos = 0 AND f.hubo_falla = 1 THEN 1 ELSE 0 END) AS fn,
                    SUM(CASE WHEN a.alertamos = 0 AND f.hubo_falla = 0 THEN 1 ELSE 0 END) AS tn
                FROM alertas a
                INNER JOIN feedback f ON f.scoring_id = a.scoring_id;
            """)
            if df_mc.empty or df_mc.iloc[0].isna().all():
                empty_state("Aún no hay suficiente feedback para construir la matriz.", height=240)
            else:
                tp = int(df_mc.iloc[0]["tp"] or 0)
                fp = int(df_mc.iloc[0]["fp"] or 0)
                fn = int(df_mc.iloc[0]["fn"] or 0)
                tn = int(df_mc.iloc[0]["tn"] or 0)
                confusion = pd.DataFrame({
                    '': ['Falla real', 'No falla'],
                    'Alertamos': [tp, fp],
                    'No alertamos': [fn, tn]
                })
                st.dataframe(confusion, use_container_width=True, hide_index=False)
                st.caption("Formato: casos validados con feedback del taller")

    # Estado del modelo
    if metricas_modelo:
        version = metricas_modelo.get("version", "desconocido")
        st.markdown(f"**Estado del modelo:** 🟢 Activo — versión `{version}`")
    else:
        st.markdown("**Estado del modelo:** 🔴 Sin modelo activo registrado")

    # Feedback del taller
    st.markdown("---")
    st.markdown("#### 📝 Feedback del taller y ciclo de aprendizaje")
    col_fb1, col_fb2 = st.columns(2)

    with col_fb1:
        st.markdown("**Alertas por estado**")
        df_fb_est = fetch_feedback_estados()
        if df_fb_est.empty:
            empty_state(
                "Sin feedback registrado todavía. "
                "Activar tabla feedback_alertas y comenzar captura desde el taller.",
                height=320
            )
        else:
            fig_fb = px.pie(
                df_fb_est, values='cantidad', names='estado',
                color_discrete_map={
                    'confirmada': '#4CAF50', 'Confirmadas': '#4CAF50',
                    'parcial': '#FFC107', 'Parciales': '#FFC107',
                    'descartada': '#F44336', 'rechazada': '#F44336',
                    'pendiente': '#9E9E9E', 'Pendientes': '#9E9E9E'
                }
            )
            fig_fb.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_fb, use_container_width=True)

    with col_fb2:
        st.markdown("**Top motivos de rechazo**")
        df_motivos = fetch_motivos_rechazo()
        if df_motivos.empty:
            empty_state("Sin motivos de rechazo registrados.", height=320)
        else:
            fig_rech = px.bar(
                df_motivos, y='motivo', x='cantidad', orientation='h',
                color='cantidad', color_continuous_scale='Blues'
            )
            fig_rech.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
            st.plotly_chart(fig_rech, use_container_width=True)

    # ROI y payback — CANDADO HASTA MES 6
    st.markdown("---")
    st.markdown("#### 💼 ROI y retorno de inversión")

    if tiempo_uso < 6:
        st.info(
            f"⏳ **ROI y payback se activan en mes 6.** "
            f"Actualmente en mes {tiempo_uso}. "
            f"Con 6 meses de operación tendremos baseline sólido para estas métricas."
        )
    else:
        col_roi1, col_roi2 = st.columns(2)
        with col_roi1:
            costo_evitado = fetch_costo_evitado_acumulado()
            st.metric(
                "ROI estimado",
                "Sin datos" if costo_evitado is None else "Pendiente cálculo"
            )
            st.caption("Costo evitado / costo BAITECK — requiere costo del servicio")
        with col_roi2:
            st.metric("Payback estimado", "Pendiente cálculo")
            st.caption("Días para recuperar inversión")


# ============================================================================
# MAIN LAYOUT
# ============================================================================

def main():
    # Crear layout con columnas: título a la izquierda, logo a la derecha
    col_title, col_logo = st.columns([4, 1])

    with col_title:
        st.title("📊 BAITECK — Dashboard Predictivo de Flotas")
        st.markdown("Versión 1.0 — Diseño operativo y comercial")

    with col_logo:
        # Logo en esquina superior derecha — IDÉNTICO a dashboard_com.py
        logo_path = "Logo_BAITECK.jpg"
        try:
            if os.path.exists(logo_path):
                st.image(logo_path, width=100, use_container_width=False)
            elif os.path.exists(f"/mnt/user-data/uploads/{logo_path}"):
                st.image(f"/mnt/user-data/uploads/{logo_path}", width=100, use_container_width=False)
            elif os.path.exists(f"baiteck-dashboard-assets/{logo_path}"):
                st.image(f"baiteck-dashboard-assets/{logo_path}", width=100, use_container_width=False)
            else:
                st.markdown(
                    "<div style='padding: 10px; text-align: center; color: #999; font-size: 10px;'>Logo no encontrado</div>",
                    unsafe_allow_html=True
                )
        except Exception as e:
            st.markdown(
                f"<div style='padding: 10px; text-align: center; color: #999; font-size: 10px;'>Error: {str(e)[:50]}</div>",
                unsafe_allow_html=True
            )

    # Selector de vista en sidebar
    with st.sidebar:
        st.markdown("## 🎯 Navegación")
        vista_seleccionada = st.radio(
            "Selecciona una vista",
            ["Estado y Riesgo", "Plan de Acción", "Impacto y Desempeño"]
        )

        st.markdown("---")
        st.markdown("### ℹ️ Acerca de")

        # Estado de conexión — UNA SOLA VEZ, aquí
        conn = get_db_connection()
        status_conexion = "✅ Conectado" if conn is not None else "❌ Sin conexión"

        # Validación de datos
        n_total = fetch_unidades_total()
        n_op = fetch_unidades_operativas()

        st.markdown(f"""
        **BAITECK v1.0** — Mantenimiento predictivo de flotas.

        - **Vista 1:** Qué pasa, qué va a fallar.
        - **Vista 2:** Qué hacer, con qué repuestos.
        - **Vista 3:** Cuánto está rindiendo.

        **Estado:**
        - Supabase: {status_conexion}
        - Unidades en base: **{n_total}**
        - Operativas: **{n_op}**
        """)

    # Render vista seleccionada
    if vista_seleccionada == "Estado y Riesgo":
        vista_1_estado_riesgo()
    elif vista_seleccionada == "Plan de Acción":
        vista_2_plan_accion()
    else:
        vista_3_impacto_desempeno()

    # Footer
    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #999; font-size: 12px;'>"
        "BAITECK © 2026 — Inteligencia operacional predictiva para flotas"
        "</div>",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
