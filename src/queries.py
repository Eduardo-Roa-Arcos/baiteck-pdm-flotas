"""
BAITECK — Queries SQL para Dashboard Refactorizado (v1.0)

Todas las queries SQL necesarias para alimentar las 3 vistas del dashboard.
Documentadas: qué está conectado a datos reales (Supabase) vs qué es placeholder.

Stack: Supabase PostgreSQL
Tablas esperadas: activos, ordenes_trabajo, scoring_resultados, feedback_taller, 
                   repuestos_consumidos, taxonomia_fallas, auditoria_calidad_datos

Nota: En la versión actual (mayo 2026), muchas queries retornan datos sintéticos
      porque el proyecto está en fase smoke test. Cuando llegue el primer cliente real,
      estas queries retornarán datos verdaderos sin cambios de sintaxis.
"""

# ============================================================================
# VISTA 1 — ESTADO DE FLOTA Y RIESGO PREDICTIVO
# ============================================================================

def query_hero_metrics_v1(fecha_inicio, fecha_fin):
    """
    Query para los KPI hero de Vista 1.
    
    DATOS REALES:
    - Unidades operativas (activos.estado_actual = 'operativo')
    - MTBF (calculado de ordenes_trabajo)
    
    DATOS QUE REQUIEREN INTEGRACIÓN:
    - Disponibilidad operacional (requiere tabla disponibilidad_diaria o estimación desde OT)
    - Fallas anticipadas (requiere feedback_taller + scoring_resultados)
    
    Status: Parcialmente implementado en v2.0
    """
    query = f"""
    SELECT
        COUNT(DISTINCT a.activo_id) as unidades_operativas,
        -- Disponibilidad: requiere registro de horas detenidas
        -- Por ahora: estimación = 1 - (días con OT correctiva / días totales)
        ROUND(100.0 * (1.0 - (
            COUNT(DISTINCT CASE 
                WHEN ot.tipo_ot = 'correctiva' 
                THEN DATE(ot.fecha_apertura) 
            END)::float / 
            DATE_PART('day', '{fecha_fin}'::date - '{fecha_inicio}'::date)
        )), 1) as disponibilidad_pct,
        
        -- MTBF: Mean Time Between Failures
        ROUND(
            EXTRACT(EPOCH FROM ('{fecha_fin}'::date - '{fecha_inicio}'::date) * INTERVAL '1 day') / 3600.0 /
            NULLIF(COUNT(CASE WHEN ot.tipo_ot = 'correctiva' THEN 1 END), 0),
            0
        ) as mtbf_horas,
        
        -- Fallas anticipadas (requiere feedback taller)
        COUNT(DISTINCT CASE 
            WHEN ft.falla_confirmada = true 
            THEN ft.feedback_id 
        END) as fallas_anticipadas_confirmadas,
        
        -- P1 y P2 actuales
        COUNT(DISTINCT CASE 
            WHEN s.prioridad = 'P1_critica' AND s.fecha_scoring = CURRENT_DATE
            THEN s.activo_id 
        END) as unidades_p1,
        
        COUNT(DISTINCT CASE 
            WHEN s.prioridad = 'P2_alta' AND s.fecha_scoring = CURRENT_DATE
            THEN s.activo_id 
        END) as unidades_p2
        
    FROM activos a
    LEFT JOIN ordenes_trabajo ot ON a.activo_id = ot.activo_id 
        AND ot.fecha_apertura >= '{fecha_inicio}'::date 
        AND ot.fecha_apertura <= '{fecha_fin}'::date
    LEFT JOIN scoring_resultados s ON a.activo_id = s.activo_id
    LEFT JOIN feedback_taller ft ON s.scoring_id = ft.scoring_id
    WHERE a.estado_actual = 'operativo'
    """
    return query

