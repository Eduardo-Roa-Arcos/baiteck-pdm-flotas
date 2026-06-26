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
  - feedback_taller
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
from sqlalchemy import create_engine, text

# ============================================================================
# CONFIG Y CONEXIÓN
# ============================================================================

st.set_page_config(
    page_title="BAITECK — Dashboard PDM",
    layout="wide",
    initial_sidebar_state="expanded"
)

# SVG de fondo futurista con gradiente azul profundo + más estrellas/luces
svg_bg = """
<svg width="100%" height="100%" style="position: fixed; top: 0; left: 0; z-index: -1; opacity: 0.3;">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#0a1f3d;stop-opacity:0.8" />
      <stop offset="100%" style="stop-color:#051428;stop-opacity:0.8" />
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
      <feMerge>
        <feMergeNode in="coloredBlur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>
  <rect width="100%" height="100%" fill="url(#grad)"/>
  
  <!-- Estrellas/puntos de luz distribuidos -->
  <circle cx="5%" cy="8%" r="1.5" fill="#007ACC" opacity="0.8" filter="url(#glow)"/>
  <circle cx="10%" cy="15%" r="2.5" fill="#007ACC" opacity="0.7"/>
  <circle cx="15%" cy="5%" r="1" fill="#007ACC" opacity="0.6"/>
  <circle cx="20%" cy="20%" r="1.8" fill="#007ACC" opacity="0.8" filter="url(#glow)"/>
  <circle cx="25%" cy="10%" r="2" fill="#007ACC" opacity="0.7"/>
  <circle cx="35%" cy="25%" r="2.2" fill="#007ACC" opacity="0.8"/>
  <circle cx="45%" cy="12%" r="1.5" fill="#007ACC" opacity="0.6"/>
  <circle cx="50%" cy="20%" r="1.8" fill="#007ACC" opacity="0.7" filter="url(#glow)"/>
  <circle cx="60%" cy="8%" r="1.2" fill="#007ACC" opacity="0.7"/>
  <circle cx="70%" cy="15%" r="2" fill="#007ACC" opacity="0.8"/>
  <circle cx="80%" cy="10%" r="1.5" fill="#007ACC" opacity="0.6"/>
  <circle cx="85%" cy="30%" r="2.2" fill="#007ACC" opacity="0.7" filter="url(#glow)"/>
  <circle cx="92%" cy="5%" r="1.2" fill="#007ACC" opacity="0.8"/>
  <circle cx="8%" cy="45%" r="1.8" fill="#007ACC" opacity="0.7"/>
  <circle cx="15%" cy="50%" r="2" fill="#007ACC" opacity="0.8" filter="url(#glow)"/>
  <circle cx="35%" cy="55%" r="1.5" fill="#007ACC" opacity="0.6"/>
  <circle cx="45%" cy="48%" r="1.8" fill="#007ACC" opacity="0.7"/>
  <circle cx="55%" cy="60%" r="2.2" fill="#007ACC" opacity="0.8"/>
  <circle cx="70%" cy="50%" r="1.2" fill="#007ACC" opacity="0.7"/>
  <circle cx="82%" cy="55%" r="1.8" fill="#007ACC" opacity="0.6" filter="url(#glow)"/>
  <circle cx="10%" cy="80%" r="2" fill="#007ACC" opacity="0.8"/>
  <circle cx="25%" cy="75%" r="1.5" fill="#007ACC" opacity="0.7"/>
  <circle cx="40%" cy="88%" r="1.8" fill="#007ACC" opacity="0.6"/>
  <circle cx="60%" cy="85%" r="2.2" fill="#007ACC" opacity="0.8" filter="url(#glow)"/>
  <circle cx="75%" cy="78%" r="1.5" fill="#007ACC" opacity="0.7"/>
  <circle cx="88%" cy="90%" r="1.8" fill="#007ACC" opacity="0.7"/>
  
  <!-- Líneas de conexión sutiles -->
  <line x1="10%" y1="15%" x2="25%" y2="10%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="25%" y1="10%" x2="35%" y2="25%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="35%" y1="25%" x2="50%" y2="20%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="50%" y1="20%" x2="70%" y2="15%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="15%" y1="50%" x2="45%" y2="48%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="45%" y1="48%" x2="70%" y2="50%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="10%" y1="80%" x2="40%" y2="88%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="40%" y1="88%" x2="60%" y2="85%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
  <line x1="60%" y1="85%" x2="88%" y2="90%" stroke="#007ACC" stroke-width="0.5" opacity="0.2"/>
</svg>
"""
st.markdown(svg_bg, unsafe_allow_html=True)

