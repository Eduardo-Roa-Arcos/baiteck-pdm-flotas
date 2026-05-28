# BAITECK PDM Flotas - Documentación Completa de Base de Datos
## Versión Final - Esquema Completo

**Versión:** 2.0 (Esquema Completo)  
**Fecha de Generación:** 27 de Mayo de 2026  
**Base de Datos:** Supabase (PostgreSQL)  
**Total de Objetos:** 16 (14 tablas + 2 vistas)  
**Estado:** En Producción

---

## 📊 ÍNDICE EJECUTIVO

### Tablas de Negocio (14)
1. `activos` - Flota de vehículos
2. `ordenes_trabajo` - Mantenimiento histórico
3. `scoring_resultados` - Predicciones del modelo
4. `disponibilidad_diaria` - Disponibilidad operacional
5. `modelos_registro` - Versiones de modelos entrenados
6. `features_activo_fecha` - Features para ML
7. `feedback_taller` - Feedback del taller
8. `alertas` - Alertas operacionales
9. `repuestos_maestro` - Catálogo de repuestos
10. `repuestos_consumidos` - Repuestos usados
11. `taxonomia_fallas` - Clasificación de fallos
12. `usuarios` - Gestión de usuarios
13. `audit_log` - Auditoría de cambios
14. `auditoria_calidad_datos` - Control de calidad

### Vistas (2)
- `v_alertas_pendientes` - Alertas no resueltas
- `v_ultimas_predicciones` - Predicciones más recientes

---

## 📚 DICCIONARIO DETALLADO

### 1. `activos` - Flota de Vehículos
**Descripción:** Catálogo maestro de todos los vehículos en la flota  
**Tipo:** Dimensión  
**Registros esperados:** 5-1000+

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `activo_id` | TEXT | ✅ | - | ID único (ej: JSDX11) |
| `patente` | TEXT | ✅ | - | Placa (UNIQUE) |
| `marca` | TEXT | ❌ | - | Scania, Iveco, Volvo, etc. |
| `modelo` | TEXT | ❌ | - | P360, S500, etc. |
| `anio_fabricacion` | INTEGER | ❌ | - | Año de fabricación |
| `fecha_alta_flota` | DATE | ❌ | - | Cuándo entró a flota |
| `tipo_vehiculo` | TEXT | ❌ | - | Camión, Bus, etc. |
| `motor_tipo` | TEXT | ❌ | - | Diesel, Gas, etc. |
| `estado_actual` | TEXT | ❌ | 'operativo' | operativo, fuera_servicio, etc. |
| `odometro_km` | NUMERIC | ❌ | 0 | KM actuales |
| `horometro_h` | NUMERIC | ❌ | 0 | Horas de motor |
| `created_at` | TIMESTAMP TZ | ❌ | now() | Creación |
| `updated_at` | TIMESTAMP TZ | ❌ | now() | Última actualización |

**PK:** `activo_id`  
**UNIQUE:** `patente`  
**Índices:** `estado_actual`

---

### 2. `ordenes_trabajo` - Historial de Mantenimiento
**Descripción:** Todas las intervenciones: preventivas, correctivas, etc.  
**Tipo:** Hechos  
**Registros esperados:** 100+

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `ot_id` | TEXT | ✅ | - | ID único de orden |
| `activo_id` | TEXT | ✅ | - | FK → activos |
| `tipo_ot` | TEXT | ❌ | - | correctiva, preventiva, predictiva, emergency |
| `sistema` | TEXT | ❌ | - | Motor, Frenos, Transmisión, etc. |
| `componente` | TEXT | ❌ | - | Bomba, Sensor, etc. |
| `descripcion` | TEXT | ❌ | - | Detalle de la intervención |
| `fecha_apertura` | TIMESTAMP | ✅ | - | Cuándo se abrió |
| `fecha_cierre` | TIMESTAMP | ❌ | - | Cuándo se cerró (NULL=abierta) |
| `odometro_km` | NUMERIC | ❌ | - | KM en momento OT |
| `duracion_horas` | NUMERIC | ❌ | - | Duración en horas |
| `costo_estimado` | NUMERIC | ❌ | - | Costo estimado |
| `costo_real` | NUMERIC | ❌ | - | Costo ejecutado |
| `prioridad` | TEXT | ❌ | - | Alta, Media, Baja, etc. |