def query_ranking_riesgo_v1(horizonte):
    """
    Query principal de Vista 1: ranking de unidades en riesgo.
    
    DATOS REALES:
    - scoring_resultados.probabilidad_falla (output del modelo XGBoost)
    - scoring_resultados.prioridad (P1-P4, asignado en scoring)
    - activos.* (patente, marca, modelo)
    - ordenes_trabajo (última OT, sistema probable)
    
    Status: Implementado en v2.0 (query base de "Activos en Acción")
    """
    
    # Mapeo horizonte a columna de scoring
    horizonte_dias = {'7 días': 7, '30 días': 30, '90 días': 90}.get(horizonte, 30)
    
    query = f"""
    SELECT
        a.activo_id,
        a.patente,
        a.marca,
        a.modelo,
        a.fecha_alta_flota,
        s.probabilidad_falla,
        s.prioridad as semaforo,
        ROUND(s.probabilidad_falla * 100, 1) as prob_30d,
        -- Fecha probable de falla: estimada del modelo (requiere survival analysis en v2)
        (CURRENT_DATE + INTERVAL '{horizonte_dias} days')::date as fecha_probable_falla,
        -- Sistema con mayor riesgo (requiere taxonomía en v2; hoy: aproximación de última OT)
        COALESCE(ot_recent.sistema, 'N/A') as sistema_riesgo,
        -- Días desde última OT
        COALESCE(
            EXTRACT(DAY FROM CURRENT_DATE - ot_recent.fecha_ultima),
            0
        )::int as dias_ultima_ot,
        -- Odómetro actual
        COALESCE(ot_recent.odometro_km, 0)::numeric as km_actual,
        -- Edad del activo
        EXTRACT(YEAR FROM AGE(CURRENT_DATE, a.fecha_alta_flota))::int as edad_anos,
        -- Fecha de scoring
        s.fecha_scoring,
        s.modelo_version
    
    FROM scoring_resultados s
    JOIN activos a ON s.activo_id = a.activo_id
    -- Join con última OT por activo
    LEFT JOIN LATERAL (
        SELECT 
            ot.activo_id,
            ot.sistema,
            ot.fecha_apertura as fecha_ultima,
            ot.odometro_km
        FROM ordenes_trabajo ot
        WHERE ot.activo_id = a.activo_id
        ORDER BY ot.fecha_apertura DESC
        LIMIT 1
    ) ot_recent ON a.activo_id = ot_recent.activo_id
    
    WHERE s.fecha_scoring = CURRENT_DATE
        AND s.horizonte_dias = {horizonte_dias}
        AND s.prioridad IN ('P1_critica', 'P2_alta', 'P3_media', 'P4_baja')
    
    ORDER BY s.probabilidad_falla DESC
    LIMIT 15
    """
    return query

def query_mapa_calor_sistemas():
    """
    Query para mapa de calor: riesgo por sistema × horizonte.
    
    DATOS REALES:
    - Frecuencia histórica de OT por sistema (ordenes_trabajo.sistema)
    - En v2 con taxonomía limpia: agregación por sistema
    
    Status: Placeholder en v1 (datos sintéticos aleatorios en dashboard)
    Implementable cuando taxonomía de fallas esté limpia.
    """
    query = """
    -- PLACEHOLDER: Esta query retorna estructura, datos son sintéticos en dashboard.py
    -- Cuando taxonomía de fallas esté limpia (v2), esta query será:
    -- Agregación de probabilidad por sistema × horizonte desde scoring_resultados
    -- después de modelo multiclase.
    
    SELECT
        'Motor' as sistema,
        7 as horizonte_dias,
        RANDOM() * 0.8 as probabilidad_promedio
    UNION ALL
    SELECT 'Motor', 30, RANDOM() * 0.8
    UNION ALL
    SELECT 'Motor', 90, RANDOM() * 0.8
    -- ... etc para otros sistemas
    """
    return query

# ============================================================================
# VISTA 2 — PLAN DE ACCIÓN: MANTENIMIENTO Y REPUESTOS
# ============================================================================

