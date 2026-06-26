"""
EXPLICACIONES DE MÉTRICAS — Sistema centralizado de tooltips y documentación
==============================================================================

Propósito:
  - Diccionario centralizado de explicaciones para TODAS las métricas
  - Funciones helper para insertar tooltips en Streamlit
  - Explicaciones en lenguaje simple, sin fórmulas (usuario final)
  - Accesibles mediante hover, expandible, o botón de ayuda

Estructura:
  explicaciones = {
      "vista_1": {
          "metrica_nombre": {
              "titulo": "...",
              "descripcion": "...",
              "que_incluye": ["...", "..."],
              "que_excluye": ["...", "..."],
              "fuente": "..."
          }
      },
      "vista_2": {...},
      "vista_3": {...}
  }

Uso:
  from explicaciones_metricas import get_explicacion, render_tooltip
  
  # Obtener explicación
  exp = get_explicacion("vista_1", "unidades_operativas")
  
  # Renderizar en dashboard
  render_tooltip("Unidades Operativas", "unidades_operativas", "vista_1")

Autor: BAITECK — junio 2026
"""

import streamlit as st
from typing import Dict, Optional

# ============================================================================
# DICCIONARIO CENTRALIZADO DE EXPLICACIONES
# ============================================================================

EXPLICACIONES = {
    "vista_1": {
        # ====== BANDA SUPERIOR (HERO METRICS) ======
        "unidades_operativas": {
            "titulo": "Unidades Operativas",
            "descripcion": "Cantidad total de vehículos en tu flota que están activos y disponibles para operación.",
            "que_incluye": [
                "Buses, camiones y vehículos livianos en estado activo",
                "Unidades con al menos un registro en los últimos 30 días",
            ],
            "que_excluye": [
                "Vehículos dados de baja o en mantenimiento mayor",
                "Unidades sin historial de operación en el período",
            ],
            "fuente": "Base de datos de activos (estado = 'activo')"
        },
        
        "disponibilidad_operacional": {
            "titulo": "% Disponibilidad Operacional",
            "descripcion": "Porcentaje de tiempo que tu flota estuvo disponible para operación en los últimos 30 días.",
            "que_incluye": [
                "Tiempo de operación normal sin detenciones",
                "Mantenciones planificadas (no restan disponibilidad)",
            ],
            "que_excluye": [
                "Detenciones inesperadas (fallas correctivas)",
                "Tiempo de inactividad no planificado",
            ],
            "fuente": "Historial de órdenes de trabajo y disponibilidad diaria"
        },
        
        "unidades_p1_critica": {
            "titulo": "Unidades en P1 Crítica",
            "descripcion": "Cantidad de vehículos con RIESGO CRÍTICO de falla en los próximos 7 días. Requieren atención inmediata.",
            "que_incluye": [
                "Unidades con probabilidad de falla > 70% en 7 días",
                "Basado en modelo predictivo XGBoost entrenado con tu historial de fallas",
            ],
            "que_excluye": [
                "Unidades ya en mantenimiento preventivo activo",
                "Vehículos con mantenimiento completado en últimas 48 horas",
            ],
            "fuente": "Scoring predictivo (modelo XGBoost)"
        },
        
        "unidades_p2_alta": {
            "titulo": "Unidades en P2 Alta",
            "descripcion": "Cantidad de vehículos con RIESGO ALTO de falla en los próximos 30 días. Ideal para mantenimiento preventivo en la próxima semana.",
            "que_incluye": [
                "Unidades con probabilidad de falla 40-70% en 30 días",
                "Clasificadas automáticamente por el modelo predictivo",
            ],
            "que_excluye": [
                "Unidades ya clasificadas como P1",
                "Vehículos en mantenimiento activo",
            ],
            "fuente": "Scoring predictivo (modelo XGBoost)"
        },
        
        "fallas_anticipadas": {
            "titulo": "Fallas Anticipadas (últimos 30 días)",
            "descripcion": "Cantidad de fallas que el modelo PREDIJO CORRECTAMENTE en el mes anterior. Indica qué tan bien está funcionando la solución.",
            "que_incluye": [
                "Unidades que fueron alertadas como P1/P2 y luego fallaron",
                "Confirmadas por feedback del taller",
            ],
            "que_excluye": [
                "Alertas sin confirmación de falla",
                "Fallas no previstas (falsos negativos)",
            ],
            "fuente": "Feedback del taller + scoring histórico"
        },
        
        "mtbf_flota": {
            "titulo": "MTBF Flota (últimos 90 días)",
            "descripcion": "Promedio de horas que una unidad opera sin fallar. Más alto = flota más confiable.",
            "que_incluye": [
                "Horas de operación real de toda la flota",
                "Conteo de fallas correctivas (no planificadas)",
            ],
            "que_excluye": [
                "Mantenciones preventivas planificadas",
                "Paradas administrativas",
            ],
            "fuente": "Historial de órdenes de trabajo correctivas"
        },

        # ====== RANKING Y ANÁLISIS ======
        "ranking_unidades_riesgo": {
            "titulo": "Ranking de Unidades en Riesgo",
            "descripcion": "Tabla de los vehículos más críticos ordenados por probabilidad de falla. Incluye patente, marca, edad y tres factores principales que generan el riesgo.",
            "que_incluye": [
                "Probabilidad de falla en 7, 30 y 90 días",
                "Top 3 factores de riesgo (sistemas o patrones más influyentes)",
                "Recomendación de acción (reparación, inspección, reemplazo)",
            ],
            "que_excluye": [
                "Unidades sin historial de fallas",
                "Vehículos dados de baja",
            ],
            "fuente": "Scoring predictivo con análisis SHAP (explicabilidad)"
        },

        "heatmap_sistemas": {
            "titulo": "Mapa de Calor: Sistemas en Riesgo",
            "descripcion": "Visualiza qué sistemas mecánicos (frenos, motor, transmisión, etc.) tienen más riesgo de fallar en tu flota.",
            "que_incluye": [
                "Historial de fallas por sistema en últimos 90 días",
                "Probabilidad agregada de falla por sistema",
            ],
            "que_excluye": [
                "Sistemas sin historial de fallas",
                "Vehículos con mantenimiento reciente en ese sistema",
            ],
            "fuente": "Taxonomía de fallas + scoring por sistema"
        },
    },

    "vista_2": {
        "plan_accion": {
            "titulo": "Plan de Acción",
            "descripcion": "Recomendaciones automáticas de qué mantención hacer, con qué repuestos y cuándo es la mejor ventana.",
            "que_incluye": [
                "Unidades en P1/P2 clasificadas por urgencia",
                "Repuestos críticos necesarios para cada reparación",
                "Ventanas óptimas de tiempo (horas disponibles)",
            ],
            "que_excluye": [
                "Unidades en operación normal (P3/P4)",
                "Mantenciones completadas en últimos 7 días",
            ],
            "fuente": "Scoring + tabla de repuestos críticos"
        },

        "repuestos_criticos": {
            "titulo": "Repuestos Críticos (P1/P2)",
            "descripcion": "Lista de piezas necesarias para reparar los vehículos en riesgo. Ordena por urgencia y disponibilidad en pañol.",
            "que_incluye": [
                "SKU de repuestos necesarios para las 10 unidades más críticas",
                "Disponibilidad en stock",
                "Lead time del proveedor (si es compra externa)",
                "Costo estimado",
            ],
            "que_excluye": [
                "Repuestos de mantenimiento rutinario",
                "Piezas para unidades en estado bueno (P3/P4)",
            ],
            "fuente": "Tabla repuestos_panel_criticos + consumo histórico"
        },

        "cobertura_stock": {
            "titulo": "Cobertura de Stock",
            "descripcion": "Porcentaje de repuestos críticos que tienes en bodega. ¿Estás preparado para las reparaciones que vienen?",
            "que_incluye": [
                "Repuestos en stock vs. repuestos necesarios en próximos 30 días",
                "Solo cuenta piezas críticas (P1/P2)",
            ],
            "que_excluye": [
                "Stock de piezas de bajo movimiento",
                "Repuestos genéricos sin demanda previsible",
            ],
            "fuente": "Inventario + demanda proyectada"
        },

        "pm_vencidos": {
            "titulo": "Mantenciones Preventivas Vencidas",
            "descripcion": "Cantidad de unidades que superaron su intervalo de mantención preventiva planificada.",
            "que_incluye": [
                "Vehículos que debían recibir mantenimiento planificado",
                "Basado en odómetro, horómetro o calendario",
            ],
            "que_excluye": [
                "Mantenciones completadas a tiempo",
                "Unidades nuevas sin historial",
            ],
            "fuente": "Plan de mantención + historial de OT"
        },

        "backlog_mantenimiento": {
            "titulo": "Backlog de Mantenimiento",
            "descripcion": "Cantidad de horas de trabajo de mantención que están pendientes (OT no asignadas o no iniciadas).",
            "que_incluye": [
                "OT preventivas creadas pero no ejecutadas",
                "OT correctivas en cola de espera",
            ],
            "que_excluye": [
                "OT completadas o canceladas",
                "Trabajo ya en ejecución",
            ],
            "fuente": "Sistema de órdenes de trabajo"
        },
    },

    "vista_3": {
        "costo_total_mantenimiento": {
            "titulo": "Costo Total de Mantenimiento por Unidad",
            "descripcion": "Inversión promedio en mantención por vehículo en los últimos 30/90 días. Incluye repuestos usados en reparaciones.",
            "que_incluye": [
                "Costo de repuestos consumidos en mantención preventiva y correctiva",
                "Repuestos principales (frenos, filtros, mangueras, componentes mecánicos)",
            ],
            "que_excluye": [
                "Costo de mano de obra o mecánico",
                "Lubricantes y consumibles menores (pañol)",
                "Combustible",
                "Lavado o detallado",
            ],
            "fuente": "Historial de órdenes de trabajo + valuación de repuestos"
        },

        "costo_evitado": {
            "titulo": "Costo Evitado",
            "descripcion": "Dinero ahorrado al prevenir fallas. Se calcula como: costo de detención (camión en piso) menos costo de mantenimiento preventivo.",
            "que_incluye": [
                "Detenciones inesperadas prevenidas (fallas anticipadas por modelo)",
                "Costo de pérdida de operación durante detención",
                "Menos: costo de la mantención preventiva realizada a tiempo",
            ],
            "que_excluye": [
                "Fallas no prevenidas",
                "Detenciones planificadas",
            ],
            "fuente": "Feedback del taller + análisis económico"
        },

        "downtime_evitado": {
            "titulo": "Downtime Evitado (Horas)",
            "descripcion": "Horas de operación que recuperaste al evitar fallas. Cada hora = productividad del vehículo.",
            "que_incluye": [
                "Horas de detención evitadas por mantención preventiva",
                "Basado en tiempo promedio de reparación de fallas similares",
            ],
            "que_excluye": [
                "Paradas planificadas",
                "Tiempo de mantenimiento preventivo",
            ],
            "fuente": "Feedback del taller + histórico de tiempo de reparación"
        },

        "roi_modelo": {
            "titulo": "ROI del Modelo Predictivo",
            "descripcion": "Retorno de inversión. Compara el ahorro total (costo + downtime evitado) vs. el costo de la solución BAITECK.",
            "que_incluye": [
                "Costo evitado (dinero ahorrado)",
                "Downtime evitado convertido a valor",
                "Menos: costo anual de suscripción a BAITECK",
            ],
            "que_excluye": [
                "Beneficios intangibles (confiabilidad, reputación)",
                "Ahorros ya realizados en años anteriores",
            ],
            "fuente": "Análisis económico integral"
        },

        "accuracy_modelo": {
            "titulo": "Accuracy del Modelo",
            "descripcion": "¿Qué tan acertadas son las predicciones? Porcentaje de alertas P1/P2 que resultaron en fallas reales.",
            "que_incluye": [
                "Alertas confirmadas por feedback del taller",
                "Período de evaluación: últimos 30 días",
            ],
            "que_excluye": [
                "Alertas sin confirmación aún",
                "Falsos negativos (fallas no anticipadas)",
            ],
            "fuente": "Feedback del taller + scoring histórico"
        },

        "precision_sistema": {
            "titulo": "Precisión por Sistema",
            "descripcion": "Qué sistemas el modelo predice MEJOR. Identifica dónde el modelo es más confiable.",
            "que_incluye": [
                "Accuracy desglosado por sistema mecánico",
                "Ejemplo: Motor 85%, Frenos 92%, Transmisión 78%",
            ],
            "que_excluye": [
                "Sistemas con menos de 5 fallas en el período",
            ],
            "fuente": "Taxonomía de fallas + scoring por sistema"
        },

        "feedback_taller": {
            "titulo": "Feedback del Taller",
            "descripcion": "Confirmación del taller: ¿qué predicciones fueron acertadas? ¿Cuáles fueron falsas alarmas? Esto entrena el modelo.",
            "que_incluye": [
                "3 opciones: Falla confirmada, Alarma falsa, Aún no se sabe",
                "Comentarios adicionales del mecánico",
            ],
            "que_excluye": [
                "Información de mantenimiento corrección, solo validación",
            ],
            "fuente": "Formulario simple de feedback en dashboard"
        },
    },
}


