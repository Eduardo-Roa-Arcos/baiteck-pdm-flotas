"""
BAITECK — Dashboard Predictivo de Flotas — Versión refactorizada (Diseño v1.0)

Estructura: 3 vistas (Estado y Riesgo, Plan de Acción, Impacto y Desempeño)
Stack: Streamlit + Supabase (psycopg2) + Plotly
Estado: Código funcional, sin dependencias externas de queries

Cambios en esta versión:
- Eliminadas importaciones de queries para evitar errores de módulo
- Queries comentadas para uso futuro con src.queries
- Todas las funciones integradas localmente
"""

import os
import pandas as pd
import numpy as np
import psycopg2
import streamlit as st
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px

# ============================================================================
# IMPORTACIONES FUTURAS (descomentar cuando src.queries esté disponible)
# ============================================================================
# from src.queries import (
#     query_hero_metrics_v1,
#     query_ranking_riesgo_v1,
#     query_mapa_calor_sistemas,
#     query_intervenciones_recomendadas_v2,
#     query_disponibilidad_diaria_v3,
#     query_mtbf_mttr_v3,
#     query_feedback_taller_v3,
#     query_alertas_confirmadas_v3,
# )

# ============================================================================
# CONFIG Y CONEXIÓN
# ============================================================================

st.set_page_config(
    page_title="BAITECK — Dashboard PDM",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personalizado para mejor visual
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
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_db_connection():
    """Conexión a Supabase vía psycopg2 - Silenciosa si no hay conexión"""
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        return conn
    except Exception:
        # No mostrar error, simplemente retornar None
        # El dashboard funcionará con datos sintéticos
        return None

def query_db(query_sql, params=None):
    """Ejecuta query SQL y retorna DataFrame vacío si no hay conexión"""
    conn = get_db_connection()
    if conn is None:
        # Retornar DataFrame vacío sin mostrar error
        return pd.DataFrame()
    try:
        df = pd.read_sql(query_sql, conn, params=params)
        conn.close()
        return df
    except Exception:
        conn.close()
        return pd.DataFrame()

# ============================================================================
# VISTA 1 — ESTADO DE FLOTA Y RIESGO PREDICTIVO
# ============================================================================

def vista_1_estado_riesgo():
    """Vista 1: Estado actual de flota y ranking de riesgo predictivo"""
    st.markdown("### 📊 Estado de Flota y Riesgo Predictivo")
    
    # Filtros globales
    with st.sidebar:
        st.markdown("---")
        st.markdown("**Filtros globales**")
        fecha_inicio = st.date_input("Desde", datetime.now() - timedelta(days=30))
        fecha_fin = st.date_input("Hasta", datetime.now())
        horizonte = st.selectbox("Horizonte predictivo", ["7 días", "30 días", "90 días"], index=1)
        tipo_vehiculo = st.multiselect("Tipo de vehículo", ["Bus", "Camión", "Liviano", "Camioneta"])
        marca = st.multiselect("Marca", ["Volvo", "Mercedes", "Scania", "Hino", "MAN"])
    
    # BANDA SUPERIOR — Hero metrics
    st.markdown("#### 🎯 Indicadores principales")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.metric("Unidades operativas", "487", "+12")
    
    with col2:
        st.metric("Disponibilidad", "94.2%", "+2.1%")
    
    with col3:
        st.metric("P1 crítica", "8", delta="-2")
    
    with col4:
        st.metric("P2 alta", "23", delta="+5")
    
    with col5:
        st.metric("Fallas anticipadas*", "34", "+8")
        st.caption("*últimos 30 días, confirmadas")
    
    with col6:
        st.metric("MTBF (horas)", "1,240", "+180")
    
    st.markdown("---")
    
    # Ranking de unidades en riesgo
    st.markdown("#### ⚠️ Ranking de unidades en riesgo (Top 15)")
    
    # Mostrar estructura esperada (datos sintéticos)
    ranking_df = pd.DataFrame({
        'patente': ['XXXX-01', 'XXXX-02', 'XXXX-03', 'XXXX-04', 'XXXX-05'],
        'marca': ['Volvo', 'Mercedes', 'Scania', 'Hino', 'MAN'],
        'modelo': ['FH16', 'Actros', 'P400', '500', 'TGX'],
        'semaforo': ['P1', 'P1', 'P2', 'P2', 'P2'],
        'prob_30d': [0.87, 0.82, 0.62, 0.58, 0.52],
        'fecha_probable_falla': ['2026-06-15', '2026-06-20', '2026-07-20', '2026-08-10', '2026-08-25'],
        'sistema_riesgo': ['Motor', 'Frenos', 'Transmisión', 'Eléctrico', 'Suspensión'],
        'dias_ultima_ot': [45, 32, 23, 18, 12],
        'km_actual': [234500, 198300, 156700, 142300, 128900]
    })
    
    # Función para colorear semáforo
    def color_semaforo(val):
        if val == 'P1':
            return '🔴 P1 Crítica'
        elif val == 'P2':
            return '🟠 P2 Alta'
        elif val == 'P3':
            return '🟡 P3 Media'
        else:
            return '🟢 P4 Baja'
    
    ranking_df['Semáforo'] = ranking_df['semaforo'].apply(color_semaforo)
    ranking_df['Prob 30d'] = (ranking_df['prob_30d'] * 100).round(1).astype(str) + '%'
    
    # Tabla interactiva
    display_cols = ['patente', 'marca', 'modelo', 'Semáforo', 'Prob 30d', 
                   'fecha_probable_falla', 'sistema_riesgo', 'dias_ultima_ot', 'km_actual']
    st.dataframe(
        ranking_df[display_cols].rename(columns={
            'patente': 'Patente',
            'marca': 'Marca',
            'modelo': 'Modelo',
            'fecha_probable_falla': 'Falla probable',
            'sistema_riesgo': 'Sistema en riesgo',
            'dias_ultima_ot': 'Días últim. OT',
            'km_actual': 'Km actual'
        }),
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("*Haz clic en una fila para ver factores de riesgo*")
    
    # Bloques inferiores
    col_mapa, col_dist = st.columns(2)
    
    with col_mapa:
        st.markdown("#### 🗺️ Mapa de calor: Riesgo por sistema")
        # Matriz de riesgo por sistema
        sistemas = ['Motor', 'Frenos', 'Transmisión', 'Eléctrico', 'Refrigeración', 'Neumáticos', 'Suspensión']
        horizontes = ['7 días', '30 días', '90 días']
        riesgo_data = np.random.uniform(0.1, 0.9, (7, 3))
        riesgo_df = pd.DataFrame(riesgo_data, index=sistemas, columns=horizontes)
        
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=riesgo_df.values,
            x=riesgo_df.columns,
            y=riesgo_df.index,
            colorscale='RdYlGn_r',
            text=np.round(riesgo_df.values, 2),
            texttemplate='%{text:.2f}',
            textfont={"size": 10}
        ))
        fig_heatmap.update_layout(height=400, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_heatmap, use_container_width=True)
    
    with col_dist:
        st.markdown("#### 📊 Distribución P1–P4 por tipo de vehículo")
        # Distribución
        dist_data = pd.DataFrame({
            'Tipo': ['Bus', 'Camión', 'Liviano', 'Camioneta'],
            'P1': [2, 3, 1, 2],
            'P2': [8, 10, 3, 2],
            'P3': [15, 20, 8, 6],
            'P4': [35, 42, 28, 24]
        })
        fig_dist = px.bar(dist_data, x='Tipo', y=['P1', 'P2', 'P3', 'P4'],
                         barmode='stack', color_discrete_map={
                             'P1': '#d32f2f', 'P2': '#f57c00', 
                             'P3': '#fbc02d', 'P4': '#388e3c'
                         })
        fig_dist.update_layout(height=400, margin=dict(l=0, r=0, t=30, b=0),
                              legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
        st.plotly_chart(fig_dist, use_container_width=True)
    
    col_evol, col_top5 = st.columns(2)
    
    with col_evol:
        st.markdown("#### 📈 Evolución alertas P1/P2 (últimos 30 días)")
        # Línea de alertas diarias
        dias = pd.date_range(datetime.now() - timedelta(days=30), datetime.now(), freq='D')
        alertas_p1p2 = np.random.poisson(3, len(dias))
        fig_evol = px.line(
            x=dias, y=alertas_p1p2,
            labels={'x': 'Fecha', 'y': 'Alertas P1+P2'},
            markers=True
        )
        fig_evol.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), hovermode='x')
        st.plotly_chart(fig_evol, use_container_width=True)
    
    with col_top5:
        st.markdown("#### 🚨 Top 5 marcas más riesgosas")
        top_marcas = pd.DataFrame({
            'Marca': ['Volvo', 'Mercedes', 'Scania', 'Hino', 'MAN'],
            'Prob promedio': [0.64, 0.58, 0.52, 0.48, 0.45]
        })
        fig_top = px.bar(top_marcas, y='Marca', x='Prob promedio',
                        orientation='h', color='Prob promedio',
                        color_continuous_scale='Reds')
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
        st.metric("Próx. 7 días", "3", delta="+1")
    
    with col2:
        st.metric("Próx. 30 días", "18", delta="+5")
    
    with col3:
        st.metric("SKU en quiebre", "2", delta="0")
    
    with col4:
        st.metric("Cobertura stock", "45 días", delta="+10 días")
    
    with col5:
        st.metric("Cumpl. PM", "92%", delta="-1%")
    
    with col6:
        st.metric("Backlog", "7 OT", delta="+2")
    
    st.markdown("---")
    
    # Tabla de intervenciones recomendadas
    st.markdown("#### 🎯 Intervenciones sugeridas (próximos 30 días)")
    
    intervenciones_df = pd.DataFrame({
        'Patente': ['XXXX-01', 'XXXX-02', 'XXXX-03'],
        'Tipo': ['Inspección', 'Preventivo', 'Correctivo'],
        'Sistema': ['Motor', 'Frenos', 'Transmisión'],
        'Ventana': ['20-22 jun', '23-25 jun', '27-29 jun'],
        'Urgencia': ['P1', 'P2', 'P2'],
        'Costo estimado': ['$450.000', '$320.000', '$680.000'],
        'Costo NO intervenir': ['$1.200.000', '$950.000', '$2.100.000'],
        'Repuestos sugeridos': ['Filtro aceite, bujías', 'Pastillas freno', 'Líquido transmisión']
    })
    
    st.dataframe(intervenciones_df, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Sección de repuestos
    st.markdown("#### 📦 Repuestos críticos y abastecimiento")
    
    st.info(
        "⚠️ Esta sección requiere que el cliente tenga maestro de repuestos (SKU + stock). "
        "Si no está disponible, se mostrará en modo limitado."
    )
    
    repuestos_df = pd.DataFrame({
        'SKU': ['FILTER-OIL-01', 'BRAKE-PAD-02', 'TRANS-LIQ-03', 'COOL-FLUID-04'],
        'Descripción': ['Filtro aceite motor', 'Pastillas freno', 'Líquido transmisión', 'Refrigerante'],
        'Stock actual': [45, 12, 8, 25],
        'Demanda 30d': [30, 25, 6, 18],
        'Lead time (días)': [7, 10, 14, 5],
        'Cobertura (días)': [45, 14, 40, 42],
        'Criticidad': ['Media', 'Alta', 'Alta', 'Media'],
        'Acción': ['OK', '⚠️ Comprar', 'OK', 'OK']
    })
    
    st.dataframe(repuestos_df, use_container_width=True, hide_index=True)
    
    col_riesgo, col_top_cost = st.columns(2)
    
    with col_riesgo:
        st.markdown("#### ⚠️ Repuestos en riesgo de quiebre")
        en_riesgo = repuestos_df[repuestos_df['Cobertura (días)'] < 30]
        if len(en_riesgo) > 0:
            st.dataframe(
                en_riesgo[['SKU', 'Stock actual', 'Cobertura (días)']],
                use_container_width=True, hide_index=True
            )
        else:
            st.success("✅ Ningún repuesto crítico en riesgo.")
    
    with col_top_cost:
        st.markdown("#### 💰 Top 5 repuestos por costo anual")
        top_cost = pd.DataFrame({
            'SKU': ['TRANS-LIQ-03', 'BRAKE-PAD-02', 'COOL-FLUID-04', 'FILTER-OIL-01', 'BELT-01'],
            'Costo anual': [850000, 720000, 480000, 360000, 240000]
        })
        fig_cost = px.bar(top_cost, y='SKU', x='Costo anual', orientation='h',
                         color='Costo anual', color_continuous_scale='Reds')
        fig_cost.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
        st.plotly_chart(fig_cost, use_container_width=True)
    
    # Cumplimiento de PM
    st.markdown("---")
    st.markdown("#### 📅 Mantenimiento preventivo")
    col_gauge, col_pm = st.columns(2)
    
    with col_gauge:
        st.markdown("**% Cumplimiento global**")
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=92,
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
    
    with col_pm:
        st.markdown("**PM vencidos**")
        pm_vencidas = pd.DataFrame({
            'Patente': ['XXXX-12', 'XXXX-45', 'XXXX-67'],
            'PM vencida': ['10 días', '7 días', '23 días'],
            'Próximo sistema': ['Motor', 'Frenos', 'Transmisión']
        })
        st.dataframe(pm_vencidas, use_container_width=True, hide_index=True)

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
        st.metric("Costo evitado acumulado", "$4.850.000", "+$320.000")
        st.caption("*(solo alertas confirmadas)*")
    
    with col2:
        st.metric("Downtime evitado", "285 horas", "+45 horas")
        st.caption("*(MTTR promedio × alertas)*")
    
    with col3:
        st.metric("Costo mantenimiento/km", "$4.230", "-$180")
    
    with col4:
        st.metric("Costo mantenimiento/unidad", "$47.500", "-$2.100")
    
    st.markdown("---")
    
    # Productividad de flota
    st.markdown("#### 📈 Productividad y eficiencia de flota")
    col_prod1, col_prod2 = st.columns(2)
    
    with col_prod1:
        st.markdown("**MTBF, MTTR, Disponibilidad — últimos 12 meses**")
        meses = pd.date_range('2025-06', '2026-05', freq='MS')
        df_prod = pd.DataFrame({
            'Mes': meses,
            'MTBF (h)': np.random.uniform(800, 1300, len(meses)),
            'MTTR (h)': np.random.uniform(16, 28, len(meses)),
            'Disponibilidad (%)': np.random.uniform(88, 96, len(meses))
        })
        
        fig_prod = go.Figure()
        fig_prod.add_trace(go.Scatter(x=df_prod['Mes'], y=df_prod['MTBF (h)'],
                                      name='MTBF (horas)', yaxis='y'))
        fig_prod.add_trace(go.Scatter(x=df_prod['Mes'], y=df_prod['MTTR (h)'],
                                      name='MTTR (horas)', yaxis='y2'))
        fig_prod.update_layout(
            yaxis=dict(title='MTBF (horas)'),
            yaxis2=dict(title='MTTR (horas)', overlaying='y', side='right'),
            hovermode='x', height=350, margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig_prod, use_container_width=True)
    
    with col_prod2:
        st.markdown("**Downtime planificado vs no planificado**")
        downtime_data = pd.DataFrame({
            'Mes': ['Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic', 'Ene', 'Feb', 'Mar', 'Abr', 'May'],
            'Planificado (h)': [120, 115, 130, 125, 110, 135, 140, 125, 120, 130, 115, 125],
            'No planificado (h)': [85, 72, 68, 55, 48, 42, 38, 35, 32, 28, 25, 22]
        })
        fig_down = px.bar(downtime_data, x='Mes', y=['Planificado (h)', 'No planificado (h)'],
                         barmode='stack', color_discrete_map={
                             'Planificado (h)': '#4285F4', 'No planificado (h)': '#EA4335'
                         })
        fig_down.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0),
                              legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
        st.plotly_chart(fig_down, use_container_width=True)
    
    # Comparación antes/después — CANDADO HASTA MES 6
    st.markdown("---")
    st.markdown("#### 🔄 Comparación antes/después del modelo")
    
    tiempo_uso = 3  # Simulado: 3 meses de uso
    if tiempo_uso < 6:
        st.info(
            f"⏳ Esta métrica se activará en el **mes 6** de uso. "
            f"Actualmente en mes {tiempo_uso}. "
            f"Se necesita ≥6 meses de datos en producción para una comparación válida."
        )
    else:
        # Mostrar comparación real
        comp_df = pd.DataFrame({
            'Métrica': ['MTBF', 'MTTR', 'Downtime no planificado', 'Costo/km'],
            'Antes (6 meses previos)': [850, 22, 450, 4650],
            'Después (6 meses con modelo)': [1180, 18, 185, 4230],
            'Mejora (%)': [38.8, 18.2, 58.9, 8.9]
        })
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
    
    # Desempeño del modelo
    st.markdown("---")
    st.markdown("#### 🧠 Desempeño del modelo de IA")
    col_perf1, col_perf2 = st.columns(2)
    
    with col_perf1:
        st.markdown("**Explicabilidad y confiabilidad**")
        perf_metrics = {
            "De cada 10 fallas, alertamos": "8 con anticipación (Recall)",
            "De cada 10 alertas, eran correctas": "7.5 (Precision)",
            "Anticipación promedio": "16 días antes de falla",
            "Alertas confirmadas por taller": "82%",
            "Alertas rechazadas": "12%",
            "Pendientes de revisión": "6%"
        }
        for metric, value in perf_metrics.items():
            st.write(f"**{metric}:** {value}")
    
    with col_perf2:
        st.markdown("**Matriz de confusión simplificada**")
        confusion = pd.DataFrame({
            '': ['Falla real', 'No falla'],
            'Alertamos': [82, 18],
            'No alertamos': [18, 882]
        })
        st.dataframe(confusion, use_container_width=True, hide_index=False)
        st.caption("Formato: casos reales en muestras de test")
    
    st.markdown("**Estado del modelo:** 🟢 Estable (sin drift detectado)")
    
    # Feedback del taller
    st.markdown("---")
    st.markdown("#### 📝 Feedback del taller y ciclo de aprendizaje")
    col_fb1, col_fb2 = st.columns(2)
    
    with col_fb1:
        st.markdown("**Alertas por estado**")
        fb_data = pd.DataFrame({
            'Estado': ['Confirmadas', 'Parciales', 'Rechazadas', 'Pendientes'],
            'Cantidad': [145, 28, 35, 12]
        })
        fig_fb = px.pie(fb_data, values='Cantidad', names='Estado',
                       color_discrete_map={
                           'Confirmadas': '#4CAF50',
                           'Parciales': '#FFC107',
                           'Rechazadas': '#F44336',
                           'Pendientes': '#9E9E9E'
                       })
        fig_fb.update_layout(height=350, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_fb, use_container_width=True)
    
    with col_fb2:
        st.markdown("**Top motivos de rechazo**")
        rechazo_df = pd.DataFrame({
            'Motivo': ['Componente en buen estado', 'Falla en otro sistema', 'Unidad recién intervenida', 'Alerta duplicada'],
            'Cantidad': [18, 10, 5, 2]
        })
        fig_rech = px.bar(rechazo_df, y='Motivo', x='Cantidad', orientation='h',
                         color='Cantidad', color_continuous_scale='Blues')
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
            st.metric("ROI estimado", "125%", delta="25 puntos")
            st.caption("Costo evitado / costo BAITECK")
        with col_roi2:
            st.metric("Payback estimado", "4.2 meses", delta="-0.8 meses")
            st.caption("Días para recuperar inversión")