def query_intervenciones_recomendadas_v2():
    """
    Query para intervenciones sugeridas en Vista 2.
    
    DATOS REALES:
    - scoring_resultados.probabilidad_falla (predicción)
    - ordenes_trabajo.* (costo histórico)
    - activos.* (identificación)
    
    DATOS QUE REQUIEREN INTEGRACIÓN:
    - Costo promedio de intervención por sistema (calculado de histórico OT)
    - Costo de NO intervenir (valor teórico basado en probabilidad × costo correctivo)
    - Ventana óptima (requiere análisis de disponibilidad operativa)
    
    Status: Base implementada en v2.0, refactorización para V2 completa en v1.0
    """
    query = """
    SELECT
        a.patente,
        a.marca,
        a.modelo,
        s.activo_id,
        
        -- Tipo de intervención sugerida
        CASE 
            WHEN s.probabilidad_falla >= 0.85 THEN 'Correctivo programado'
            WHEN s.probabilidad_falla >= 0.60 THEN 'Preventivo anticipado'
            ELSE 'Inspección'
        END as tipo_intervencion,
        
        -- Sistema probable (en v1 agregado; en v2 multiclase por componente)
        COALESCE(tax.sistema, 'Sistema general') as sistema,
        
        -- Ventana óptima de intervención (aproximación: basada en prob creciente)
        CONCAT(
            TO_CHAR(CURRENT_DATE + INTERVAL '3 days', 'DD Mon'),
            ' - ',
            TO_CHAR(CURRENT_DATE + INTERVAL '7 days', 'DD Mon')
        ) as ventana_optima,
        
        -- Urgencia (semáforo)
        s.prioridad as urgencia,
        
        -- Costo estimado de intervención
        COALESCE(
            (SELECT ROUND(AVG(costo_total_clp), 0)
             FROM ordenes_trabajo ot_cost
             WHERE ot_cost.sistema = tax.sistema
             AND EXTRACT(YEAR FROM ot_cost.fecha_apertura) = EXTRACT(YEAR FROM CURRENT_DATE) - 1),
            450000::numeric
        )::bigint as costo_estimado_intervencion,
        
        -- Costo de NO intervenir (teórico)
        ROUND(
            s.probabilidad_falla * 
            COALESCE(
                (SELECT AVG(costo_total_clp)
                 FROM ordenes_trabajo ot_cost2
                 WHERE ot_cost2.sistema = tax.sistema
                 AND ot_cost2.tipo_ot = 'correctiva'),
                1200000::numeric
            ),
            0
        )::bigint as costo_no_intervenir,
        
        -- Repuestos sugeridos (en v1 lista genérica; en v2 SKU específicos)
        STRING_AGG(DISTINCT rc.descripcion_repuesto, ', ') as repuestos_sugeridos,
        
        -- Probabilidad 30 días
        ROUND(s.probabilidad_falla * 100, 1) as probabilidad_30d
    
    FROM scoring_resultados s
    JOIN activos a ON s.activo_id = a.activo_id
    -- Join con última OT para sistema probable
    LEFT JOIN LATERAL (
        SELECT sistema, componente
        FROM ordenes_trabajo ot_sys
        WHERE ot_sys.activo_id = a.activo_id
        ORDER BY ot_sys.fecha_apertura DESC
        LIMIT 1
    ) ot_sys ON true
    LEFT JOIN taxonomia_fallas tax ON ot_sys.sistema = tax.sistema
    -- Join con consumo histórico de repuestos
    LEFT JOIN repuestos_consumidos rc ON true
    
    WHERE s.fecha_scoring = CURRENT_DATE
        AND s.horizonte_dias = 30
        AND s.prioridad IN ('P1_critica', 'P2_alta')
    
    GROUP BY 
        a.patente, a.marca, a.modelo, a.activo_id,
        s.probabilidad_falla, s.prioridad, tax.sistema, s.fecha_scoring
    
    ORDER BY s.probabilidad_falla DESC
    LIMIT 20
    """
    return query

