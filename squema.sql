-- =================================================================
-- BAITECK PdM FLOTAS - ESQUEMA COMPLETO CON DATOS INICIALES
-- Listo para producción
-- =================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==================== 1. MAESTRO DE ACTIVOS ====================
CREATE TABLE IF NOT EXISTS activos (
    activo_id TEXT PRIMARY KEY,
    patente TEXT UNIQUE NOT NULL,
    marca TEXT,
    modelo TEXT,
    anio_fabricacion INT,
    fecha_alta_flota DATE,
    tipo_vehiculo TEXT,
    motor_tipo TEXT,
    estado_actual TEXT DEFAULT 'operativo',
    odometro_km NUMERIC DEFAULT 0,
    horometro_h NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================== 2. ORDENES DE TRABAJO ====================
CREATE TABLE IF NOT EXISTS ordenes_trabajo (
    ot_id TEXT PRIMARY KEY,
    activo_id TEXT NOT NULL REFERENCES activos(activo_id),
    fecha_apertura TIMESTAMPTZ NOT NULL,
    fecha_cierre TIMESTAMPTZ,
    tipo_ot TEXT NOT NULL,
    sistema TEXT,
    componente TEXT,
    modo_falla TEXT,
    descripcion_falla TEXT,
    odometro_km NUMERIC,
    horometro_h NUMERIC,
    taller_id TEXT,
    costo_total_clp NUMERIC,
    responsable TEXT,
    observaciones TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ot_activo_fecha ON ordenes_trabajo(activo_id, fecha_apertura);
CREATE INDEX IF NOT EXISTS idx_ot_tipo_sistema ON ordenes_trabajo(tipo_ot, sistema);
CREATE INDEX IF NOT EXISTS idx_ot_estado ON ordenes_trabajo(fecha_cierre) WHERE fecha_cierre IS NULL;

-- ==================== 3. REPUESTOS CONSUMIDOS ====================
CREATE TABLE IF NOT EXISTS repuestos_consumidos (
    consumo_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ot_id TEXT NOT NULL REFERENCES ordenes_trabajo(ot_id) ON DELETE CASCADE,
    sku TEXT,
    descripcion_repuesto TEXT,
    cantidad NUMERIC,
    costo_unitario_clp NUMERIC,
    fue_compra_urgencia BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================== 4. TAXONOMÍA DE FALLAS ====================
CREATE TABLE IF NOT EXISTS taxonomia_fallas (
    taxonomia_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sistema TEXT NOT NULL,
    componente TEXT NOT NULL,
    modo_falla TEXT NOT NULL,
    descripcion_estandar TEXT,
    palabras_clave TEXT,
    activo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(sistema, componente, modo_falla)
);

-- ==================== 5. FEATURES POR ACTIVO Y FECHA ====================
CREATE TABLE IF NOT EXISTS features_activo_fecha (
    activo_id TEXT NOT NULL REFERENCES activos(activo_id),
    fecha_corte DATE NOT NULL,
    horizonte_dias INT NOT NULL DEFAULT 30,
    edad_dias NUMERIC,
    edad_anos NUMERIC,
    odometro_actual NUMERIC,
    horometro_actual NUMERIC,
    km_dia_promedio NUMERIC,
    horas_dia_promedio NUMERIC,
    dias_desde_ultima_ot NUMERIC,
    count_ot_30d NUMERIC,
    count_ot_90d NUMERIC,
    count_ot_180d NUMERIC,
    count_correctivas_30d NUMERIC,
    count_correctivas_90d NUMERIC,
    count_correctivas_180d NUMERIC,
    costo_total_30d NUMERIC,
    costo_total_90d NUMERIC,
    costo_total_180d NUMERIC,
    mtbf_180d NUMERIC,
    dias_ult_correctiva_motor NUMERIC,
    dias_ult_correctiva_frenos NUMERIC,
    dias_ult_correctiva_transmision NUMERIC,
    target INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY(activo_id, fecha_corte, horizonte_dias)
);

CREATE INDEX IF NOT EXISTS idx_features_fecha ON features_activo_fecha(fecha_corte);
CREATE INDEX IF NOT EXISTS idx_features_activo ON features_activo_fecha(activo_id);

-- ==================== 6. REGISTRO DE MODELOS ====================
CREATE TABLE IF NOT EXISTS modelos_registro (
    modelo_version TEXT PRIMARY KEY,
    algoritmo TEXT NOT NULL,
    fecha_entrenamiento TIMESTAMPTZ DEFAULT NOW(),
    horizonte_dias INT,
    feature_cols JSONB,
    metricas JSONB,
    umbral_decision NUMERIC,
    ruta_artefacto TEXT,
    notas TEXT,
    activo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================== 7. SCORING/RESULTADOS ====================
CREATE TABLE IF NOT EXISTS scoring_resultados (
    scoring_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activo_id TEXT NOT NULL REFERENCES activos(activo_id),
    fecha_scoring DATE NOT NULL,
    horizonte_dias INT NOT NULL DEFAULT 30,
    probabilidad_falla NUMERIC NOT NULL,
    prediccion INT NOT NULL,
    prioridad TEXT NOT NULL,
    modelo_version TEXT REFERENCES modelos_registro(modelo_version),
    explicabilidad JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(activo_id, fecha_scoring, horizonte_dias, modelo_version)
);

CREATE INDEX IF NOT EXISTS idx_scoring_fecha_prioridad ON scoring_resultados(fecha_scoring, prioridad);
CREATE INDEX IF NOT EXISTS idx_scoring_activo ON scoring_resultados(activo_id);
CREATE INDEX IF NOT EXISTS idx_scoring_activo_fecha ON scoring_resultados(activo_id, fecha_scoring);

-- ==================== 8. ALERTAS ACTIVAS ====================
CREATE TABLE IF NOT EXISTS alertas (
    alerta_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scoring_id UUID REFERENCES scoring_resultados(scoring_id),
    activo_id TEXT NOT NULL REFERENCES activos(activo_id),
    fecha_alerta TIMESTAMPTZ DEFAULT NOW(),
    prioridad TEXT NOT NULL,
    descripcion TEXT,
    leida BOOLEAN DEFAULT FALSE,
    resuelta BOOLEAN DEFAULT FALSE,
    fecha_resolucion TIMESTAMPTZ,
    accion_tomada TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alertas_estado ON alertas(leida, resuelta);
CREATE INDEX IF NOT EXISTS idx_alertas_activo ON alertas(activo_id);

-- ==================== 9. FEEDBACK DEL TALLER ====================
CREATE TABLE IF NOT EXISTS feedback_taller (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scoring_id UUID REFERENCES scoring_resultados(scoring_id),
    activo_id TEXT REFERENCES activos(activo_id),
    ot_id TEXT REFERENCES ordenes_trabajo(ot_id),
    fecha_alerta DATE,
    prioridad_modelo TEXT,
    accion_realizada TEXT,
    resultado_revision TEXT,
    falla_confirmada BOOLEAN,
    falsa_alarma BOOLEAN DEFAULT FALSE,
    comentario_mecanico TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_confirmada ON feedback_taller(falla_confirmada);

-- ==================== 10. AUDITORÍA DE CALIDAD ====================
CREATE TABLE IF NOT EXISTS auditoria_calidad_datos (
    auditoria_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha_auditoria TIMESTAMPTZ DEFAULT NOW(),
    fuente TEXT,
    total_registros INT,
    registros_validos INT,
    registros_invalidos INT,
    metricas JSONB,
    resultado TEXT,
    recomendaciones TEXT
);

-- ==================== 11. USUARIOS ====================
CREATE TABLE IF NOT EXISTS usuarios (
    usuario_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    rol TEXT,
    estado TEXT DEFAULT 'activo',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================== 12. LOGS DE AUDITORÍA ====================
CREATE TABLE IF NOT EXISTS audit_log (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id UUID REFERENCES usuarios(usuario_id),
    tabla_afectada TEXT,
    operacion TEXT,
    datos_anteriores JSONB,
    datos_nuevos JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- ==================== ÍNDICES ADICIONALES ====================
CREATE INDEX IF NOT EXISTS idx_activos_estado ON activos(estado_actual);

-- ==================== VISTAS ÚTILES ====================

CREATE OR REPLACE VIEW v_ultimas_predicciones AS
SELECT DISTINCT ON (s.activo_id)
    s.scoring_id,
    s.activo_id,
    a.patente,
    s.fecha_scoring,
    s.probabilidad_falla,
    s.prioridad,
    s.modelo_version
FROM scoring_resultados s
JOIN activos a ON s.activo_id = a.activo_id
ORDER BY s.activo_id, s.fecha_scoring DESC;

CREATE OR REPLACE VIEW v_alertas_pendientes AS
SELECT
    a.alerta_id,
    a.activo_id,
    ac.patente,
    a.prioridad,
    a.fecha_alerta,
    a.descripcion
FROM alertas a
JOIN activos ac ON a.activo_id = ac.activo_id
WHERE a.resuelta = FALSE
ORDER BY a.prioridad DESC, a.fecha_alerta DESC;

CREATE OR REPLACE VIEW v_metricas_modelo AS
SELECT
    m.modelo_version,
    m.algoritmo,
    m.fecha_entrenamiento,
    COUNT(f.feedback_id) as total_predicciones,
    SUM(CASE WHEN f.falla_confirmada = TRUE THEN 1 ELSE 0 END) as aciertos,
    ROUND(100.0 * SUM(CASE WHEN f.falla_confirmada = TRUE THEN 1 ELSE 0 END) / NULLIF(COUNT(f.feedback_id), 0), 2) as precision_porcentaje
FROM modelos_registro m
LEFT JOIN scoring_resultados s ON m.modelo_version = s.modelo_version
LEFT JOIN feedback_taller f ON s.scoring_id = f.scoring_id
GROUP BY m.modelo_version, m.algoritmo, m.fecha_entrenamiento;

-- ==================== DATOS INICIALES ====================
-- Taxonomía mínima de fallas según BAITECK

INSERT INTO taxonomia_fallas (sistema, componente, modo_falla, descripcion_estandar, palabras_clave)
VALUES 
  ('motor', 'aceite_motor', 'cambio_aceite', 'Cambio de aceite de motor', 'aceite,cambio aceite,lubricante'),
  ('motor', 'aceite_motor', 'fuga_aceite', 'Fuga de aceite de motor', 'fuga aceite,pierde aceite,filtracion'),
  ('motor', 'inyectores', 'obstruccion', 'Obstruccion de inyectores', 'inyector,inyectores,obstruido'),
  ('frenos', 'pastillas', 'desgaste', 'Desgaste de pastillas de freno', 'pastillas gastadas,cambio pastillas,desgaste freno'),
  ('frenos', 'discos', 'desgaste', 'Desgaste de discos de freno', 'disco freno,discos gastados'),
  ('transmision', 'caja_cambios', 'ruido', 'Ruido en caja de cambios', 'ruido caja,caja cambios'),
  ('electrico', 'bateria', 'descarga', 'Descarga de bateria', 'bateria descargada,no parte'),
  ('electrico', 'alternador', 'no_carga', 'Alternador no carga', 'alternador,no carga,carga bateria')
ON CONFLICT (sistema, componente, modo_falla) DO NOTHING;