**PK:** `ot_id`  
**FK:** `activo_id` → activos  
**Índices:** 
- `activo_id, fecha_apertura`
- `tipo_ot, sistema`
- `fecha_cierre` (WHERE NULL)

---

### 3. `scoring_resultados` - Predicciones del Modelo ML
**Descripción:** Todas las predicciones generadas por el modelo  
**Tipo:** Hechos  
**Registros esperados:** 1000+

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `scoring_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `activo_id` | TEXT | ✅ | - | FK → activos |
| `fecha_scoring` | TIMESTAMP | ✅ | - | Cuándo se generó |
| `modelo_version` | TEXT | ✅ | - | v1_xgboost, v2_xgboost, etc. |
| `horizonte_dias` | INTEGER | ✅ | - | 7, 30 o 90 días |
| `probabilidad_falla` | NUMERIC | ✅ | - | Probabilidad 0-1 |
| `prediccion` | BOOLEAN | ❌ | - | Binario: sí/no falla |
| `prioridad` | TEXT | ✅ | - | P1_critica, P2_alta, P3_media, P4_baja |
| `sistema_en_riesgo` | TEXT | ❌ | - | Sistema identificado en riesgo |
| `dias_desde_ultima_ot` | INTEGER | ❌ | - | Contexto temporal |
| `odometro_actual` | NUMERIC | ❌ | - | KM en fecha scoring |
| `dias_ult_correctiva_motor` | NUMERIC | ❌ | - | Días desde última falla motor |
| `dias_ult_correctiva_frenos` | NUMERIC | ❌ | - | Días desde última falla frenos |
| `dias_ult_correctiva_transmision` | NUMERIC | ❌ | - | Días desde última falla transmisión |
| `created_at` | TIMESTAMP TZ | ❌ | now() | Creación |

**PK:** `scoring_id`  
**FK:** `activo_id` → activos  
**UNIQUE:** `(activo_id, fecha_scoring, horizonte_dias, modelo_version)`  
**Índices:**
- `activo_id, fecha_scoring`
- `activo_id`
- `fecha_scoring, prioridad`

---

### 4. `disponibilidad_diaria` - Disponibilidad Operacional
**Descripción:** Disponibilidad calculada por activo/día  
**Tipo:** Agregación  
**Registros esperados:** 1000+ (N_activos × 180 días)

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `activo_id` | TEXT | ✅ | - | FK → activos |
| `fecha` | DATE | ✅ | - | Fecha de cálculo |
| `horas_operativas` | NUMERIC | ❌ | - | Horas operativo (máx 24) |
| `horas_detenido_planificado` | NUMERIC | ❌ | - | Parado por PM |
| `horas_detenido_no_planificado` | NUMERIC | ❌ | - | Parado por falla |
| `fuente` | TEXT | ❌ | 'inferido' | inferido, real, predicho |
| `created_at` | TIMESTAMP | ❌ | now() | Creación |

**PK:** `(activo_id, fecha)` - Composite  
**FK:** `activo_id` → activos  
**Índices:**
- `activo_id, fecha`
- `fecha DESC`
- `activo_id`

**Fórmula de Disponibilidad:**
```
Disponibilidad % = (horas_operativas / 24) × 100
MTBF = SUM(horas_operativas) / N_correctivas
```

---

### 5. `modelos_registro` - Versiones de Modelos
**Descripción:** Auditoría y registro de versiones de modelos ML  
**Tipo:** Dimensión (SCD Tipo 2)  
**Registros esperados:** 10-50

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `modelo_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `version` | TEXT | ✅ | - | v1_xgboost_20260527 (UNIQUE) |
| `nombre_archivo` | TEXT | ✅ | - | Ruta del archivo |
| `fecha_entrenamiento` | DATE | ✅ | - | Cuándo se entrenó |
| `fecha_creacion` | TIMESTAMP TZ | ❌ | now() | Cuándo se registró |
| `auc_score` | NUMERIC | ❌ | - | AUC-ROC (0-1) |
| `precision` | NUMERIC | ❌ | - | Precisión |
| `recall` | NUMERIC | ❌ | - | Recall |
| `f1_score` | NUMERIC | ❌ | - | F1-Score |
| `n_samples_train` | INTEGER | ❌ | - | N muestras training |
| `n_features` | INTEGER | ❌ | - | N features usadas |
| `features_utilizadas` | ARRAY | ❌ | - | Lista de features |
| `hiperparametros` | JSONB | ❌ | - | Config en JSON |
| `estado` | TEXT | ❌ | 'entrenado' | entrenado, validando, rechazado, producción |
| `es_activo` | BOOLEAN | ❌ | false | ¿En uso actualmente? |
| `entrenado_por` | TEXT | ❌ | 'sistema' | Usuario o proceso |