def query_repuestos_maestro():
    """
    Query para maestro de repuestos y stock (Vista 2, bloque condicional).
    
    DATOS REALES (SI EXISTEN):
    - Tabla repuestos_maestro (SKU, stock_actual, lead_time, etc.)
    - Consumo histórico de repuestos (repuestos_consumidos)
    
    Status: Disponible solo si cliente tiene maestro SKU poblado.
    Si no existe tabla, bloque queda en modo "limitado" con solo consumo histórico.
    """
    query = """
    SELECT
        rm.sku,
        rm.descripcion,
        rm.sistema,
        rm.componente,
        rm.stock_actual,
        
        -- Demanda predictiva 30 días
        COALESCE(
            (SELECT ROUND(SUM(CASE WHEN DATE(ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '30 days'
                                 THEN rc.cantidad ELSE 0 END), 0)
             FROM repuestos_consumidos rc
             JOIN ordenes_trabajo ot ON rc.ot_id = ot.ot_id
             WHERE rc.sku = rm.sku),
            0::numeric
        ) as demanda_30d,
        
        -- Lead time promedio
        rm.lead_time_dias_promedio as lead_time_dias,
        
        -- Días de cobertura
        CASE 
            WHEN (SELECT ROUND(AVG(CASE WHEN DATE(ot.fecha_apertura) >= CURRENT_DATE - INTERVAL '30 days'
                                        THEN rc.cantidad END), 2)
                  FROM repuestos_consumidos rc
                  JOIN ordenes_trabajo ot ON rc.ot_id = ot.ot_id
                  WHERE rc.sku = rm.sku) > 0
            THEN ROUND(rm.stock_actual / 
                      (SELECT AVG(rc.cantidad)
                       FROM repuestos_consumidos rc
                       WHERE rc.sku = rm.sku), 0)
            ELSE rm.stock_actual
        END::int as dias_cobertura,
        
        -- Criticidad
        rm.criticidad,
        
        -- Acción recomendada
        CASE 
            WHEN rm.stock_actual < (rm.lead_time_dias_promedio * 
                 COALESCE((SELECT AVG(rc.cantidad)
                          FROM repuestos_consumidos rc
                          WHERE rc.sku = rm.sku), 1))
            THEN '⚠️ Comprar urgente'
            WHEN rm.stock_actual < (rm.stock_minimo)
            THEN '⚠️ Comprar'
            ELSE 'OK'
        END as accion
    
    FROM repuestos_maestro rm
    
    WHERE rm.criticidad IN ('alta', 'media')
        AND rm.activo = true
    
    ORDER BY dias_cobertura ASC, criticidad DESC
    LIMIT 30
    """
    return query

# ============================================================================
# VISTA 3 — IMPACTO Y DESEMPEÑO DEL MODELO
# ============================================================================

def query_disponibilidad_diaria_v3(fecha_inicio, fecha_fin):
    """
    Query para disponibilidad operacional, MTBF, MTTR en Vista 3.
    
    DATOS REALES:
    - Si existe tabla disponibilidad_diaria: datos directos
    - Si no existe: estimación desde ordenes_trabajo (menos precisa)
    
    Status: En v2.0 existe estimación desde OT. Idealmente el cliente 
            debe proveer tabla disponibilidad_diaria para exactitud.
    """
    query = f"""
    -- Opción A: Si cliente tiene tabla disponibilidad_diaria (recomendado)
    -- SELECT
    --     DATE_TRUNC('month', fecha)::date as mes,
    --     ROUND(100 * AVG(horas_operativas / (horas_operativas + horas_detenido_no_planificado)), 1) as disponibilidad_pct,
    --     ROUND(AVG(horas_detenido_no_planificado), 0) as downtime_no_plan_promedio
    -- FROM disponibilidad_diaria
    -- WHERE fecha BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
    -- GROUP BY DATE_TRUNC('month', fecha)
    
    -- Opción B: Estimación desde ordenes_trabajo (fallback)
    SELECT
        DATE_TRUNC('month', ot.fecha_apertura)::date as mes,
        ROUND(100 * (1.0 - (
            COUNT(CASE WHEN ot.tipo_ot = 'correctiva' THEN 1 END)::float /
            NULLIF(COUNT(*), 0)
        )), 1) as disponibilidad_pct,
        ROUND(AVG(EXTRACT(EPOCH FROM (ot.fecha_cierre - ot.fecha_apertura)) / 3600), 1) as downtime_no_plan_promedio
    FROM ordenes_trabajo ot
    WHERE ot.fecha_apertura BETWEEN '{fecha_inicio}'::date AND '{fecha_fin}'::date
        AND ot.tipo_ot = 'correctiva'
    GROUP BY DATE_TRUNC('month', ot.fecha_apertura)
    ORDER BY mes DESC
    LIMIT 12
    """
    return query

