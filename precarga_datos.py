"""
PRECARGA DE DATOS — Carga inteligente en background mientras usuario se autentica
===================================================================================

Objetivo:
  Mientras el usuario está ingresando credenciales en el panel de login,
  el sistema carga todos los datos necesarios para las 3 vistas.
  
  Resultado: Al ingresar exitosamente, el dashboard ya tiene todos los datos
  en cache (memoria) → display INSTANTÁNEO, sin esperas.

Estrategia:
  1. Cache con @st.cache_data (TTL inteligente)
  2. Precarga en orden de importancia
  3. Manejo de errores silencioso (BD no disponible ≠ dashboard cae)
  4. Funciones de lectura rápidas y eficientes

Funciones principales:
  - iniciar_precarga_background() → dispara precarga (llamar en panel login)
  - get_paneles_cached() → devuelve paneles (o [] si no está disponible)
  - get_scoring_resultados_cached() → devuelve scoring
  - get_repuestos_panel_criticos_cached() → devuelve repuestos P1/P2
  - get_disponibilidad_diaria_cached() → devuelve disponibilidad
  - get_feedback_taller_cached() → devuelve feedback (si existe tabla)

Uso en dashboard:
  from precarga_datos import iniciar_precarga_background, get_paneles_cached
  
  # En panel de login:
  iniciar_precarga_background()
  
  # En cualquier lugar del dashboard:
  paneles = get_paneles_cached()
  if not paneles:
      st.warning("No hay datos disponibles")
  else:
      st.dataframe(paneles)

Autor: BAITECK — junio 2026
"""

import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
import threading
import logging

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL")

# TTL (Time To Live) de cache en segundos
CACHE_TTL_PANELES = 300  # 5 minutos
CACHE_TTL_SCORING = 300  # 5 minutos
CACHE_TTL_REPUESTOS = 600  # 10 minutos
CACHE_TTL_DISPONIBILIDAD = 900  # 15 minutos
CACHE_TTL_FEEDBACK = 900  # 15 minutos


def get_db_connection():
    """Retorna conexión a Supabase PostgreSQL."""
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            connect_timeout=5,
            options="-c statement_timeout=15000"
        )
        return conn
    except psycopg2.Error as e:
        logger.warning(f"No se pudo conectar a BD: {e}")
        return None


# ============================================================================
# FUNCIONES DE LECTURA DE DATOS (base, sin cache)
# ============================================================================

def _query_paneles_base() -> List[Dict]:
    """
    Lectura base: tabla paneles completa.
    
    Devuelve:
      Lista de dicts con todos los registros de paneles.
      [] si no hay datos o hay error.
    """
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT 
                panel_id, vista, metrica, valor, valor_anterior,
                fecha_calculo, horizonte_dias, nota, periodo_mes,
                delta_color, fuente_sql
            FROM paneles
            WHERE fecha_calculo >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY fecha_calculo DESC
            LIMIT 10000
            """
        )
        registros = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in registros]
    except psycopg2.Error as e:
        logger.warning(f"Error al leer paneles: {e}")
        return []
    finally:
        if conn:
            conn.close()


def _query_scoring_resultados_base() -> List[Dict]:
    """
    Lectura base: tabla scoring_resultados.
    
    Devuelve:
      Lista de dicts con scoring de activos.
      [] si no hay datos o hay error.
    """
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT 
                activo_id, activo_nombre, prob_h7, prob_h30, prob_h90,
                prioridad_h7, prioridad_h30, prioridad_h90,
                fecha_scoring
            FROM scoring_resultados
            WHERE UPPER(COALESCE(estado_actual, 'Activo')) = 'ACTIVO'
            ORDER BY fecha_scoring DESC
            LIMIT 5000
            """
        )
        registros = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in registros]
    except psycopg2.Error as e:
        logger.warning(f"Error al leer scoring_resultados: {e}")
        return []
    finally:
        if conn:
            conn.close()


def _query_repuestos_panel_criticos_base() -> List[Dict]:
    """
    Lectura base: tabla repuestos_panel_criticos (P1/P2).
    
    Devuelve:
      Lista de dicts con demanda de repuestos críticos.
      [] si no hay datos o hay error.
    """
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT 
                id, activo_id, activo_nombre, sistema, sku, 
                descripcion, demanda_p1, demanda_p2, demanda_total,
                fecha_calculo
            FROM repuestos_panel_criticos
            ORDER BY fecha_calculo DESC
            LIMIT 5000
            """
        )
        registros = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in registros]
    except psycopg2.Error as e:
        logger.warning(f"Error al leer repuestos_panel_criticos: {e}")
        return []
    finally:
        if conn:
            conn.close()


def _query_disponibilidad_diaria_base() -> List[Dict]:
    """
    Lectura base: tabla disponibilidad_diaria.
    
    Devuelve:
      Lista de dicts con disponibilidad por activo y día.
      [] si no hay datos o hay error.
    """
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT 
                activo_id, activo_nombre, fecha, disponibilidad_pct,
                horas_disponibles, horas_total, motivo_indisponibilidad
            FROM disponibilidad_diaria
            WHERE fecha >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY fecha DESC
            LIMIT 10000
            """
        )
        registros = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in registros]
    except psycopg2.Error as e:
        logger.warning(f"Error al leer disponibilidad_diaria: {e}")
        return []
    finally:
        if conn:
            conn.close()