**PK:** `modelo_id`  
**UNIQUE:** `version`  
**Índices:**
- `es_activo`
- `fecha_creacion DESC`

---

### 6. `features_activo_fecha` - Features para Entrenamientos ML
**Descripción:** Características calculadas por activo/fecha/horizonte  
**Tipo:** Hechos  
**Registros esperados:** 10000+

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `activo_id` | TEXT | ✅ | - | FK → activos |
| `fecha_corte` | DATE | ✅ | - | Fecha de cálculo |
| `horizonte_dias` | INTEGER | ✅ | 30 | 7, 30 o 90 días |
| `edad_dias` | NUMERIC | ❌ | - | Antigüedad en días |
| `edad_anos` | NUMERIC | ❌ | - | Antigüedad en años |
| `odometro_actual` | NUMERIC | ❌ | - | KM acumulados |
| `horometro_actual` | NUMERIC | ❌ | - | Horas acumuladas |
| `km_dia_promedio` | NUMERIC | ❌ | - | Promedio km/día |
| `horas_dia_promedio` | NUMERIC | ❌ | - | Promedio horas/día |
| `dias_desde_ultima_ot` | NUMERIC | ❌ | - | Días desde última intervención |
| `count_ot_30d` | NUMERIC | ❌ | - | Total OT 30d |
| `count_ot_90d` | NUMERIC | ❌ | - | Total OT 90d |
| `count_ot_180d` | NUMERIC | ❌ | - | Total OT 180d |
| `count_correctivas_30d` | NUMERIC | ❌ | - | OT correctivas 30d |
| `count_correctivas_90d` | NUMERIC | ❌ | - | OT correctivas 90d |
| `count_correctivas_180d` | NUMERIC | ❌ | - | OT correctivas 180d |
| `costo_total_30d` | NUMERIC | ❌ | - | Costo acumulado 30d |
| `costo_total_90d` | NUMERIC | ❌ | - | Costo acumulado 90d |
| `costo_total_180d` | NUMERIC | ❌ | - | Costo acumulado 180d |
| `mtbf_180d` | NUMERIC | ❌ | - | MTBF 180d |
| `dias_ult_correctiva_motor` | NUMERIC | ❌ | - | Días desde falla motor |
| `dias_ult_correctiva_frenos` | NUMERIC | ❌ | - | Días desde falla frenos |
| `dias_ult_correctiva_transmision` | NUMERIC | ❌ | - | Días desde falla transmisión |
| `target` | INTEGER | ❌ | - | Variable objetivo (1=falla, 0=ok) |
| `created_at` | TIMESTAMP TZ | ❌ | now() | Creación |