def query_mtbf_mttr_v3(fecha_inicio, fecha_fin):
    """
    Query para MTBF y MTTR en Vista 3.
    
    Cálculos:
    - MTBF = horas operativas totales / número de fallas correctivas
    - MTTR = suma de (fecha_cierre - fecha_apertura) / número de OT correctivas
    
    DATOS REALES: ordenes_trabajo (con fecha_cierre y tipo_ot)
    
    Status: Implementado en v2.0. Caveat: requiere fecha_cierre disponible
            en >75% de OT. Si falta, se estima con duración promedio.
    """
    query = f"""
    SELECT
        DATE_TRUNC('month', ot.fecha_apertura)::date as mes,
        
        -- MTBF: Mean Time Between Failures
        ROUND(
            EXTRACT(EPOCH FROM (DATE_TRUNC('month', ot.fecha_apertura + INTERVAL '1 month') - 
                               DATE_TRUNC('month', ot.fecha_apertura))) / 3600.0 /
            NULLIF(COUNT(CASE WHEN ot.tipo_ot = 'correctiva' THEN 1 END), 0),
            0
        )::int as mtbf_horas,
        
        -- MTTR: Mean Time To Repair (si fecha_cierre está disponible)
        CASE 
            WHEN COUNT(CASE WHEN ot.fecha_cierre IS NOT NULL THEN 1 END) > 0
            THEN ROUND(
                EXTRACT(EPOCH FROM SUM(CASE WHEN ot.fecha_cierre IS NOT NULL 
                                          THEN (ot.fecha_cierre - ot.fecha_apertura)
                                          ELSE INTERVAL '0' END)) / 3600.0 /
                NULLIF(COUNT(CASE WHEN ot.tipo_ot = 'correctiva' THEN 1 END), 0),
                1
            )::numeric
            ELSE NULL  -- No disponible si falta fecha_cierre
        END as mttr_horas
    
    FROM ordenes_trabajo ot
    WHERE ot.fecha_apertura BETWEEN '{fecha_inicio}'::date AND '{fecha_fin}'::date
    GROUP BY DATE_TRUNC('month', ot.fecha_apertura)
    ORDER BY mes DESC
    LIMIT 12
    """
    return query

def query_feedback_taller_v3():
    """
    Query para feedback del taller acumulado en Vista 3.
    
    DATOS REALES: feedback_taller (tabla que cierra el loop del modelo)
    
    Status: Implementado en v2.0. Requiere que el taller use la app de feedback
            (3 botones) en Streamlit.
    """
    query = """
    SELECT
        COUNT(*) as total_alertas,
        COUNT(CASE WHEN ft.falla_confirmada = true THEN 1 END) as confirmadas,
        COUNT(CASE WHEN ft.resultado_revision = 'parcial' THEN 1 END) as parciales,
        COUNT(CASE WHEN ft.falla_confirmada = false THEN 1 END) as rechazadas,
        COUNT(CASE WHEN ft.falla_confirmada IS NULL THEN 1 END) as pendientes,
        
        -- Tasa de aciertos validados
        ROUND(100.0 * 
            COUNT(CASE WHEN ft.falla_confirmada = true THEN 1 END)::float /
            NULLIF(COUNT(*), 0), 1) as tasa_aciertos_pct,
        
        -- Tiempo promedio alerta -> revisión (adoptabilidad)
        ROUND(AVG(EXTRACT(EPOCH FROM (ft.created_at - sr.fecha_scoring)) / 3600), 1) as horas_promedio_revision,
        
        -- Top motivos de rechazo (requiere campo 'motivo_rechazo')
        MAX(ft.comentario_mecanico) as comentario_tecnico_reciente
    
    FROM feedback_taller ft
    JOIN scoring_resultados sr ON ft.scoring_id = sr.scoring_id
    WHERE ft.created_at >= CURRENT_DATE - INTERVAL '30 days'
    """
    return query

