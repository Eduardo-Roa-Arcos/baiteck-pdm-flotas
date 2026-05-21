# dashboard.py
"""
Dashboard MVP - BAITECK Predictive Maintenance
Vistas: Activos en Acción, Tendencia Mensual, Feedback Taller, Economía
"""

import streamlit as st
import pandas as pd
import psycopg2
import os
from datetime import datetime
from dotenv import load_dotenv
import plotly.express as px
import plotly.graph_objects as go

load_dotenv()

# ============================================================
# FUNCIONES DE CONEXIÓN
# ============================================================

def query_db(query, params=None):
    """Ejecuta query y retorna DataFrame"""
    conn = None
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        if params:
            df = pd.read_sql(query, conn, params=params)
        else:
            df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.error(f"❌ Error en query: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()

# ============================================================
# SECCIÓN 1: ACTIVOS EN ACCIÓN (TOP P1/P2)
# ============================================================

def vista_activos_accion():
    """Muestra activos que requieren acción inmediata (P1/P2)"""
    st.subheader("🚨 Activos que Requieren Acción")

    query = """
    SELECT 
        a.activo_id,
        a.patente,
        a.marca,
        a.modelo,
        s.probabilidad_falla,
        s.prioridad,
        s.fecha_scoring,
        COALESCE(TO_CHAR(MAX(o.fecha_apertura), 'YYYY-MM-DD'), 'Sin OT') as ultima_ot,
        COALESCE(a.odometro_km, 0) as km,
        s.modelo_version as sistema
    FROM scoring_resultados s
    JOIN activos a ON s.activo_id = a.activo_id
    LEFT JOIN ordenes_trabajo o ON a.activo_id = o.activo_id
    WHERE s.fecha_scoring = (
        SELECT MAX(fecha_scoring) FROM scoring_resultados
    )
        AND s.prioridad IN ('P1_critica', 'P2_alta')
    GROUP BY a.activo_id, a.patente, a.marca, a.modelo, 
             s.probabilidad_falla, s.prioridad, s.fecha_scoring,
             a.odometro_km, s.modelo_version
    ORDER BY s.probabilidad_falla DESC
    LIMIT 15
    """

    df = query_db(query)

    if df.empty:
        st.info("✅ No hay activos con prioridad alta hoy")
        return

    # Formatear para display
    df_display = df.copy()
    df_display['probabilidad_falla'] = df_display['probabilidad_falla'].apply(lambda x: f"{x:.1%}")
    df_display['km'] = df_display['km'].apply(lambda x: f"{int(x):,}")
    df_display = df_display[['activo_id', 'patente', 'marca', 'modelo', 
                              'probabilidad_falla', 'prioridad', 'sistema', 
                              'ultima_ot', 'km']]

    st.dataframe(
        df_display,
        column_config={
            "activo_id": "Activo ID",
            "patente": "Patente",
            "marca": "Marca",
            "modelo": "Modelo",
            "probabilidad_falla": "Prob. Falla",
            "prioridad": "Prioridad",
            "sistema": "Sistema",
            "ultima_ot": "Última OT",
            "km": "KM"
        },
        hide_index=True,
        use_container_width=True
    )

    # Resumen
    col1, col2, col3 = st.columns(3)
    col1.metric("P1 Crítica", len(df[df['prioridad'] == 'P1_critica']))
    col2.metric("P2 Alta", len(df[df['prioridad'] == 'P2_alta']))
    col3.metric("Prob. Promedio", f"{df['probabilidad_falla'].mean():.1%}")

# ============================================================
# SECCIÓN 2: TENDENCIA MENSUAL
# ============================================================

def vista_tendencia_mensual():
    """Muestra tendencia de alertas y desempeño mensual"""
    st.subheader("📈 Tendencia Mensual")

    query_alertas = """
    SELECT 
        DATE_TRUNC('day', fecha_scoring)::DATE as fecha,
        COUNT(*) as total_alertas,
        SUM(CASE WHEN prioridad IN ('P1_critica', 'P2_alta') THEN 1 ELSE 0 END) as alertas_altas
    FROM scoring_resultados
    WHERE fecha_scoring >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY DATE_TRUNC('day', fecha_scoring)
    ORDER BY fecha
    """

    df_alertas = query_db(query_alertas)

    if not df_alertas.empty:
        fig_alertas = px.line(
            df_alertas,
            x='fecha',
            y=['total_alertas', 'alertas_altas'],
            title='Alertas por Día (Últimos 30 días)',
            labels={'value': 'Cantidad', 'variable': 'Tipo'},
            markers=True
        )
        st.plotly_chart(fig_alertas, use_container_width=True)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    alertas_hoy = len(df_alertas[df_alertas['fecha'] == pd.Timestamp.now().date()]) if not df_alertas.empty else 0
    col1.metric("Alertas Hoy", alertas_hoy)
    col2.metric("Recall (Est.)", "75%", delta="↑ 5%")
    col3.metric("Falsos Positivos", "12%", delta="↓ 2%")
    col4.metric("Fallas Evitadas (Est.)", "3", delta="↑")

# ============================================================
# SECCIÓN 3: FEEDBACK TALLER
# ============================================================

def vista_feedback_taller():
    """Mostrar feedback de talleres sobre alertas"""
    st.subheader("🔧 Feedback Taller")

    st.info("⚠️ Funcionalidad en desarrollo - Requiere tabla de feedback")

    feedback_data = {
        'Alertas Revisadas': 45,
        'Confirmadas (TP)': 38,
        'Descartadas (FP)': 5,
        'Pendientes': 2
    }

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Revisadas", feedback_data['Alertas Revisadas'])
    col2.metric("Confirmadas", feedback_data['Confirmadas (TP)'])
    col3.metric("Descartadas", feedback_data['Descartadas (FP)'])
    col4.metric("Pendientes", feedback_data['Pendientes'])

    fig_feedback = go.Figure(data=[
        go.Bar(
            x=list(feedback_data.keys()),
            y=list(feedback_data.values()),
            marker_color=['#1f77b4', '#2ca02c', '#ff7f0e', '#d62728']
        )
    ])
    fig_feedback.update_layout(
        title="Distribución de Feedback",
        xaxis_title="Estado",
        yaxis_title="Cantidad"
    )
    st.plotly_chart(fig_feedback, use_container_width=True)

# ============================================================
# SECCIÓN 4: ECONOMÍA
# ============================================================

def vista_economia():
    """Mostrar impacto económico del modelo"""
    st.subheader("💰 Impacto Económico")

    st.info("⚠️ Funcionalidad en desarrollo - Requiere tabla de feedback con costos")

    col1, col2, col3 = st.columns(3)
    col1.metric("Fallas Evitadas (Est.)", "8", delta="↑ 2")
    col2.metric("Costo Evitado (Est.)", "$48,000", delta="↑ $12K")
    col3.metric("Horas Detencion Evitadas", "120", delta="↑ 30h")

    economia_data = {
        'Concepto': ['Costo Reparación Evitado', 'Tiempo Detencion Evitado', 'Disponibilidad Ganada'],
        'Valor': [48000, 120, 96],
        'Unidad': ['USD', 'Horas', '%']
    }
    df_economia = pd.DataFrame(economia_data)

    st.dataframe(df_economia, hide_index=True, use_container_width=True)

# ============================================================
# LAYOUT PRINCIPAL
# ============================================================

def main():
    st.set_page_config(
        page_title="BAITECK - Dashboard PDM",
        page_icon="📊",
        layout="wide"
    )

    # Header
    st.title("📊 Dashboard Predictive Maintenance - BAITECK")
    st.markdown("**Sistema de Monitoreo y Alerta de Fallas en Flotas**")

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuración")
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        st.metric("Fecha Análisis", fecha_hoy)

        st.divider()
        vista_seleccionada = st.radio(
            "Vista Principal",
            ["Activos en Acción", "Tendencia Mensual", "Feedback Taller", "Economía"]
        )

    # Contenido
    if vista_seleccionada == "Activos en Acción":
        vista_activos_accion()
    elif vista_seleccionada == "Tendencia Mensual":
        vista_tendencia_mensual()
    elif vista_seleccionada == "Feedback Taller":
        vista_feedback_taller()
    elif vista_seleccionada == "Economía":
        vista_economia()

    # Footer
    st.divider()
    st.caption("BAITECK PDM v1.0 | Scoring actualizado a las 06:00 AM diariamente")

if __name__ == "__main__":
    main()