**PK:** `(activo_id, fecha_corte, horizonte_dias)` - Composite  
**FK:** `activo_id` → activos  
**Índices:**
- `activo_id`
- `fecha_corte`

---

### 7. `feedback_taller` - Feedback de Mantenimiento
**Descripción:** Feedback del taller sobre predicciones  
**Tipo:** Hechos  
**Registros esperados:** 100+

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `feedback_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `scoring_id` | UUID | ❌ | - | FK → scoring_resultados |
| `activo_id` | TEXT | ❌ | - | FK → activos |
| `ot_id` | TEXT | ❌ | - | FK → ordenes_trabajo |
| `fecha_alerta` | DATE | ❌ | - | Cuándo se generó alerta |
| `prioridad_modelo` | TEXT | ❌ | - | Prioridad predicha |
| `accion_realizada` | TEXT | ❌ | - | Qué se hizo |
| `resultado_revision` | TEXT | ❌ | - | Hallazgos |
| `falla_confirmada` | BOOLEAN | ❌ | - | ¿Se confirmó falla? |
| `falsa_alarma` | BOOLEAN | ❌ | false | ¿Fue falsa alarma? |
| `comentario_mecanico` | TEXT | ❌ | - | Comentario libre |
| `created_at` | TIMESTAMP TZ | ❌ | now() | Creación |

**PK:** `feedback_id`  
**FK:** 
- `scoring_id` → scoring_resultados
- `activo_id` → activos
- `ot_id` → ordenes_trabajo  
**Índices:**
- `falla_confirmada`

---

### 8. `alertas` - Alertas Operacionales
**Descripción:** Alertas generadas para operadores  
**Tipo:** Hechos  
**Registros esperados:** 500+

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `alerta_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `scoring_id` | UUID | ❌ | - | FK → scoring_resultados |
| `activo_id` | TEXT | ✅ | - | FK → activos |
| `fecha_alerta` | TIMESTAMP TZ | ❌ | now() | Cuándo se generó |
| `prioridad` | TEXT | ✅ | - | P1_critica, P2_alta, P3_media, P4_baja |
| `descripcion` | TEXT | ❌ | - | Descripción |
| `leida` | BOOLEAN | ❌ | false | ¿Leída por operador? |
| `resuelta` | BOOLEAN | ❌ | false | ¿Resuelta? |
| `fecha_resolucion` | TIMESTAMP TZ | ❌ | - | Cuándo se resolvió |
| `accion_tomada` | TEXT | ❌ | - | Qué se hizo |
| `created_at` | TIMESTAMP TZ | ❌ | now() | Creación |

**PK:** `alerta_id`  
**FK:**
- `scoring_id` → scoring_resultados
- `activo_id` → activos  
**Índices:**
- `activo_id`
- `leida, resuelta`

---

### 9. `repuestos_maestro` - Catálogo de Repuestos
**Descripción:** Catálogo maestro de repuestos y componentes  
**Tipo:** Dimensión

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `sku` | TEXT | ✅ | - | SKU único (PK) |
| `sistema` | TEXT | ❌ | - | Sistema/categoría |
| `componente` | TEXT | ❌ | - | Nombre componente |
| `descripcion` | TEXT | ❌ | - | Descripción detallada |
| `proveedor` | TEXT | ❌ | - | Proveedor |
| `costo_unitario` | NUMERIC | ❌ | - | Costo |
| `criticidad` | TEXT | ❌ | - | Alta, Media, Baja |
| `activo` | BOOLEAN | ❌ | true | ¿Disponible? |

**PK:** `sku`  
**Índices:**
- `sistema`
- `criticidad`

---