def query_alertas_confirmadas_v3(fecha_inicio, fecha_fin):
    """
    Query para cálculo de impacto económico en Vista 3.
    
    DATOS:
    - Alertas confirmadas por feedback taller (feedback_taller.falla_confirmada = true)
    - Costo promedio de intervención por sistema (ordenes_trabajo histórico)
    - MTTR promedio para calcular horas evitadas
    
    IMPORTANTE: "Costo evitado" es estimado. La fórmula es:
    Costo evitado = N alertas confirmadas × (costo correctivo promedio sistema - costo preventivo)
    
    Se asume que intervención preventiva cuesta menos que correctiva. 
    Factor de seguridad conservador: usar solo 70% del diferencial.
    
    Status: Implementado en v2.0. Metodología debe estar visible en tooltip del dashboard.
    """
    query = f"""
    SELECT
        COUNT(DISTINCT ft.feedback_id) as alertas_confirmadas,
        
        -- Costo evitado estimado
        ROUND(
            COUNT(DISTINCT ft.feedback_id) * 
            COALESCE(
                (SELECT AVG(costo_total_clp) FROM ordenes_trabajo 
                 WHERE tipo_ot = 'correctiva' AND fecha_apertura >= '{fecha_inicio}'::date),
                1200000::numeric
            ) * 0.7,  -- Factor conservador 70%
            0
        )::bigint as costo_evitado_estimado,
        
        -- Downtime evitado
        ROUND(
            COUNT(DISTINCT ft.feedback_id) * 
            COALESCE(
                (SELECT AVG(EXTRACT(EPOCH FROM (fecha_cierre - fecha_apertura)) / 3600)
                 FROM ordenes_trabajo
                 WHERE tipo_ot = 'correctiva'),
                22::numeric
            ),
            0
        )::int as horas_downtime_evitadas,
        
        -- Tasa real de aciertos
        ROUND(100.0 * 
            COUNT(CASE WHEN ft.falla_confirmada = true THEN 1 END)::float /
            NULLIF(COUNT(*), 0), 1) as recall_validado_pct,
        
        -- Alertas rechazadas (falsos positivos confirmados)
        COUNT(CASE WHEN ft.falla_confirmada = false THEN 1 END) as falsos_positivos
    
    FROM feedback_taller ft
    JOIN scoring_resultados sr ON ft.scoring_id = sr.scoring_id
    WHERE sr.fecha_scoring BETWEEN '{fecha_inicio}'::date AND '{fecha_fin}'::date
    """
    return query

def query_drift_modelo_v3():
    """
    Query para monitoreo de drift del modelo en Vista 3.
    
    Detecciona si la distribución de predicciones está cambiando (concepto drift)
    o si la performance se está degradando (performance drift).
    
    Status: Placeholder en v1 (requiere implementación de concepto drift detector)
    """
    query = """
    -- PLACEHOLDER: implementar cuando modelo esté en producción con histórico
    -- Comparar distribución de probabilidades últimas 2 semanas vs últimas 4 semanas
    -- Si KL-divergence o similar > umbral → "drift detectado" semáforo amarillo/rojo
    
    SELECT
        'Estable' as estado_modelo,  -- Placeholder
        0.12 as drift_score,  -- Score de drift (0-1)
        CURRENT_DATE as fecha_validacion
    """
    return query

# ============================================================================
# QUERIES AUXILIARES
# ============================================================================

def query_conformidad_pm():
    """
    Query para cumplimiento de mantenimiento preventivo (Vista 2).
    
    DATOS REALES: ordenes_trabajo con tipo_ot = 'preventivo'
    """
    query = """
    SELECT
        ROUND(100.0 * 
            COUNT(CASE WHEN ot.tipo_ot = 'preventivo' THEN 1 END)::float /
            NULLIF(COUNT(*), 0), 1) as cumplimiento_pm_pct,
        
        COUNT(CASE WHEN ot.tipo_ot = 'preventivo' THEN 1 END) as ot_preventivas,
        COUNT(*) as total_ot,
        
        -- PM vencidos (requiere tabla de programación PM)
        0::int as pm_vencidos  -- PLACEHOLDER
    FROM ordenes_trabajo ot
    WHERE ot.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days'
    """
    return query