# ============================================================================
# FUNCIONES HELPER
# ============================================================================

def get_explicacion(vista: str, metrica: str) -> Optional[Dict]:
    """
    Obtiene la explicación completa de una métrica.
    
    Args:
        vista: "vista_1", "vista_2" o "vista_3"
        metrica: nombre de la métrica (ej: "unidades_operativas")
    
    Returns:
        Dict con: titulo, descripcion, que_incluye, que_excluye, fuente
        None si no existe
    """
    if vista not in EXPLICACIONES:
        return None
    if metrica not in EXPLICACIONES[vista]:
        return None
    
    return EXPLICACIONES[vista][metrica]


def render_tooltip(titulo: str, clave_metrica: str, vista: str, posicion: str = "right"):
    """
    Renderiza un tooltip interactivo en Streamlit.
    
    Uso:
        render_tooltip("Unidades Operativas", "unidades_operativas", "vista_1")
    
    Resultado:
        [Unidades Operativas ℹ️] (hover muestra explicación)
    
    Args:
        titulo: texto visible en el dashboard
        clave_metrica: clave del diccionario EXPLICACIONES
        vista: "vista_1", "vista_2" o "vista_3"
        posicion: "left", "right", "top", "bottom" (si Streamlit lo soporta)
    """
    exp = get_explicacion(vista, clave_metrica)
    
    if not exp:
        st.write(titulo)
        return
    
    col_titulo, col_help = st.columns([20, 1])
    
    with col_titulo:
        st.write(titulo)
    
    with col_help:
        if st.button("ℹ️", key=f"help_{vista}_{clave_metrica}", help="Ver explicación"):
            with st.expander("📖 Explicación", expanded=True):
                st.markdown(f"### {exp['titulo']}")
                st.markdown(f"**{exp['descripcion']}**")
                
                if exp.get("que_incluye"):
                    st.markdown("**Incluye:**")
                    for item in exp["que_incluye"]:
                        st.markdown(f"  • {item}")
                
                if exp.get("que_excluye"):
                    st.markdown("**NO incluye:**")
                    for item in exp["que_excluye"]:
                        st.markdown(f"  • {item}")
                
                st.caption(f"📊 Fuente: {exp.get('fuente', 'N/A')}")