### 10. `repuestos_consumidos` - Repuestos Usados
**Descripción:** Registro de repuestos consumidos en OT  
**Tipo:** Hechos

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `consumo_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `ot_id` | TEXT | ✅ | - | FK → ordenes_trabajo |
| `sku` | TEXT | ✅ | - | FK → repuestos_maestro |
| `cantidad` | INTEGER | ✅ | - | Cantidad usada |
| `costo_total` | NUMERIC | ❌ | - | Costo total (cantidad × precio) |
| `fecha_consumo` | TIMESTAMP | ❌ | now() | Cuándo se consumió |

**PK:** `consumo_id`  
**FK:**
- `ot_id` → ordenes_trabajo
- `sku` → repuestos_maestro

---

### 11. `taxonomia_fallas` - Clasificación Estándar de Fallos
**Descripción:** Catálogo estándar de clasificación de fallos  
**Tipo:** Dimensión

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `taxonomia_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `sistema` | TEXT | ✅ | - | Sistema (Motor, Frenos, etc.) |
| `componente` | TEXT | ✅ | - | Componente |
| `modo_falla` | TEXT | ✅ | - | Modo de falla |
| `descripcion_estandar` | TEXT | ❌ | - | Descripción estándar |
| `palabras_clave` | TEXT | ❌ | - | Keywords para clasificación NLP |
| `activo` | BOOLEAN | ❌ | true | ¿Vigente? |
| `created_at` | TIMESTAMP TZ | ❌ | now() | Creación |

**PK:** `taxonomia_id`  
**UNIQUE:** `(sistema, componente, modo_falla)`  
**Índices:** (ninguno adicional)

---

### 12. `usuarios` - Gestión de Usuarios
**Descripción:** Usuarios del sistema BAITECK  
**Tipo:** Dimensión

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `usuario_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `nombre` | TEXT | ✅ | - | Nombre completo |
| `email` | TEXT | ✅ | - | Email (UNIQUE) |
| `rol` | TEXT | ❌ | - | admin, mecanico, operador, analista |
| `estado` | TEXT | ❌ | 'activo' | activo, inactivo, suspendido |
| `created_at` | TIMESTAMP TZ | ❌ | now() | Creación |
| `updated_at` | TIMESTAMP TZ | ❌ | now() | Última actualización |

**PK:** `usuario_id`  
**UNIQUE:** `email`

---

### 13. `audit_log` - Auditoría General
**Descripción:** Trazabilidad de cambios en BD  
**Tipo:** Hechos

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `log_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `usuario_id` | UUID | ❌ | - | FK → usuarios |
| `tabla_afectada` | TEXT | ❌ | - | Tabla modificada |
| `operacion` | TEXT | ❌ | - | INSERT, UPDATE, DELETE |
| `datos_anteriores` | JSONB | ❌ | - | Valores previos |
| `datos_nuevos` | JSONB | ❌ | - | Valores nuevos |
| `timestamp` | TIMESTAMP TZ | ❌ | now() | Cuándo ocurrió |

**PK:** `log_id`  
**FK:** `usuario_id` → usuarios

---

### 14. `auditoria_calidad_datos` - Control de Calidad
**Descripción:** Auditoría de integridad de datos  
**Tipo:** Hechos

| Campo | Tipo | ✅ | Default | Descripción |
|-------|------|:--:|---------|-------------|
| `auditoria_id` | UUID | ✅ | gen_random_uuid() | ID único |
| `fecha_auditoria` | TIMESTAMP TZ | ❌ | now() | Cuándo se ejecutó |
| `fuente` | TEXT | ❌ | - | Origen auditado |
| `total_registros` | INTEGER | ❌ | - | Total procesados |
| `registros_validos` | INTEGER | ❌ | - | Válidos |
| `registros_invalidos` | INTEGER | ❌ | - | Con errores |
| `metricas` | JSONB | ❌ | - | Métricas detalladas |
| `resultado` | TEXT | ❌ | - | PASS, FAIL, WARNING |
| `recomendaciones` | TEXT | ❌ | - | Acciones recomendadas |

**PK:** `auditoria_id`

---

## 👁️ VISTAS