# CSS personalizado
st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background: linear-gradient(135deg, #0a1f3d 0%, #051428 100%) !important; }
    .stApp { background: linear-gradient(135deg, #0a1f3d 0%, #051428 100%) !important; }
    
    /* Barra superior AZUL OSCURO */
    [data-testid="stHeader"] { background: #003d7a !important; }
    header { background: #003d7a !important; }
    
    /* Sidebar GRIS con TEXTO NEGRO */
    [data-testid="stSidebar"] { background: #f8f9fa !important; }
    [data-testid="stSidebar"] * { color: #000000 !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] div { color: #000000 !important; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #000000 !important; }
    
    /* Métricas: números en BLANCO, fondo transparente */
    .hero-metric { font-size: 32px; font-weight: bold; text-align: center; padding: 15px; border-radius: 8px; background: rgba(0, 30, 60, 0.4); border: 1px solid rgba(0, 122, 204, 0.4); color: #ffffff !important; }
    
    /* Colores de tendencias MÁS BRILLANTES Y CLAROS */
    .metric-green { background: rgba(144, 238, 144, 0.25); color: #66FF66; border: 1px solid rgba(144, 238, 144, 0.6); font-weight: bold; }
    .metric-yellow { background: rgba(255, 223, 0, 0.2); color: #FFFF00; border: 1px solid rgba(255, 223, 0, 0.6); font-weight: bold; }
    .metric-red { background: rgba(255, 102, 102, 0.25); color: #FF6666; border: 1px solid rgba(255, 102, 102, 0.6); font-weight: bold; }
    
    .candado { color: #b0b0b0; font-size: 12px; }
    .logo-container { display: flex; justify-content: flex-end; padding: 10px 15px 0 0; margin: 0 0 -80px 0; }
    .logo-baiteck { width: 100px; height: auto; object-fit: contain; }
    
    /* Tabla ranking con fondo gris oscuro */
    [data-testid="stDataFrame"] { background: #1a1a1a !important; }
    [role="grid"] { background: #1a1a1a !important; }
    table { background: #1a1a1a !important; }
    th { background: #2a2a2a !important; color: #ffffff !important; }
    td { background: #1a1a1a !important; color: #e0e0e0 !important; }
    
    .empty-state { background: rgba(0, 122, 204, 0.15); border: 1px dashed rgba(0, 122, 204, 0.5); border-radius: 6px; padding: 20px; text-align: center; color: #a8a8a8; font-size: 13px; }
    
    h1, h2, h3, h4, h5, h6 { color: #ffffff !important; }
    p, span { color: #e0e0e0 !important; }
    
    input, select, textarea { background-color: rgba(0, 122, 204, 0.1) !important; color: #ffffff !important; border: 1px solid rgba(0, 122, 204, 0.3) !important; }
    button { background: #003d7a !important; color: #ffffff !important; }
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




@st.cache_resource
def get_engine():
    """Engine de SQLAlchemy para leer de tabla paneles (cache de recurso)."""
    try:
        url = os.getenv("DATABASE_URL")
        if not url:
            return None
        return create_engine(url, pool_pre_ping=True)
    except Exception:
        return None


def fetch_metrica_paneles(vista: str, metrica: str, horizonte_dias: Optional[int] = None) -> Optional[float]:
    """
    Obtiene una métrica desde tabla `paneles` (última actualización).
    
    Query: SELECT valor FROM paneles WHERE vista=... AND metrica=... 
           ORDER BY fecha_calculo DESC LIMIT 1
    """
    engine = get_engine()
    if engine is None:
        return None
    
    try:
        with engine.connect() as conn:
            if horizonte_dias is not None:
                query = text("""
                    SELECT valor FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias = :horizonte
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                result = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica,
                    "horizonte": horizonte_dias
                }).scalar()
            else:
                query = text("""
                    SELECT valor FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias IS NULL
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                result = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica
                }).scalar()
        return result
    except Exception:
        return None


def fetch_metrica_anterior_paneles(vista: str, metrica: str, horizonte_dias: Optional[int] = None) -> Optional[float]:
    """
    Obtiene el valor anterior de una métrica desde paneles (para cálculo de delta).
    """
    engine = get_engine()
    if engine is None:
        return None
    
    try:
        with engine.connect() as conn:
            if horizonte_dias is not None:
                query = text("""
                    SELECT valor_anterior FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias = :horizonte
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                result = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica,
                    "horizonte": horizonte_dias
                }).scalar()
            else:
                query = text("""
                    SELECT valor_anterior FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias IS NULL
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                result = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica
                }).scalar()
        return result
    except Exception:
        return None

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
    """Cuenta de unidades operativas (desde paneles)."""
    valor = fetch_metrica_paneles("Estado y Riesgo", "Unidades operativas")
    return int(valor) if valor is not None else 0


@st.cache_data(ttl=300)
def fetch_unidades_total() -> int:
    """Cuenta total de unidades en la flota (sin filtrar por estado)."""
    df = query_db("SELECT COUNT(*) AS n FROM activos;")
    if df.empty:
        return 0
    return int(df.iloc[0]["n"])


@st.cache_data(ttl=300)
def fetch_disponibilidad_30d() -> Optional[float]:
    """Disponibilidad operacional últimos 30 días (desde paneles)."""
    return fetch_metrica_paneles("Estado y Riesgo", "Disponibilidad")


@st.cache_data(ttl=300)
def fetch_conteo_prioridad(prioridad: str, horizonte_dias: int = 30) -> int:
    """Cuenta de unidades con prioridad desde tabla paneles (precalculado)."""
    # Mapear prioridad a nombre de métrica en paneles
    metrica_map = {
        "P1_critica": "P1 Crítica",
        "P2_alta": "P2 Alta",
        "P3_media": "P3 Media",
        "P4_baja": "P4 Baja"
    }
    metrica = metrica_map.get(prioridad, "")
    
    if not metrica:
        return 0
    
    df = query_db("""
        SELECT valor FROM paneles 
        WHERE vista = 'Estado y Riesgo' AND metrica = %s AND horizonte_dias = %s
        ORDER BY fecha_calculo DESC LIMIT 1
    """, params=(metrica, horizonte_dias))
    
    if df.empty or df.iloc[0]['valor'] is None:
        return 0
    return int(df.iloc[0]['valor'])

@st.cache_data(ttl=300)
def fetch_fallas_anticipadas_30d() -> int:
    """Fallas anticipadas confirmadas últimos 30 días (desde paneles)."""
    valor = fetch_metrica_paneles("Estado y Riesgo", "Fallas anticipadas")
    return int(valor) if valor is not None else 0

@st.cache_data(ttl=300)
def fetch_mtbf_horas() -> Optional[float]:
    """MTBF en horas últimos 180 días (desde paneles)."""
    return fetch_metrica_paneles("Estado y Riesgo", "MTBF")

# ============================================================================
# TENDENCIAS DE HERO METRICS (desde tabla paneles)
# ----------------------------------------------------------------------------
# La tendencia se lee directamente de la tabla paneles: cada métrica guarda
# valor (medición actual) y valor_anterior (medición previa), poblados por
# calcular_paneles.py. El delta mostrado es la diferencia absoluta entre ambos.
# Devuelve None cuando valor_anterior es NULL (primera medición) — en ese caso
# st.metric omite el delta automáticamente (no se inventa nada).
# ============================================================================

@st.cache_data(ttl=300)
def fetch_tendencia_paneles(vista: str, metrica: str,
                            horizonte_dias: Optional[int] = None) -> Optional[float]:
    """Delta absoluto (valor - valor_anterior) desde la fila más reciente de paneles.

    Lee ambos valores de la MISMA fila para garantizar coherencia entre el
    valor mostrado y su tendencia. Devuelve None si no hay fila o si
    valor_anterior es NULL.
    """
    engine = get_engine()
    if engine is None:
        return None

    try:
        with engine.connect() as conn:
            if horizonte_dias is not None:
                query = text("""
                    SELECT valor, valor_anterior FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias = :horizonte
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                row = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica,
                    "horizonte": horizonte_dias
                }).fetchone()
            else:
                query = text("""
                    SELECT valor, valor_anterior FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias IS NULL
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                row = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica
                }).fetchone()
        if row is None or row[0] is None or row[1] is None:
            return None
        return float(row[0]) - float(row[1])
    except Exception:
        return None


def fetch_valor_paneles(vista: str, metrica: str,
                       horizonte_dias: Optional[int] = None) -> Optional[float]:
    """Obtiene el VALOR ACTUAL de una métrica desde paneles (no la tendencia).
    
    Retorna None si no existe la métrica o si el valor es NULL.
    """
    engine = get_engine()
    if engine is None:
        return None

    try:
        with engine.connect() as conn:
            if horizonte_dias is not None:
                query = text("""
                    SELECT valor FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias = :horizonte
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                row = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica,
                    "horizonte": horizonte_dias
                }).fetchone()
            else:
                query = text("""
                    SELECT valor FROM paneles
                    WHERE vista = :vista AND metrica = :metrica AND horizonte_dias IS NULL
                    ORDER BY fecha_calculo DESC LIMIT 1
                """)
                row = conn.execute(query, {
                    "vista": vista,
                    "metrica": metrica
                }).fetchone()
        
        if row is None or row[0] is None:
            return None
        return float(row[0])
    except Exception:
        return None

@st.cache_data(ttl=300)
def fetch_ranking_riesgo(horizonte_dias: int = 30, top_n: int = 15) -> pd.DataFrame:
    """Top N unidades con mayor probabilidad de falla en horizonte dado.

    Une scoring_resultados (último scoring por activo) con activos.
    Trae también la última OT por activo y opcionalmente el sistema más reciente.
    """
    # Sistema en riesgo: preferir el calculado en scoring_resultados (taxonomía);
    # si no existe, derivar del último evento clasificado del activo; si tampoco, NULL.
    if check_column_exists("scoring_resultados", "sistema_en_riesgo"):
        sistema_select = "us.sistema_en_riesgo"
        sistema_scoring_col = ", sistema_en_riesgo"
    elif check_table_exists("ot_falla_evento") and check_table_exists("taxonomia_fallas"):
        sistema_select = ("(SELECT tf.sistema FROM ot_falla_evento ofe "
                          "JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id "
                          "WHERE ofe.activo_id = a.activo_id "
                          "ORDER BY ofe.fecha_evento DESC NULLS LAST LIMIT 1)")
        sistema_scoring_col = ""
    else:
        sistema_select = "NULL"
        sistema_scoring_col = ""

    q = f"""
        WITH ultimo_scoring AS (
            SELECT DISTINCT ON (activo_id)
                activo_id, fecha_scoring, probabilidad_falla, prediccion,
                prioridad, modelo_version, horizonte_dias{sistema_scoring_col}
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

    El sistema se obtiene de la taxonomía real de fallas
    (ot_falla_evento → taxonomia_fallas), no de una columna de texto en
    ordenes_trabajo (que no existe en el esquema actual).
    Si la estructura de taxonomía no existe o está vacía, retorna vacío.
    """
    if not (check_table_exists("ot_falla_evento") and check_table_exists("taxonomia_fallas")):
        return pd.DataFrame()

    df = query_db("""
        WITH ventanas AS (
            SELECT
                COALESCE(NULLIF(LOWER(tf.sistema), ''), 'sin_clasificar') AS sistema,
                CASE
                    WHEN COALESCE(ofe.fecha_evento, ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '7 days'  THEN '7 días'
                    WHEN COALESCE(ofe.fecha_evento, ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '30 days' THEN '30 días'
                    WHEN COALESCE(ofe.fecha_evento, ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '90 days' THEN '90 días'
                    ELSE NULL
                END AS horizonte
            FROM ot_falla_evento ofe
            JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
            LEFT JOIN ordenes_trabajo ot ON ofe.ot_id = ot.ot_id
        )
        SELECT sistema, horizonte, COUNT(*) AS n
        FROM ventanas
        WHERE horizonte IS NOT NULL
        GROUP BY sistema, horizonte;
    """)
    return df


@st.cache_data(ttl=300)
def fetch_intervenciones_recomendadas(horizonte_dias: int = 30) -> pd.DataFrame:
    """Lista de intervenciones sugeridas desde tabla intervenciones_sugeridas.
    
    Lee intervenciones precompiladas según horizonte (7, 30, 90 días).
    Incluye costos estimados y de no intervenir.
    """
    if not check_table_exists("intervenciones_sugeridas"):
        return pd.DataFrame()
    
    h_col = f"h{horizonte_dias}"
    q = f"""
        SELECT patente, tipo, sistema, urgencia, costo_estimado, costo_no_intervenir
        FROM intervenciones_sugeridas
        WHERE {h_col} = 1
        ORDER BY costo_no_intervenir DESC NULLS LAST;
    """
    return query_db(q)

@st.cache_data(ttl=300)
def fetch_costo_promedio_por_sistema() -> pd.DataFrame:
    """Costo promedio de OT correctiva por sistema.

    El sistema se obtiene de la taxonomía real (ot_falla_evento →
    taxonomia_fallas). El costo es la columna canónica costo_total_clp.
    """
    if not (check_table_exists("ot_falla_evento") and check_table_exists("taxonomia_fallas")):
        return pd.DataFrame()
    if not check_column_exists("ordenes_trabajo", "costo_total_clp"):
        return pd.DataFrame()

    q = """
        SELECT
            COALESCE(NULLIF(LOWER(tf.sistema), ''), 'sin_clasificar') AS sistema,
            AVG(COALESCE(ot.costo_total_clp, 0))::numeric(12,0) AS costo_promedio
        FROM ot_falla_evento ofe
        JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
        JOIN ordenes_trabajo ot ON ofe.ot_id = ot.ot_id
        WHERE LOWER(COALESCE(ot.tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')
        GROUP BY tf.sistema;
    """
    return query_db(q)


@st.cache_data(ttl=300)
def fetch_repuestos_estado() -> pd.DataFrame:
    """Estado de repuestos: lee desde tabla paneles_repuestos (precompilada diariamente).
    
    Retorna SKUs con stock actual vs requerido, basado en:
    - Consumo histórico promedio por sistema (últimos 180 días)
    - Intervenciones recomendadas próximas (30 días)
    
    La tabla paneles_repuestos se actualiza diariamente con calcular_repuestos.py
    """
    if not check_table_exists("paneles_repuestos"):
        return pd.DataFrame()
    
    # Lee últimos registros de paneles_repuestos (del día actual)
    return query_db("""
        SELECT
            sku,
            descripcion,
            sistema,
            stock_actual,
            lead_time_dias AS lead_time,
            criticidad,
            costo_unitario_clp,
            cobertura_dias,
            cantidad_promedio_por_intervencion,
            n_intervenciones_proximas,
            stock_requerido,
            brecha,
            fecha_calculo
        FROM paneles_repuestos
        WHERE DATE(fecha_calculo) = CURRENT_DATE
        ORDER BY sku;
    """)


@st.cache_data(ttl=300)
def fetch_repuestos_panel_criticos() -> pd.DataFrame:
    """Lee panel de repuestos críticos basado en predicción P1/P2.
    
    Retorna SKUs con demanda proyectada, cobertura y acciones recomendadas.
    Se actualiza diariamente con 04_demanda_p1p2.py
    
    Filtra solo SKUs válidos (formato REP-XXXX) para evitar descripciones
    que se filtraron incorrectamente en la carga de datos.
    """
    if not check_table_exists("repuestos_panel_criticos"):
        return pd.DataFrame()
    
    return query_db("""
        SELECT
            sku,
            descripcion,
            stock_actual,
            demanda_30d_prediccion,
            demanda_30d_historico,
            lead_time_dias,
            cobertura_dias,
            criticidad,
            accion,
            delta_demanda,
            fecha_calculo
        FROM repuestos_panel_criticos
        WHERE DATE(fecha_calculo) = CURRENT_DATE
          AND sku ~ '^REP-[0-9]{4}$'
        ORDER BY cobertura_dias ASC NULLS LAST
    """)


@st.cache_data(ttl=300)
def fetch_pm_vencidos() -> pd.DataFrame:
    """PM vencidos: requiere un plan de PM. Por ahora se aproxima como
    activos sin OT preventiva en los últimos 90 días.
    """
    if check_table_exists("ot_falla_evento") and check_table_exists("taxonomia_fallas"):
        sistema_sub = ("COALESCE((SELECT tf.sistema FROM ot_falla_evento ofe "
                       "JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id "
                       "WHERE ofe.activo_id = a.activo_id "
                       "ORDER BY ofe.fecha_evento DESC NULLS LAST LIMIT 1), 'Sin clasificar')")
    else:
        sistema_sub = "'Sin clasificar'"

    df = query_db(f"""
        WITH ultima_pm AS (
            SELECT activo_id, MAX(fecha_apertura) AS ultima_pm_fecha
            FROM ordenes_trabajo
            WHERE LOWER(COALESCE(tipo_ot, '')) IN ('preventiva', 'preventivo')
            GROUP BY activo_id
        )
        SELECT
            a.patente,
            COALESCE((CURRENT_DATE - up.ultima_pm_fecha::date)::text || ' días', 'Nunca') AS pm_vencida,
            {sistema_sub} AS proximo_sistema
        FROM activos a
        LEFT JOIN ultima_pm up ON up.activo_id = a.activo_id
        WHERE up.ultima_pm_fecha IS NULL
           OR (CURRENT_DATE - up.ultima_pm_fecha::date) > 90
        ORDER BY up.ultima_pm_fecha NULLS FIRST
        LIMIT 10;
    """)
    return df


@st.cache_data(ttl=300)
def fetch_cumplimiento_pm() -> Optional[float]:
    """Cumplimiento de PM últimos 30 días (desde paneles)."""
    return fetch_metrica_paneles("Plan de Acción", "Cumplimiento PM")
    return float(df.iloc[0]["cerradas"]) / float(df.iloc[0]["total"]) * 100.0


@st.cache_data(ttl=300)
def fetch_backlog_ot() -> int:
    """OT abiertas sin asignación (desde paneles)."""
    valor = fetch_metrica_paneles("Plan de Acción", "Backlog OT")
    return int(valor) if valor is not None else 0
    return int(df.iloc[0]["n"])


@st.cache_data(ttl=300)
def fetch_intervenciones_proximas(dias: int) -> int:
    """Cuenta de unidades con P1/P2 en último scoring del horizonte dado."""
    p1 = fetch_conteo_prioridad("P1_critica", horizonte_dias=dias)
    p2 = fetch_conteo_prioridad("P2_alta", horizonte_dias=dias)
    return p1 + p2


@st.cache_data(ttl=300)
def fetch_costo_evitado_acumulado() -> Optional[float]:
    """Costo evitado acumulado (desde paneles)."""
    return fetch_metrica_paneles("Impacto y Desempeño", "Costo evitado")
    df = query_db("""
        SELECT COALESCE(SUM(costo_reparacion), 0) AS total
        FROM feedback_taller
        WHERE falla_confirmada = TRUE;
    """)
    if df.empty:
        return None
    return float(df.iloc[0]["total"] or 0)


@st.cache_data(ttl=300)
def fetch_downtime_evitado_horas() -> Optional[float]:
    """Downtime evitado en horas (desde paneles)."""
    return fetch_metrica_paneles("Impacto y Desempeño", "Downtime evitado")
    df = query_db("""
        SELECT COALESCE(SUM(horas_detencion), 0) AS total
        FROM feedback_taller
        WHERE falla_confirmada = TRUE;
    """)
    if df.empty:
        return None
    return float(df.iloc[0]["total"] or 0)


@st.cache_data(ttl=300)
def fetch_costo_mantenimiento_por_km_unidad() -> Tuple[Optional[float], Optional[float]]:
    """Retorna (costo/km, costo/unidad) desde tabla paneles (precalculado)."""
    df_km = query_db("""
        SELECT valor FROM paneles 
        WHERE vista = 'Impacto y Desempeño' AND metrica = 'Costo mantenimiento km'        
        ORDER BY fecha_calculo DESC LIMIT 1
    """)
    costo_km = float(df_km.iloc[0]['valor']) if not df_km.empty and df_km.iloc[0]['valor'] is not None else None
    
    df_unidad = query_db("""
        SELECT valor FROM paneles 
        WHERE vista = 'Impacto y Desempeño' AND metrica = 'Costo mantenimiento unidad'        
        ORDER BY fecha_calculo DESC LIMIT 1
    """)
    costo_unidad = float(df_unidad.iloc[0]['valor']) if not df_unidad.empty and df_unidad.iloc[0]['valor'] is not None else None
    
    return (costo_km, costo_unidad)

@st.cache_data(ttl=300)
def fetch_cobertura_stock() -> Optional[float]:
    """Cobertura de stock desde tabla paneles (precalculado)."""
    df = query_db("""
        SELECT valor FROM paneles 
        WHERE vista = 'Plan de Acción' AND metrica = 'Cobertura stock'
        ORDER BY fecha_calculo DESC LIMIT 1
    """)
    if df.empty or df.iloc[0]['valor'] is None:
        return None
    return float(df.iloc[0]['valor'])

@st.cache_data(ttl=300)
def fetch_mtbf_mttr_12m() -> pd.DataFrame:
    """Serie mensual de MTBF y MTTR de los últimos 12 meses.

    MTTR: media de duración real de las OT correctivas cerradas (horas).
    MTBF: si existe disponibilidad_diaria, usa horas operativas reales del mes
          dividido por nº de correctivas; si no, cae al aproximado 720h/mes.
    """
    usar_disp = check_table_exists("disponibilidad_diaria")

    if usar_disp:
        df = query_db("""
            WITH ot_mes AS (
                SELECT DATE_TRUNC('month', fecha_apertura)::date AS mes,
                       fecha_apertura, fecha_cierre, tipo_ot
                FROM ordenes_trabajo
                WHERE fecha_apertura >= CURRENT_DATE - INTERVAL '12 months'
            ),
            mttr AS (
                SELECT mes,
                       AVG(CASE WHEN fecha_cierre IS NOT NULL
                                 AND LOWER(COALESCE(tipo_ot,'')) IN ('correctiva','correctivo','emergency')
                                THEN EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura)) / 3600.0
                                ELSE NULL END)::numeric(10,2) AS mttr_h,
                       COUNT(*) FILTER (
                           WHERE LOWER(COALESCE(tipo_ot,'')) IN ('correctiva','correctivo','emergency')
                       ) AS n_corr
                FROM ot_mes GROUP BY mes
            ),
            horas AS (
                SELECT DATE_TRUNC('month', fecha)::date AS mes,
                       SUM(COALESCE(horas_operativas,0)) AS h_op
                FROM disponibilidad_diaria
                WHERE fecha >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY DATE_TRUNC('month', fecha)
            )
            SELECT m.mes,
                   m.mttr_h,
                   CASE WHEN m.n_corr > 0 AND h.h_op IS NOT NULL
                        THEN (h.h_op / m.n_corr)::numeric(10,2)
                        ELSE NULL END AS mtbf_h
            FROM mttr m
            LEFT JOIN horas h ON h.mes = m.mes
            ORDER BY m.mes;
        """)
        return df

    # Fallback sin disponibilidad_diaria: MTBF aproximado 720h/mes
    df = query_db("""
        WITH meses AS (
            SELECT DATE_TRUNC('month', fecha_apertura)::date AS mes,
                   fecha_apertura, fecha_cierre, tipo_ot
            FROM ordenes_trabajo
            WHERE fecha_apertura >= CURRENT_DATE - INTERVAL '12 months'
        )
        SELECT
            mes,
            AVG(CASE WHEN fecha_cierre IS NOT NULL
                          AND LOWER(COALESCE(tipo_ot,'')) IN ('correctiva','correctivo','emergency')
                     THEN EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura)) / 3600.0
                     ELSE NULL END)::numeric(10,2) AS mttr_h,
            CASE
                WHEN COUNT(*) FILTER (WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')) > 0
                THEN (720.0 / COUNT(*) FILTER (WHERE LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')))::numeric(10,2)
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

    Si existe disponibilidad_diaria, usa las horas detenido reales (ya calculadas
    desde el intervalo apertura→cierre). Si no, aproxima con la duración de OT.
    """
    if check_table_exists("disponibilidad_diaria"):
        return query_db("""
            SELECT
                DATE_TRUNC('month', fecha)::date AS mes,
                SUM(COALESCE(horas_detenido_planificado, 0))::numeric(10,2) AS planificado_h,
                SUM(COALESCE(horas_detenido_no_planificado, 0))::numeric(10,2) AS no_planificado_h
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '12 months'
            GROUP BY DATE_TRUNC('month', fecha)
            ORDER BY mes;
        """)

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
                    WHEN LOWER(COALESCE(tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')
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
    """Distribución de alertas por resultado de revisión del taller."""
    if not check_table_exists("feedback_taller"):
        return pd.DataFrame()
    return query_db("""
        SELECT
            COALESCE(NULLIF(resultado_revision, ''), 'Sin revisar') AS estado,
            COUNT(*) AS cantidad
        FROM feedback_taller
        GROUP BY resultado_revision;
    """)


@st.cache_data(ttl=300)
def fetch_motivos_rechazo() -> pd.DataFrame:
    """Top motivos por los que el taller marca una alerta como falsa alarma."""
    if not check_table_exists("feedback_taller"):
        return pd.DataFrame()
    return query_db("""
        SELECT
            COALESCE(NULLIF(comentario_mecanico, ''), 'Sin especificar') AS motivo,
            COUNT(*) AS cantidad
        FROM feedback_taller
        WHERE falsa_alarma = TRUE
        GROUP BY comentario_mecanico
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
    with st.sidebar:
        st.markdown("---")
        st.markdown("**Filtros globales**")
        horizonte_label = st.selectbox("Horizonte predictivo", ["7 días", "30 días", "90 días"], index=1)

    horizonte_dias = parse_horizonte(horizonte_label)

    # BANDA SUPERIOR — Hero metrics (todos desde Supabase)
    st.markdown("#### 🎯 Indicadores principales")

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        n_op = fetch_unidades_operativas()
        delta_op = fetch_tendencia_paneles("Estado y Riesgo", "Unidades operativas")
        delta_str = f"{delta_op:+.0f}" if delta_op is not None else None
        st.metric("Unidades operativas", fmt_num(n_op), delta=delta_str)

    with col2:
        disp = fetch_disponibilidad_30d()
        delta_disp = fetch_tendencia_paneles("Estado y Riesgo", "Disponibilidad")
        delta_str = f"{delta_disp:+.1f}pp" if delta_disp is not None else None
        st.metric("Disponibilidad", 
                  fmt_pct(disp) if disp is not None else "Sin datos",
                  delta=delta_str)
        if disp is None:
            st.caption("Requiere disponibilidad_diaria")

    with col3:
        n_p1 = fetch_conteo_prioridad("P1_critica", horizonte_dias=horizonte_dias)
        delta_p1 = fetch_tendencia_paneles("Estado y Riesgo", "P1 Crítica", horizonte_dias=horizonte_dias)
        delta_str = f"{delta_p1:+.0f}" if delta_p1 is not None else None
        # inverse: que SUBA el número de P1 es malo (rojo), que baje es bueno (verde)
        st.metric("P1 crítica", fmt_num(n_p1), delta=delta_str, delta_color="inverse")

    with col4:
        n_p2 = fetch_conteo_prioridad("P2_alta", horizonte_dias=horizonte_dias)
        delta_p2 = fetch_tendencia_paneles("Estado y Riesgo", "P2 Alta", horizonte_dias=horizonte_dias)
        delta_str = f"{delta_p2:+.0f}" if delta_p2 is not None else None
        # inverse: que SUBA el número de P2 es malo (rojo), que baje es bueno (verde)
        st.metric("P2 alta", fmt_num(n_p2), delta=delta_str, delta_color="inverse")

    with col5:
        n_anticipadas = fetch_fallas_anticipadas_30d()
        delta_ant = fetch_tendencia_paneles("Estado y Riesgo", "Fallas anticipadas")
        delta_str = f"{delta_ant:+.0f}" if delta_ant is not None else None
        st.metric("Fallas anticipadas*", fmt_num(n_anticipadas), delta=delta_str)
        st.caption("*últimos 30 días, confirmadas")

    with col6:
        mtbf = fetch_mtbf_horas()
        delta_mtbf = fetch_tendencia_paneles("Estado y Riesgo", "MTBF")
        delta_str = f"{delta_mtbf:+.0f}" if delta_mtbf is not None else None
        st.metric("MTBF (horas)", fmt_num(mtbf, 0) if mtbf is not None else "Sin datos", delta=delta_str)
        if mtbf is None:
            st.caption("Requiere disponibilidad_diaria")

    st.markdown("---")
    # Ranking de unidades en riesgo — DATOS REALES
    st.markdown(f"#### ⚠️ Ranking de unidades en riesgo (Top 15, horizonte {horizonte_label})")

    with st.spinner("⏳ Cargando ranking..."):
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
            "fecha_scoring": "Fecha alerta",
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
        delta_7d = fetch_tendencia_paneles("Plan de Acción", "Intervenciones próximas 7d", horizonte_dias=7)
        delta_str = f"{delta_7d:+.0f}" if delta_7d is not None else None
        # inverse: que SUBAN las intervenciones pendientes es señal de deterioro (rojo)
        st.metric("Próx. 7 días", fmt_num(n_7d), delta=delta_str, delta_color="inverse")

    with col2:
        n_30d = fetch_intervenciones_proximas(30)
        delta_30d = fetch_tendencia_paneles("Plan de Acción", "Intervenciones próximas 30d", horizonte_dias=30)
        delta_str = f"{delta_30d:+.0f}" if delta_30d is not None else None
        st.metric("Próx. 30 días", fmt_num(n_30d), delta=delta_str, delta_color="inverse")

    with col3:
        # SKU en quiebre: lee desde tabla paneles (calculado por calcular_paneles.py)
        df_sku = query_db("""
            SELECT valor FROM paneles 
            WHERE vista = 'Plan de Acción' AND metrica = 'SKU en quiebre'
            ORDER BY fecha_calculo DESC LIMIT 1
        """)
        if not df_sku.empty and df_sku.iloc[0]['valor'] is not None:
            st.metric("SKU en quiebre", fmt_num(int(df_sku.iloc[0]['valor'])))
        else:
            st.metric("SKU en quiebre", "Sin datos")
    with col4:
        cobertura = fetch_valor_paneles("Impacto y Desempeño", "Cobertura stock")
        if cobertura is not None:
            st.metric("Cobertura stock", fmt_pct(cobertura, 1))
        else:
            st.metric("Cobertura stock", "Sin datos")
            st.caption("Requiere repuestos_maestro")

    with col5:
        pm = fetch_cumplimiento_pm()
        delta_pm = fetch_tendencia_paneles("Plan de Acción", "Cumplimiento PM")
        delta_str = f"{delta_pm:+.1f}pp" if delta_pm is not None else None
        st.metric("Cumpl. PM", fmt_pct(pm, 0) if pm is not None else "Sin datos", delta=delta_str)

    with col6:
        backlog = fetch_backlog_ot()
        delta_bl = fetch_tendencia_paneles("Plan de Acción", "Backlog OT")
        delta_str = f"{delta_bl:+.0f}" if delta_bl is not None else None
        # inverse: que SUBA el backlog es malo (rojo), que baje es bueno (verde)
        st.metric("Backlog", f"{fmt_num(backlog)} OT", delta=delta_str, delta_color="inverse")

    st.markdown("---")

    # Tabla de intervenciones recomendadas
    st.markdown("#### 🎯 Intervenciones sugeridas (próximos 30 días)")
    with st.spinner("⏳ Cargando intervenciones..."):
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
        # Costos ya vienen precalculados desde intervenciones_sugeridas
        # Solo formatear para mostrar
        df_intervenciones["Costo estimado"] = df_intervenciones["costo_estimado"].apply(
            lambda x: fmt_clp(x) if x is not None else "Sin datos"
        )
        df_intervenciones["Costo NO intervenir"] = df_intervenciones["costo_no_intervenir"].apply(
            lambda x: fmt_clp(x) if x is not None else "Sin datos"
        )
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

    # Sección de repuestos CRÍTICOS (nuevo panel predictor)
    st.markdown("#### 📦 Repuestos críticos y abastecimiento")
    st.caption("Panel basado en predicción P1/P2 - Demanda proyectada para próximos 30 días")
    
    df_panel = fetch_repuestos_panel_criticos()
    
    if df_panel.empty:
        empty_state(
            "Panel de repuestos predictor aún no disponible. Ejecute: `uv run python 04_demanda_p1p2.py`",
            height=120
        )
    else:
        # Resumen de acciones ANTES de la tabla
        col_urgentes, col_comprar, col_ok = st.columns(3)
        
        n_urgentes = len(df_panel[df_panel["accion"].str.contains("urgente", case=False, na=False)])
        n_comprar = len(df_panel[df_panel["accion"].str.contains("Comprar", case=False, na=False) & 
                                 ~df_panel["accion"].str.contains("urgente", case=False, na=False)])
        n_ok = len(df_panel[df_panel["accion"].str.contains("OK", case=False, na=False)])
        
        with col_urgentes:
            st.metric("🔴 Comprar urgente", n_urgentes, delta_color="inverse")
        with col_comprar:
            st.metric("🟡 Comprar", n_comprar)
        with col_ok:
            st.metric("✅ OK", n_ok)
        
        st.markdown("")
        
        # Ordenar por urgencia: urgente (0) → comprar (1) → ok (2)
        def orden_accion(accion):
            if pd.isna(accion):
                return 999
            accion_str = str(accion).lower()
            if "urgente" in accion_str:
                return 0
            elif "comprar" in accion_str:
                return 1
            else:  # OK
                return 2
        
        df_panel["orden_urgencia"] = df_panel["accion"].apply(orden_accion)
        df_panel_ordenado = df_panel.sort_values("orden_urgencia")
        
        # Mostrar tabla con columnas principales
        display_panel = df_panel_ordenado[[
            "sku", "descripcion", "stock_actual", 
            "demanda_30d_prediccion", "demanda_30d_historico",
            "lead_time_dias", "cobertura_dias", "criticidad", "accion"
        ]].copy()
        
        # Agregar prefijos numéricos a "accion" para que ordene correctamente
        # cuando el usuario hace click en la columna
        def format_accion_ordenable(accion):
            if pd.isna(accion):
                return "3_Desconocido"
            accion_str = str(accion).lower()
            if "urgente" in accion_str:
                return "1_urgente"
            elif "comprar" in accion_str and "urgente" not in accion_str:
                return "2_comprar"
            else:  # OK
                return "3_ok"
        
        # Crear columna de ordenamiento invisible
        display_panel["_sort_accion"] = display_panel["accion"].apply(format_accion_ordenable)
        
        # Crear display limpio (sin números)
        def format_accion_display(accion):
            if pd.isna(accion):
                return "Desconocido"
            accion_str = str(accion).lower()
            if "urgente" in accion_str:
                return "🔴 Comprar urgente"
            elif "comprar" in accion_str and "urgente" not in accion_str:
                return "🟡 Comprar"
            else:  # OK
                return "✅ OK"
        
        display_panel["accion"] = display_panel["accion"].apply(format_accion_display)
        
        # Ordenar por columna invisible
        display_panel = display_panel.sort_values("_sort_accion", ascending=True)
        
        display_panel = display_panel.rename(columns={
            "sku": "SKU",
            "descripcion": "Descripción",
            "stock_actual": "Stock",
            "demanda_30d_prediccion": "Demanda 30d",
            "demanda_30d_historico": "Histórico",
            "lead_time_dias": "Lead time",
            "cobertura_dias": "Cobertura",
            "criticidad": "Criticidad",
            "accion": "Acción"
        })
        
        # Remover columna invisible antes de mostrar
        display_panel = display_panel.drop(columns=["_sort_accion"])
        
        # Formatear números
        for col in ["Stock", "Demanda 30d", "Histórico", "Lead time", "Cobertura"]:
            if col in display_panel.columns:
                display_panel[col] = display_panel[col].apply(
                    lambda x: f"{x:.1f}" if x is not None and x == x else "—"
                )
        
        st.dataframe(display_panel, use_container_width=True, hide_index=True)

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
    st.markdown("### 📊 Impacto y desempeño del modelo")

    st.markdown("#### 💰 Resultados económicos")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        costo_evitado = fetch_costo_evitado_acumulado()
        delta_ce = fetch_tendencia_paneles("Impacto y Desempeño", "Costo evitado")
        delta_str = (f"+{fmt_clp(delta_ce)}" if delta_ce >= 0 else f"-{fmt_clp(abs(delta_ce))}") if delta_ce is not None else None
        st.metric("Costo evitado acumulado", fmt_clp(costo_evitado), delta=delta_str)
        st.caption("*(solo alertas confirmadas)*" if costo_evitado is not None else "Requiere feedback_taller")

    with col2:
        downtime_evitado = fetch_downtime_evitado_horas()
        delta_dt = fetch_tendencia_paneles("Impacto y Desempeño", "Downtime evitado")
        delta_str = f"{delta_dt:+.0f} h" if delta_dt is not None else None
        st.metric(
            "Downtime evitado",
            f"{fmt_num(downtime_evitado, 0)} horas" if downtime_evitado is not None else "Sin datos",
            delta=delta_str
        )
        st.caption("*(MTTR promedio × alertas)*" if downtime_evitado is not None else "Requiere feedback_taller")

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

    st.markdown("#### 📈 Productividad y eficiencia de flota")
    col_prod1, col_prod2 = st.columns(2)

    with col_prod1:
        st.markdown("**MTBF, MTTR, Disponibilidad — últimos 12 meses**")
        with st.spinner("⏳ Cargando gráfico MTBF/MTTR..."):
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
        with st.spinner("⏳ Cargando gráfico downtime..."):
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

    st.markdown("---")

    st.markdown("#### 🔄 Comparación antes/después del modelo")

    tiempo_uso = fetch_tiempo_uso_meses()
    if tiempo_uso < 6:
        st.info(
            f"⏳ Esta métrica se activará en el **mes 6** de uso. "
            f"Actualmente en mes {tiempo_uso:.0f}. "
            f"Se necesita ≥6 meses de datos en producción para una comparación válida."
        )
    else:
        empty_state(
            "Comparación antes/después: requiere implementación del cálculo "
            "(período previo vs período con modelo activo).",
            height=120
        )

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

            if recall is not None and not pd.isna(recall):
                st.write(f"**De cada 10 fallas, alertamos:** {float(recall)*10:.1f} con anticipación (Recall)")
            else:
                st.write("**De cada 10 fallas, alertamos:** Sin datos (no hay test set evaluable)")

            if precision is not None and not pd.isna(precision):
                st.write(f"**De cada 10 alertas, eran correctas:** {float(precision)*10:.1f} (Precision)")
            else:
                st.write("**De cada 10 alertas, eran correctas:** Sin datos")

            if check_table_exists("feedback_taller"):
                df_ant = query_db("""
                    SELECT AVG(
                        EXTRACT(DAY FROM (
                            (SELECT MIN(fecha_apertura)
                             FROM ordenes_trabajo o
                             WHERE o.activo_id = f.activo_id
                               AND o.fecha_apertura >= f.fecha_alerta
                               AND LOWER(COALESCE(o.tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')
                            ) - f.fecha_alerta::timestamp
                        ))
                    ) AS dias_promedio
                    FROM feedback_taller f
                    WHERE f.falla_confirmada = TRUE;
                """)
                if not df_ant.empty and df_ant.iloc[0]["dias_promedio"] is not None:
                    st.write(f"**Anticipación promedio:** {float(df_ant.iloc[0]['dias_promedio']):.0f} días antes de falla")
                else:
                    st.write("**Anticipación promedio:** Sin datos suficientes")
            else:
                st.write("**Anticipación promedio:** Sin datos (requiere feedback_taller)")

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
        if not check_table_exists("feedback_taller"):
            empty_state(
                "Requiere feedback_taller para construir la matriz real "
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
                           CASE WHEN falla_confirmada THEN 1 ELSE 0 END AS hubo_falla
                    FROM feedback_taller
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

    if metricas_modelo:
        version = metricas_modelo.get("version", "desconocido")
        st.markdown(f"**Estado del modelo:** 🟢 Activo — versión `{version}`")
    else:
        st.markdown("**Estado del modelo:** 🔴 Sin modelo activo registrado")

    st.markdown("---")

    st.markdown("#### 📝 Feedback del taller y ciclo de aprendizaje")
    col_fb1, col_fb2 = st.columns(2)

    with col_fb1:
        st.markdown("**Alertas por estado**")
        df_fb_est = fetch_feedback_estados()
        if df_fb_est.empty:
            empty_state(
                "Sin feedback registrado todavía. "
                "Activar tabla feedback_taller y comenzar captura desde el taller.",
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

    st.markdown("---")

    st.markdown("#### 💼 ROI y retorno de inversión")

    tiempo_uso = fetch_tiempo_uso_meses()
    if tiempo_uso < 6:
        st.info(
            f"⏳ **ROI y payback se activan en mes 6.** "
            f"Actualmente en mes {tiempo_uso:.0f}. "
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
    # Crear layout compacto: título y logo en la misma fila, sin espacio extra
    st.markdown("<style>.block-container { padding-top: 1rem; padding-bottom: 0rem; } .css-1y4p5pa { padding: 0rem; }</style>", unsafe_allow_html=True)
    
    col_title, col_logo = st.columns([4, 1])

    with col_title:
        st.title("📊 BAITECK — Dashboard Predictivo de Flotas")
        st.markdown("Versión 1.0 — Diseño operativo y comercial")

    with col_logo:
        # Logo en esquina superior derecha
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
        - Base de datos: {status_conexion}
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