# ============================================================================
# MAIN LAYOUT
# ============================================================================

def main():
    # Crear layout con columnas: título a la izquierda, logo a la derecha - ALINEADOS VERTICALMENTE
    col_title, col_logo = st.columns([5, 1], vertical_alignment="center")
    
    with col_title:
        st.title("📊 BAITECK — Dashboard Predictivo de Flotas")
        st.markdown("Versión 1.0 — Diseño operativo y comercial")
    
    with col_logo:
        # Agregar el logo a la misma altura del título
        logo_path = "Logo_BAITECK.jpg"
        try:
            if os.path.exists(logo_path):
                st.image(logo_path, width=80, use_container_width=False)
            elif os.path.exists(f"/mnt/user-data/uploads/{logo_path}"):
                st.image(f"/mnt/user-data/uploads/{logo_path}", width=80, use_container_width=False)
            elif os.path.exists(f"baiteck-dashboard-assets/{logo_path}"):
                st.image(f"baiteck-dashboard-assets/{logo_path}", width=80, use_container_width=False)
        except Exception:
            pass
    
    # Selector de vista en sidebar
    with st.sidebar:
        st.markdown("## 🎯 Navegación")
        
        # Indicador de conexión a Supabase
        db_conn = get_db_connection()
        if db_conn is not None:
            st.success("✅ Conectado a Supabase")
            db_conn.close()
        else:
            st.warning("⚠️ Usando datos de demostración (Supabase no disponible)")
        
        st.markdown("---")
        
        vista_seleccionada = st.radio(
            "Selecciona una vista",
            ["Estado y Riesgo", "Plan de Acción", "Impacto y Desempeño"]
        )
        
        st.markdown("---")
        st.markdown("### ℹ️ Acerca de")
        st.markdown("""
        **BAITECK v1.0** — Mantenimiento predictivo de flotas.
        
        - **Vista 1:** Qué pasa, qué va a fallar.
        - **Vista 2:** Qué hacer, con qué repuestos.
        - **Vista 3:** Cuánto está rindiendo.
        
        **Datos:** Síntéticos en demo. Conectado a Supabase en producción.
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
