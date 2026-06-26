"""
AUTENTICACIÓN v2 — Simplificada y optimizada para velocidad
============================================================

Filosofía:
  - Sin roles (solo: ¿autorizado sí/no?)
  - Verificación ultra-rápida
  - Integración mínima con dashboard
  - Sin botón de logout separado (logout integrado en sidebar del dashboard)

Funciones:
  - autenticar_usuario() → verifica email+password en BD
  - get_usuario_autenticado() → obtiene de session_state
  - logout() → limpia sesión
  - render_login_panel() → panel minimalista de login

Uso:
  from autenticacion_v2 import render_login_panel, get_usuario_autenticado
  
  usuario = get_usuario_autenticado()
  if not usuario:
      render_login_panel()
      st.stop()
  
  # Usuario autenticado → continuar con dashboard

Autor: BAITECK — junio 2026
"""

import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
from datetime import datetime
from typing import Optional, Dict

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db_connection():
    """Retorna conexión a Supabase PostgreSQL con timeout."""
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            connect_timeout=10,
            options="-c statement_timeout=30000"
        )
        return conn
    except psycopg2.Error as e:
        return None


# ============================================================================
# FUNCIONES DE AUTENTICACIÓN
# ============================================================================

def verificar_contraseña(contraseña_ingresada: str, hash_almacenado: str) -> bool:
    """Verifica si una contraseña coincide con su hash bcrypt."""
    try:
        return bcrypt.checkpw(
            contraseña_ingresada.encode('utf-8'),
            hash_almacenado.encode('utf-8')
        )
    except Exception:
        return False


def obtener_usuario_por_email(email: str) -> Optional[Dict]:
    """Consulta la tabla usuarios por email. Solo usuarios activos."""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT usuario_id, nombre, email, estado, contraseña_hash
            FROM usuarios
            WHERE email = %s AND estado = 'activo'
            LIMIT 1
            """,
            (email,)
        )
        usuario = cursor.fetchone()
        cursor.close()
        return dict(usuario) if usuario else None
    except psycopg2.Error:
        return None
    finally:
        if conn:
            conn.close()


def actualizar_ultimo_acceso(usuario_id: str):
    """Actualiza timestamp de último acceso en BD (fire & forget, no bloquea)."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE usuarios SET updated_at = NOW() WHERE usuario_id = %s",
                (usuario_id,)
            )
            conn.commit()
            cursor.close()
        except psycopg2.Error:
            pass
        finally:
            conn.close()


# ============================================================================
# GESTIÓN DE SESIÓN
# ============================================================================

def get_usuario_autenticado() -> Optional[Dict]:
    """Retorna usuario autenticado desde session_state."""
    return st.session_state.get("usuario_autenticado", None)


def autenticar_usuario(email: str, contraseña: str) -> Optional[Dict]:
    """
    Autentica usuario. Retorna dict con datos si es exitoso, None si falla.
    
    Proceso:
      1. Obtiene usuario por email
      2. Verifica contraseña contra hash
      3. Actualiza último acceso en BD (async)
      4. Guarda en session_state
      5. Retorna datos del usuario
    """
    usuario = obtener_usuario_por_email(email)
    
    if not usuario or not usuario.get("contraseña_hash"):
        return None
    
    if not verificar_contraseña(contraseña, usuario["contraseña_hash"]):
        return None
    
    # Autenticación exitosa
    usuario_sesion = {
        "usuario_id": str(usuario["usuario_id"]),
        "nombre": usuario["nombre"],
        "email": usuario["email"],
        "authenticated_at": datetime.now().isoformat()
    }
    
    # Guardar en session_state
    st.session_state.usuario_autenticado = usuario_sesion
    
    # Actualizar acceso en BD (no bloquea)
    actualizar_ultimo_acceso(usuario["usuario_id"])
    
    return usuario_sesion


def logout():
    """Limpia sesión del usuario."""
    if "usuario_autenticado" in st.session_state:
        del st.session_state.usuario_autenticado
    st.rerun()


# ============================================================================
# INTERFAZ DE LOGIN (MINIMALISTA)
# ============================================================================

def render_login_panel():
    """
    Renderiza panel de login minimalista y profesional.
    
    Diseño:
      - Centrado en pantalla
      - Gradiente de fondo
      - Campos de email/password
      - Botón de ingresar
      - Manejo claro de errores
    """
    
    # CSS minimalista
    st.markdown("""
    <style>
    .login-card {
        max-width: 420px;
        margin: 80px auto 0;
        padding: 50px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        box-shadow: 0 15px 35px rgba(0, 0, 0, 0.25);
        color: white;
    }
    .login-title {
        font-size: 32px;
        font-weight: 700;
        text-align: center;
        margin: 0 0 8px 0;
    }
    .login-subtitle {
        font-size: 14px;
        text-align: center;
        opacity: 0.9;
        margin-bottom: 30px;
    }
    .login-error {
        background-color: #f8d7da;
        color: #721c24;
        padding: 12px 15px;
        border-radius: 6px;
        margin-bottom: 20px;
        border-left: 4px solid #f5c6cb;
        font-size: 13px;
    }
    .login-button {
        width: 100%;
        padding: 12px;
        font-size: 15px;
        font-weight: 600;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Layout
    col_left, col_main, col_right = st.columns([1, 1.2, 1])
    
    with col_main:
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        
        st.markdown('<div class="login-title">🔐 BAITECK</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="login-subtitle">Dashboard Predictivo de Flotas</div>',
            unsafe_allow_html=True
        )
        
        # Mostrar error previo si existe
        if st.session_state.get("login_error"):
            st.markdown(
                f'<div class="login-error">❌ {st.session_state.login_error}</div>',
                unsafe_allow_html=True
            )
            st.session_state.login_error = None
        
        # Campos de login
        email = st.text_input(
            "Email",
            key="login_email",
            placeholder="usuario@empresa.com"
        )
        
        password = st.text_input(
            "Contraseña",
            type="password",
            key="login_password",
            placeholder="••••••••"
        )
        
        # Botón de ingresar
        if st.button("🚀 Ingresar", use_container_width=True, type="primary"):
            if not email or not password:
                st.session_state.login_error = "Completa email y contraseña"
                st.rerun()
            
            usuario = autenticar_usuario(email, password)
            
            if usuario:
                st.success(f"✅ Bienvenido, {usuario['nombre']}!")
                st.balloons()
                st.rerun()
            else:
                st.session_state.login_error = "Email o contraseña incorrectos"
                st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Footer
        st.markdown(
            "<div style='text-align: center; color: #999; font-size: 11px; margin-top: 30px;'>"
            "BAITECK © 2026 — Inteligencia operacional predictiva para flotas"
            "</div>",
            unsafe_allow_html=True
        )


def render_logout_button_en_sidebar():
    """
    Renderiza nombre del usuario y botón de logout en el sidebar.
    (Llama esto una sola vez, al inicio del sidebar en dashboard.py)
    """
    usuario = get_usuario_autenticado()
    if not usuario:
        return
    
    with st.sidebar:
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"👤 {usuario['nombre']}")
            st.caption(usuario['email'], help="Tu cuenta")
        with col2:
            if st.button("🚪", help="Cerrar sesión", use_container_width=True):
                logout()
        st.divider()