### V1. `v_alertas_pendientes` - Alertas no Resueltas
**Propósito:** Vista para operadores: alertas sin resolver  
**Columns:**
- `alerta_id` (UUID)
- `activo_id` (TEXT)
- `patente` (TEXT)
- `prioridad` (TEXT)
- `fecha_alerta` (TIMESTAMP TZ)
- `descripcion` (TEXT)

**Query subyacente:** Esperado → Alertas donde `resuelta = false`

---

### V2. `v_ultimas_predicciones` - Últimas Predicciones
**Propósito:** Vista para analistas: predicciones más recientes  
**Columns:**
- `scoring_id` (UUID)
- `activo_id` (TEXT)
- `patente` (TEXT)
- `fecha_scoring` (DATE)
- `probabilidad_falla` (NUMERIC)
- `prioridad` (TEXT)
- `modelo_version` (TEXT)

**Query subyacente:** Esperado → Último scoring por activo/horizonte

---

## 🔗 RELACIONES Y RESTRICCIONES

### Matriz de Relaciones

```
activos (1) ←→ (*) ordenes_trabajo
activos (1) ←→ (*) scoring_resultados
activos (1) ←→ (*) disponibilidad_diaria
activos (1) ←→ (*) features_activo_fecha
activos (1) ←→ (*) feedback_taller
activos (1) ←→ (*) alertas

ordenes_trabajo (1) ←→ (*) repuestos_consumidos
ordenes_trabajo (1) ←→ (*) feedback_taller

repuestos_maestro (1) ←→ (*) repuestos_consumidos

scoring_resultados (1) ←→ (*) alertas
scoring_resultados (1) ←→ (*) feedback_taller

modelos_registro (1) ←→ (*) scoring_resultados

usuarios (1) ←→ (*) audit_log
```

### Restricciones de Integridad

| Tabla | Restricción | Descripción |
|-------|---|---|
| `modelos_registro` | UNIQUE(`version`) | Una versión por modelo |
| `activos` | UNIQUE(`patente`) | Una patente por vehículo |
| `usuarios` | UNIQUE(`email`) | Un email por usuario |
| `scoring_resultados` | UNIQUE(`activo_id, fecha_scoring, horizonte_dias, modelo_version`) | Un score por combinación |
| `disponibilidad_diaria` | UNIQUE(`activo_id, fecha`) | Una disponibilidad por día/activo |
| `taxonomia_fallas` | UNIQUE(`sistema, componente, modo_falla`) | Una clasificación única |

---

## 📑 ÍNDICES COMPLETOS

### Por Tabla

**activos:**
- PRIMARY: `activo_id`
- UNIQUE: `patente`
- INDEX: `estado_actual`

**ordenes_trabajo:**
- PRIMARY: `ot_id`
- INDEX: `activo_id, fecha_apertura`
- INDEX: `tipo_ot, sistema`
- INDEX: `fecha_cierre` (WHERE NULL)

**scoring_resultados:**
- PRIMARY: `scoring_id`
- UNIQUE: `(activo_id, fecha_scoring, horizonte_dias, modelo_version)`
- INDEX: `activo_id, fecha_scoring`
- INDEX: `activo_id`
- INDEX: `fecha_scoring, prioridad`

**disponibilidad_diaria:**
- PRIMARY: `(activo_id, fecha)` Composite
- INDEX: `fecha DESC`
- INDEX: `activo_id`

**modelos_registro:**
- PRIMARY: `modelo_id`
- UNIQUE: `version`
- INDEX: `es_activo`
- INDEX: `fecha_creacion DESC`

**features_activo_fecha:**
- PRIMARY: `(activo_id, fecha_corte, horizonte_dias)` Composite
- INDEX: `activo_id`
- INDEX: `fecha_corte`

**feedback_taller:**
- PRIMARY: `feedback_id`
- INDEX: `falla_confirmada`

**alertas:**
- PRIMARY: `alerta_id`
- INDEX: `activo_id`
- INDEX: `leida, resuelta`

**repuestos_maestro:**
- PRIMARY: `sku`
- INDEX: `sistema`
- INDEX: `criticidad`