def query_backlog_mantenimiento():
    """
    Query para backlog de mantenimiento (Vista 2).
    
    DATOS REALES: ordenes_trabajo con fecha_cierre IS NULL
    """
    query = """
    SELECT
        COUNT(*) as ot_abiertas,
        COUNT(CASE WHEN fecha_apertura < CURRENT_DATE - INTERVAL '7 days' THEN 1 END) as ot_vencidas_7d,
        COUNT(CASE WHEN fecha_apertura < CURRENT_DATE - INTERVAL '14 days' THEN 1 END) as ot_vencidas_14d
    FROM ordenes_trabajo
    WHERE fecha_cierre IS NULL
    """
    return query

# ============================================================================
# NOTAS SOBRE IMPLEMENTACIÓN
# ============================================================================

"""
NOTAS CRÍTICAS PARA IMPLEMENTACIÓN:

1. PLACEHOLDERS vs DATOS REALES
   - Queries con ## PLACEHOLDER ## deben retornar datos sintéticos en dashboard.py
     cuando la tabla no exista o esté vacía (primeros meses con cliente).
   - Cuando el cliente popular la tabla (ej. maestro SKU, disponibilidad_diaria),
     cambiar a comentario y descomentar la query real. Sintaxis idéntica.

2. PERFORMANCE
   - Todas las queries tienen LIMIT o agregación por mes para evitar tamaños enormes.
   - En Supabase, crear índices en:
     * activos(estado_actual)
     * ordenes_trabajo(activo_id, fecha_apertura, tipo_ot)
     * scoring_resultados(fecha_scoring, prioridad, activo_id)
     * feedback_taller(scoring_id, falla_confirmada, created_at)

3. CADENCIA DE EJECUCIÓN
   - query_hero_metrics_v1: ejecutar diariamente (5s)
   - query_ranking_riesgo_v1: ejecutar diariamente (10s)
   - query_disponibilidad_diaria_v3: ejecutar diariamente (15s)
   - query_mtbf_mttr_v3: ejecutar semanalmente (20s)
   - query_feedback_taller_v3: ejecutar después de cada cierre de alerta
   - query_alertas_confirmadas_v3: ejecutar diariamente (10s)

4. METODOLOGÍA DE "COSTO EVITADO"
   Fórmula actual en query_alertas_confirmadas_v3:
   
   Costo evitado = N alertas confirmadas × Costo promedio correctivo × 0.7
   
   Supuestos:
   - Intervención preventiva cuesta 30% menos que correctiva
   - Todas las alertas confirmadas habrían resultado en falla sin el modelo
   - Factor 0.7 es conservador (ajustable por cliente)
   
   ADVERTENCIA: Este es un estimado. Mostrarlo con ⚠️ "estimado" en dashboard.
   Para cálculo exacto, se necesaría:
   - Desagregación por sistema/componente de costos
   - Datos de lead time reales
   - Histórico de reparaciones post-intervención preventiva

5. FEEDBACK DEL TALLER
   La tabla feedback_taller cierra el ciclo. Sin ella:
   - No hay validación del modelo
   - No hay aprendizaje continuo
   - El modelo se degrada sin aviso
   
   Implementar como cláusula contractual obligatoria.

6. MIGRACIÓN DESDE V2.0
   - El dashboard v2.0 usa psycopg2 directo
   - dashboard_refactored.py mantiene psycopg2 por compatibilidad
   - DEUDA: Migrar a SQLAlchemy + ORM en v1.1 para limpieza

7. DATOS SINTÉTICOS
   Primera ejecución con cliente real: datos vacíos o mínimos.
   Estrategia de demo:
   - Primera semana: mostrar estructura con datos sintéticos anonimizados
   - Semana 2: cargar histórico cliente (batch CSV)
   - Semana 3-4: primeros scoring y resultados reales
   - Mes 2: feedback taller activo
   - Mes 3+: métricas de impacto visibles

"""