def render_tooltip_inline(titulo: str, clave_metrica: str, vista: str):
    """
    Renderiza tooltip inline (sin botón, solo información flotante al hover).
    
    Para uso con st.metric() o st.write() donde necesitas agregar contexto.
    """
    exp = get_explicacion(vista, clave_metrica)
    
    if not exp:
        return titulo
    
    # Construir texto con tooltip nativo de Streamlit
    help_text = f"{exp['descripcion']}\n\n"
    
    if exp.get("que_incluye"):
        help_text += "✅ Incluye:\n"
        for item in exp["que_incluye"]:
            help_text += f"  • {item}\n"
    
    if exp.get("que_excluye"):
        help_text += "\n❌ NO incluye:\n"
        for item in exp["que_excluye"]:
            help_text += f"  • {item}\n"
    
    help_text += f"\n📊 Fuente: {exp.get('fuente', 'N/A')}"
    
    # Retornar tuple (titulo, help_text) para usar en st.metric(label, value, help=help_text)
    return help_text


# ============================================================================
# FUNCIONES DE DEBUG
# ============================================================================

def listar_todas_metricas():
    """Imprime todas las métricas disponibles (para debugging)."""
    for vista, metricas in EXPLICACIONES.items():
        print(f"\n{vista.upper()}")
        print("=" * 50)
        for metrica in metricas.keys():
            exp = metricas[metrica]
            print(f"  • {metrica}: {exp['titulo']}")


def validar_estructura():
    """Valida que todas las explicaciones tengan campos obligatorios."""
    campos_obligatorios = ["titulo", "descripcion", "que_incluye", "que_excluye", "fuente"]
    
    for vista, metricas in EXPLICACIONES.items():
        for metrica, exp in metricas.items():
            for campo in campos_obligatorios:
                if campo not in exp:
                    print(f"⚠️  {vista}/{metrica}: falta campo '{campo}'")
            
            if not isinstance(exp.get("que_incluye"), list):
                print(f"⚠️  {vista}/{metrica}: 'que_incluye' debe ser lista")
            
            if not isinstance(exp.get("que_excluye"), list):
                print(f"⚠️  {vista}/{metrica}: 'que_excluye' debe ser lista")
    
    print("✅ Validación completada")


if __name__ == "__main__":
    # Ejecutar debug
    print("🔍 MÉTRICAS DISPONIBLES:")
    listar_todas_metricas()
    print("\n" + "=" * 50)
    validar_estructura()