**usuarios:**
- PRIMARY: `usuario_id`
- UNIQUE: `email`

---

## 🏗️ CONVENCIONES

### Nomenclatura
| Elemento | Patrón | Ejemplo |
|----------|--------|---------|
| Tabla | snake_case | ordenes_trabajo |
| Columna | snake_case | fecha_apertura |
| PK | {tabla}_id | activo_id |
| FK | {tabla_ref}_id | activo_id |
| Booleano | es_* | es_activo |
| Timestamp | *_at | created_at |
| Date | fecha_* | fecha_apertura |

### Tipos de Datos
| Uso | Tipo | Ejemplo |
|-----|------|---------|
| IDs UUID | UUID | alerta_id |
| Códigos cortos | TEXT | activo_id, ot_id |
| Decimales | NUMERIC | probabilidad_falla |
| Enteros | INTEGER | n_features |
| Fechas | DATE | fecha_apertura |
| Timestamps | TIMESTAMP TZ | created_at |
| Booleanos | BOOLEAN | es_activo |
| JSON | JSONB | hiperparametros |
| Listas | ARRAY | features_utilizadas |

### Defaults Estándar
- `created_at`: `now()`
- `updated_at`: `now()`
- `es_activo`: `false`
- `estado_actual`: `'operativo'`
- `leida`: `false`
- `fuente`: `'inferido'`

---

## 📊 ESTADÍSTICAS ESPERADAS

| Tabla | Registros Esperados | Crecimiento |
|-------|---|---|
| activos | 5-1000 | Lento |
| ordenes_trabajo | 100+ | Lineal (5-10/día) |
| scoring_resultados | 1000+ | Lineal (10-100/día) |
| disponibilidad_diaria | 1000+ | Lineal (5-10/día) |
| features_activo_fecha | 10000+ | Por horizonte/reentrenamiento |
| feedback_taller | 100+ | Según uso |
| alertas | 500+ | Según modelo |
| modelos_registro | 10-50 | Bajo |
| usuarios | 5-100 | Muy bajo |
| audit_log | 10000+ | Alto |

---

## 🔐 SEGURIDAD Y ACCESO

### Roles Recomendados

| Rol | Acceso |
|-----|--------|
| `admin` | Todo (CREATE, ALTER, DROP) |
| `analyst` | SELECT todo, INSERT en feedback_taller |
| `mechanic` | SELECT activos, ordenes_trabajo, feedback_taller; INSERT/UPDATE ordenes_trabajo |
| `operator` | SELECT alertas, scoring_resultados; UPDATE alertas |
| `system` | SELECT todo (para scripts) |

---

## ✅ CHECKLIST DE VALIDACIÓN

- [ ] Todas las PK definidas
- [ ] Todas las FK con restricciones
- [ ] Índices en columnas consultadas frecuentemente
- [ ] Campos NOT NULL donde corresponde
- [ ] Defaults apropiados
- [ ] Auditoría (created_at, updated_at)
- [ ] Comentarios en BD
- [ ] Políticas de retención definidas
- [ ] Backups configurados
- [ ] Monitoreo activo

---

## 📞 MANTENIMIENTO

**Última actualización:** 27 de Mayo de 2026  
**Responsable:** Eduardo Roa  
**Próxima revisión:** Cuando haya cambios estructurales  

**Para actualizar:**
1. Ejecutar query de esquema en Supabase
2. Exportar como CSV
3. Actualizar este documento
4. Guardar con nueva fecha

---

## 🎓 REFERENCIAS RÁPIDAS

### Query para obtener esquema
```sql
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

### Query para relaciones
```sql
SELECT constraint_name, table_name, column_name, referenced_table_name
FROM information_schema.referential_constraints
WHERE constraint_schema = 'public';
```

### Query para índices
```sql
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename;
```

---

**DOCUMENTACIÓN FINAL COMPLETA - 27 MAYO 2026**