def _query_feedback_taller_base() -> List[Dict]:
    """
    Lectura base: tabla feedback_taller (si existe).
    
    Devuelve:
      Lista de dicts con feedback económico.
      [] si no hay datos, tabla no existe, o hay error.
    """
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT 
                id, activo_id, activo_nombre, ot_id, costo_evitado,
                downtime_evitado_horas, fecha_feedback
            FROM feedback_taller
            ORDER BY fecha_feedback DESC
            LIMIT 5000
            """
        )
        registros = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in registros]
    except psycopg2.Error as e:
        # Silencio si la tabla no existe (es esperado)
        logger.debug(f"feedback_taller no disponible: {e}")
        return []
    finally:
        if conn:
            conn.close()


# ============================================================================
# FUNCIONES CON CACHE (Streamlit @cache_data)
# ============================================================================

@st.cache_data(ttl=CACHE_TTL_PANELES)
def get_paneles_cached() -> List[Dict]:
    """Retorna paneles con cache de 5 min."""
    logger.info("📊 Cargando paneles...")
    return _query_paneles_base()


@st.cache_data(ttl=CACHE_TTL_SCORING)
def get_scoring_resultados_cached() -> List[Dict]:
    """Retorna scoring con cache de 5 min."""
    logger.info("🎯 Cargando scoring_resultados...")
    return _query_scoring_resultados_base()


@st.cache_data(ttl=CACHE_TTL_REPUESTOS)
def get_repuestos_panel_criticos_cached() -> List[Dict]:
    """Retorna repuestos P1/P2 con cache de 10 min."""
    logger.info("🔧 Cargando repuestos_panel_criticos...")
    return _query_repuestos_panel_criticos_base()


@st.cache_data(ttl=CACHE_TTL_DISPONIBILIDAD)
def get_disponibilidad_diaria_cached() -> List[Dict]:
    """Retorna disponibilidad con cache de 15 min."""
    logger.info("📅 Cargando disponibilidad_diaria...")
    return _query_disponibilidad_diaria_base()


@st.cache_data(ttl=CACHE_TTL_FEEDBACK)
def get_feedback_taller_cached() -> List[Dict]:
    """Retorna feedback con cache de 15 min."""
    logger.info("💰 Cargando feedback_taller...")
    return _query_feedback_taller_cached()


# ============================================================================
# PRECARGA EN BACKGROUND
# ============================================================================

def _precarga_thread():
    """
    Función que ejecuta la precarga en thread separado.
    No bloquea la UI, solo carga datos en cache.
    """
    logger.info("🚀 Precarga iniciada en background...")
    
    try:
        # ORDEN DE CARGA (por importancia):
        # 1. Paneles (crítico para Vista 1)
        get_paneles_cached()
        
        # 2. Scoring (crítico para Vista 1)
        get_scoring_resultados_cached()
        
        # 3. Repuestos (crítico para Vista 2)
        get_repuestos_panel_criticos_cached()
        
        # 4. Disponibilidad (Vista 3)
        get_disponibilidad_diaria_cached()
        
        # 5. Feedback (Vista 3, optional)
        get_feedback_taller_cached()
        
        logger.info("✅ Precarga completada")
    
    except Exception as e:
        logger.error(f"❌ Error en precarga: {e}")


def iniciar_precarga_background():
    """
    Dispara la precarga en thread separado.
    NO bloquea la UI.
    
    USAR EN:
      - Panel de login (después de render_login_panel())
      - O cualquier lugar donde quieras forzar precarga
    
    Ejemplo:
      from precarga_datos import iniciar_precarga_background
      
      iniciar_precarga_background()
      render_login_panel()
    """
    # Evitar múltiples threads de precarga simultáneos
    if st.session_state.get("precarga_iniciada", False):
        return
    
    st.session_state.precarga_iniciada = True
    
    # Lanzar thread de precarga (daemon, no bloquea)
    thread = threading.Thread(target=_precarga_thread, daemon=True)
    thread.start()
    
    logger.info("🔄 Thread de precarga iniciado (background)")


# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def limpiar_cache():
    """
    Limpia todo el cache de datos.
    Útil para testing o forzar recarga completa.
    """
    st.cache_data.clear()
    if "precarga_iniciada" in st.session_state:
        del st.session_state.precarga_iniciada
    logger.info("🧹 Cache limpiado")


def status_cache() -> Dict[str, str]:
    """
    Retorna status actual del cache (para debugging).
    
    Devuelve:
      Dict con True/False para cada tabla
    """
    return {
        "paneles": "✅" if get_paneles_cached() else "⏳",
        "scoring": "✅" if get_scoring_resultados_cached() else "⏳",
        "repuestos": "✅" if get_repuestos_panel_criticos_cached() else "⏳",
        "disponibilidad": "✅" if get_disponibilidad_diaria_cached() else "⏳",
        "feedback": "✅" if get_feedback_taller_cached() else "⏳",
    }
