# BAITECK PdM Flotas
# 📊 BAITECK - Predictive Maintenance Dashboard (PDM)
## Sistema Integral de Predicción y Monitoreo de Fallas en Flotas

**Versión:** 1.0 MVP  
**Fecha de Desarrollo:** Mayo 2026  
**Status:** ✅ Completo (Nivel 1 y 3) | ⚠️ Con limitaciones conocidas  
**Autor:** Eduardo Roa Arcos  
**Licencia:** MIT  

---

## 📋 Tabla de Contenidos

- [Descripción General](#descripción-general)
- [Arquitectura del Sistema](#arquitectura-del-sistema)
- [Requisitos Previos](#requisitos-previos)
- [Instalación](#instalación)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Componentes Desarrollados](#componentes-desarrollados)
  - [Fase 1: Carga de Datos](#fase-1-carga-de-datos)
  - [Fase 2: Auditoría](#fase-2-auditoría)
  - [Fase 3: Feature Engineering](#fase-3-feature-engineering)
  - [Fase 4: Entrenamiento](#fase-4-entrenamiento)
  - [Fase 5: Scoring Diario](#fase-5-scoring-diario)
  - [Fase 6: Dashboard](#fase-6-dashboard)
- [Base de Datos](#base-de-datos)
- [Uso y Ejecución](#uso-y-ejecución)
- [Limitaciones Conocidas](#limitaciones-conocidas)
- [Troubleshooting](#troubleshooting)
- [Roadmap para Producción](#roadmap-para-producción)
- [Próximos Pasos](#próximos-pasos)

---

## Descripción General

BAITECK PDM es un **sistema de mantenimiento predictivo para flotas** que automatiza la detección de fallas mediante machine learning.

### Capacidades Principales

✅ **Carga y Auditoría** de datos desde CSV a Supabase  
✅ **Feature Engineering** con validación temporal (sin data leakage)  
✅ **Entrenamiento** de modelos (Random Forest + XGBoost)  
✅ **Scoring Diario** automático en batch  
✅ **Dashboard Interactivo** con alertas en tiempo real  

### Flujo de Datos
┌──────────────────────────────────────────────────────────┐
│                    FLUJO DE DATOS                        │
└──────────────────────────────────────────────────────────┘
CSV Files (activos, OTs, repuestos)
↓
[FASE 1] Load → Supabase Database
↓
[FASE 2] Audit → Reporte Calidad (Completitud, Duplicados)
↓
[FASE 3] Features → Panel Entrenamiento (25 observaciones)
↓
[FASE 4] Training → Modelos (RF inactivo + XGBoost activo ✅)
↓
[FASE 5] Scoring Diario → scoring_resultados (Predicciones)
↓
[FASE 6] Dashboard → 4 Vistas (Activos, Tendencia, Feedback, Economía)
---

## Arquitectura del Sistema

### Componentes Principales
┌─────────────────────────────────────────────────────────────────┐
│                    BAITECK PDM v1.0 ARCHITECTURE               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────┐         ┌──────────────────────┐     │
│  │  Data Layer          │         │  ML Layer            │     │
│  │  ┌────────────────┐  │         │  ┌────────────────┐  │     │
│  │  │ CSV Files      │  │         │  │ main.py        │  │     │
│  │  │ - activos      │  │         │  │ - Features     │  │     │
│  │  │ - OTs          │  │         │  │ - Training     │  │     │
│  │  │ - repuestos    │  │         │  │ - Evaluation   │  │     │
│  │  └────────┬───────┘  │         │  └────────┬───────┘  │     │
│  │           ↓          │         │           ↓          │     │
│  │  ┌────────────────┐  │         │  ┌────────────────┐  │     │
│  │  │ Supabase       │  │◄────────►│  │ Models/        │  │     │
│  │  │ - activos      │  │         │  │ - RF v1        │  │     │
│  │  │ - OTs          │  │         │  │ - XGBoost v1 ✅│  │     │
│  │  │ - repuestos    │  │         │  └────────┬───────┘  │     │
│  │  └────────┬───────┘  │         │           │          │     │
│  │           ↑          │         └───────────┼──────────┘     │
│  └───────────┼──────────┘                     │                 │
│              │                                │                 │
│    ┌─────────┴──────────────────────────────┘                  │
│    ↓                                                             │
│  ┌────────────────────────────────────┐                        │
│  │  Inference & Scoring Layer         │                        │
│  │  ┌──────────────────────────────┐  │                        │
│  │  │ predictor.py                 │  │                        │
│  │  │ - load_active_model()        │  │                        │
│  │  │ - predict()                  │  │                        │
│  │  └──────────────┬───────────────┘  │                        │
│  │                 ↓                   │                        │
│  │  ┌──────────────────────────────┐  │                        │
│  │  │ scoring_diario.py            │  │                        │
│  │  │ - generar_features()         │  │                        │
│  │  │ - ejecutar()                 │  │                        │
│  │  │ - registrar_resultados()     │  │                        │
│  │  └──────────────┬───────────────┘  │                        │
│  │                 ↓                   │                        │
│  │  ┌──────────────────────────────┐  │                        │
│  │  │ Supabase Tables              │  │                        │
│  │  │ - scoring_resultados         │  │                        │
│  │  │ - modelos_registro           │  │                        │
│  │  └──────────────┬───────────────┘  │                        │
│  └─────────────────┼──────────────────┘                        │
│                    ↓                                             │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Presentation Layer                                     │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ dashboard.py (Streamlit)                         │   │  │
│  │  │ ┌──────────────────────────────────────────────┐ │   │  │
│  │  │ │ Vista 1: 🚨 Activos en Acción (✅ FUNCIONAL) │ │   │  │
│  │  │ │ - Top 15 P1/P2                               │ │   │  │
│  │  │ │ - Paginación / Filtros                       │ │   │  │
│  │  │ └──────────────────────────────────────────────┘ │   │  │
│  │  │ ┌──────────────────────────────────────────────┐ │   │  │
│  │  │ │ Vista 2: 📈 Tendencia Mensual (⚠️ MEJORA)    │ │   │  │
│  │  │ │ - Gráficos mejorados con go.Figure          │ │   │  │
│  │  │ │ - Métricas reales (requiere feedback)       │ │   │  │
│  │  │ └──────────────────────────────────────────────┘ │   │  │
│  │  │ ┌──────────────────────────────────────────────┐ │   │  │
│  │  │ │ Vista 3: 🔧 Feedback (⚠️ PLACEHOLDER)       │ │   │  │
│  │  │ │ - Datos ficticios                            │ │   │  │
│  │  │ │ - Requiere tabla feedback_alertas            │ │   │  │
│  │  │ └──────────────────────────────────────────────┘ │   │  │
│  │  │ ┌──────────────────────────────────────────────┐ │   │  │
│  │  │ │ Vista 4: 💰 Economía (⚠️ PLACEHOLDER)       │ │   │  │
│  │  │ │ - Valores estimados                          │ │   │  │
│  │  │ │ - Requiere validación de fallas reales       │ │   │  │
│  │  │ └──────────────────────────────────────────────┘ │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

### Tecnologías Utilizadas

| Componente | Tecnología | Versión |
|-----------|-----------|---------|
| **Base de Datos** | Supabase (PostgreSQL) | Latest |
| **Backend/Scripts** | Python | 3.9+ |
| **ML Framework** | scikit-learn, XGBoost | Latest |
| **Data Processing** | pandas, numpy | Latest |
| **Visualización** | Streamlit, Plotly | Latest |
| **Connection Pool** | psycopg2 | 2.9+ |
| **Packaging** | uv | Latest |

---

## Requisitos Previos

### Software Requerido
```bash
✓ Python 3.9+
✓ uv (gestor de paquetes)
✓ PostgreSQL 13+ (vía Supabase)
✓ Git
```

### Credenciales Necesarias
✓ Cuenta Supabase activa
✓ DATABASE_URL (connection string pooler)
✓ Permisos para crear tablas
### Datos Iniciales
✓ data/raw/activos.csv          (5 vehículos)
✓ data/raw/ordenes_trabajo.csv  (25 OTs - Mayo 2024)
✓ data/raw/repuestos_consumidos.csv (5 repuestos)

---

## Instalación

### Paso 1: Clonar Repositorio
```bash
git clone <repo-url>
cd baiteck-pdm-flotas
```

### Paso 2: Crear Ambiente
```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
```

### Paso 3: Instalar Dependencias
```bash
uv add pandas sqlalchemy psycopg2-binary python-dotenv numpy
uv add scikit-learn xgboost joblib
uv add streamlit plotly
```

### Paso 4: Configurar Variables de Entorno

Crear archivo `.env` en raíz:
```env
# Supabase Connection (Session Pooler - IMPORTANTE)
DATABASE_URL=postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-1-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require

# Alternativas para debugging (NO usar en producción)
SUPABASE_HOST=aws-1-us-east-1.pooler.supabase.com
SUPABASE_USER=postgres
SUPABASE_PASSWORD=[PASSWORD]
SUPABASE_DATABASE=postgres
```

**⚠️ IMPORTANTE:** Usar **Session Pooler** (`aws-1-us-east-1.pooler.supabase.com`), NO direct connection. IPv6 es incompatible con algunas redes.

### Paso 5: Crear Estructura de Carpetas
```bash
mkdir -p models data/raw data/processed
touch .gitignore
```

### Paso 6: Verificar Conexión
```bash
uv run python -c "from main import engine; print('✅ Conexión a Supabase OK')"
```

---

## Estructura del Proyecto

baiteck-pdm-flotas/
│
├── README.md                              # ← Este archivo
├── .env                                   # Variables de entorno (⚠️ NO COMMITAR)
├── .gitignore                             # Archivos a ignorar
│
├── main.py                                # ⭐ MÓDULO PRINCIPAL
│   ├── load_csv_files()                  # Carga CSV → Supabase
│   ├── reporte_auditoria()               # Audita calidad datos
│   ├── construir_features()              # Feature engineering
│   ├── entrenar_random_forest()          # Entrena RF (inactivo)
│   ├── entrenar_xgboost()                # Entrena XGBoost (✅ ACTIVO)
│   └── ejecutar_scoring_diario()         # Orquestación
│
├── predictor.py                           # ⭐ MÓDULO INFERENCIA
│   └── Predictor (clase)
│       ├── load_active_model()           # Carga modelo activo
│       └── predict()                     # Realiza predicciones
│
├── scoring_diario.py                      # ⭐ PIPELINE BATCH
│   └── ScoringDiario (clase)
│       ├── conectar_db()
│       ├── generar_features_scoring()
│       ├── registrar_predicciones()
│       └── ejecutar()
│
├── dashboard.py                           # ⭐ STREAMLIT DASHBOARD
│   ├── query_db()                        # Ejecución queries
│   ├── vista_activos_accion()            # Sección 1 (✅)
│   ├── vista_tendencia_mensual()         # Sección 2 (⚠️)
│   ├── vista_feedback_taller()           # Sección 3 (⚠️)
│   ├── vista_economia()                  # Sección 4 (⚠️)
│   └── main()
│
├── models/
│   ├── modelo_rf_v1.joblib               # Random Forest (inactivo)
│   └── modelo_xgb_v1.joblib              # XGBoost (✅ ACTIVO)
│
├── data/
│   ├── raw/
│   │   ├── activos.csv                   # 5 vehículos
│   │   ├── ordenes_trabajo.csv           # 25 OTs
│   │   └── repuestos_consumidos.csv      # 5 repuestos
│   └── processed/
│       └── panel_entrenamiento.parquet   # Dataset entrenamiento
│
└── src/                                   # (Estructura futura)
├── features/
├── pipelines/
└── models/

---

## Componentes Desarrollados

### Fase 1: Carga de Datos

**Función:** `load_csv_files()` en main.py

**Propósito:** Lee CSV y carga a Supabase

**Proceso:**
1. Trunca tablas existentes (CASCADE)
2. Lee CSV de `data/raw/`
3. Usa SQLAlchemy `to_sql()` para inserción
4. Valida registros insertados

**Tablas Creadas:**
- `activos` (5 registros)
- `ordenes_trabajo` (25 registros)
- `repuestos_consumidos` (5 registros)

```bash
uv run python -c "from main import load_csv_files; load_csv_files()"
```

---

### Fase 2: Auditoría de Datos

**Función:** `reporte_auditoria()` en main.py

**Validaciones:**
- Completitud (% NULL por columna)
- Duplicados
- Rangos de valores
- Consistencia FK

**Output:**
✓ AUDITORÍA DE DATOS
Tabla: activos (5 registros)
- activo_id: 100% completitud
- patente: 80% completitud
Tabla: ordenes_trabajo (25 registros)
- fecha_apertura: 100% completitud

```bash
uv run python -c "from main import reporte_auditoria; reporte_auditoria()"
```

---

### Fase 3: Feature Engineering

**Función:** `construir_features(fecha_corte_str, horizonte_dias=30)` en main.py

**Panel Resultante:** 25 observaciones (5 activos × 5 fechas)

**Features Generadas:**

| Feature | Descripción | Rango |
|---------|-----------|-------|
| `activo_id` | ID vehículo | Text |
| `edad_dias` | Días desde alta | 0-365 |
| `ot_30d` | OTs últimos 30d | 0-5 |
| `ot_90d` | OTs últimos 90d | 0-10 |
| `ot_180d` | OTs últimos 180d | 0-15 |
| `corr_30d` | OTs correctivas 30d | 0-3 |
| `corr_90d` | OTs correctivas 90d | 0-8 |
| `corr_180d` | OTs correctivas 180d | 0-12 |
| `target` | Correctiva en horizonte | 0/1 |

**Validación Temporal:**
- ✅ Una fila por activo/fecha
- ✅ Sin data leakage (info ANTES de fecha_corte)
- ✅ Comparaciones basadas en STRINGS
- ✅ Temporal split (70/15/15 train/val/test)

---

### Fase 4: Entrenamiento

#### Random Forest v1 (Inactivo)

```python
RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    class_weight='balanced',
    random_state=42
)

Resultados (Test Set):
  - AUC: 0.0000 (sin positivos)
  - Precision: 0.0000
  - Recall: 0.0000
  - F1: 0.0000

Status: ENTRENADO (Inactivo)
Guardado: models/modelo_rf_v1.joblib
```

#### XGBoost v1 (✅ ACTIVO)

```python
XGBClassifier(
    n_estimators=500,
    max_depth=5,
    learning_rate=0.05,
    early_stopping_rounds=50,
    scale_pos_weight=17.00,  # Para desbalance 17:0
    subsample=0.8,
    colsample_bytree=0.8,
    eval_metric='aucpr',
    random_state=42
)

Configuración:
  - Train: 17 muestras (70%)
  - Validation: 4 muestras (15%)
  - Test: 4 muestras (15%)
  - Temporal split (sin data leakage)

Resultados (Test Set):
  - AUC: NaN (sin positivos en test)
  - Precision: 0.0000
  - Recall: 0.0000
  - F1: 0.0000
  - Early Stopping: Activado

Status: ✅ ACTIVO
Guardado: models/modelo_xgb_v1.joblib

Artifact Structure:
{
    "model": XGBClassifier(...),
    "pipeline": None,
    "feature_cols": ['edad_dias', 'ot_30d', 'ot_90d', ...]
}
```

**⚠️ Nota:** Dataset muy pequeño. Se necesita más histórico con fallas reales para mejor rendimiento.

```bash
# Entrenar XGBoost
uv run python -c "from main import entrenar_xgboost; entrenar_xgboost()"
```

---

### Fase 5: Scoring Diario

**Clase:** `ScoringDiario` en scoring_diario.py

**Flujo:**

Conectar a Supabase
Cargar modelo activo (es_activo=TRUE)
Generar features para fecha específica
Realizar predicciones (probabilidades)
Asignar prioridades:

P1_critica: prob >= 85%
P2_alta: prob >= 65%
P3_media: prob >= 40%
P4_baja: prob < 40%


Registrar en scoring_resultados

**Uso:**
```bash
# Fecha específica
uv run python -c "from scoring_diario import ejecutar_scoring_diario; ejecutar_scoring_diario('2024-05-15')"

# Hoy (CURRENT_DATE)
uv run python -c "from scoring_diario import ejecutar_scoring_diario; ejecutar_scoring_diario()"
```

**Output en Supabase:**
```sql
INSERT INTO scoring_resultados (
    scoring_id,      -- UUID único
    activo_id,       -- FK a activos
    fecha_scoring,   -- DATE
    horizonte_dias,  -- INT (default: 30)
    probabilidad_falla, -- NUMERIC [0, 1]
    prediccion,      -- INT (0 o 1)
    prioridad,       -- TEXT (P1/P2/P3/P4)
    modelo_version   -- TEXT (ref. a modelos_registro)
)
```

---

### Fase 6: Dashboard

**Framework:** Streamlit + Plotly

#### Vista 1: 🚨 Activos en Acción (✅ FUNCIONAL)

**Contenido:**
- Top 15 activos con P1_critica o P2_alta
- Columnas: Patente, Marca, Modelo, Prob%, Prioridad, Sistema, Última OT, KM
- Filtros (futuro): Marca, Taller, Rango Fechas
- Paginación (futuro): 10/15/25 items por página

**Query:**
```sql
WHERE s.fecha_scoring = (SELECT MAX(fecha_scoring) FROM scoring_resultados)
  AND s.prioridad IN ('P1_critica', 'P2_alta')
ORDER BY s.probabilidad_falla DESC
LIMIT 15
```

**Métrica:**
- ✅ Datos reales desde `scoring_resultados`

#### Vista 2: 📈 Tendencia Mensual (⚠️ MEJORA PENDIENTE)

**Contenido:**
- Gráfico de alertas últimos 30 días
- Línea de tendencia + distribución por prioridad
- Métricas: Alertas hoy, Recall, Precision, VP

**Problemas Actuales:**
- 🔴 Métrica Recall = "75%" es FICTICIA
- 🔴 Falsos Positivos = "12%" es FICTICIO
- 🔴 Fallas Evitadas = "3" es FICTICIO

**Solución:**
Requiere tabla `feedback_alertas` para calcular métricas reales. Ver sección **Limitaciones**.

#### Vista 3: 🔧 Feedback Taller (⚠️ PLACEHOLDER)

**Status:** DATOS FICTICIOS

```python
feedback_data = {
    'Alertas Revisadas': 45,    # 🔴 HARDCODED
    'Confirmadas (TP)': 38,     # 🔴 HARDCODED
    'Descartadas (FP)': 5,      # 🔴 HARDCODED
    'Pendientes': 2             # 🔴 HARDCODED
}
```

**Requiere:** Tabla `feedback_alertas`

#### Vista 4: 💰 Economía (⚠️ PLACEHOLDER)

**Status:** VALORES ESTIMADOS

```python
col1.metric("Fallas Evitadas", "8")        # 🔴 ESTIMADO
col2.metric("Costo Evitado", "$48,000")    # 🔴 ESTIMADO
col3.metric("Horas Detencion", "120")      # 🔴 ESTIMADO
```

**Requiere:** Validación de fallas reales + costos

---

## Base de Datos

### Esquema Completo

#### Tabla: `activos`

```sql
CREATE TABLE activos (
    activo_id TEXT PRIMARY KEY,
    patente TEXT,
    marca TEXT,
    modelo TEXT,
    tipo_vehiculo TEXT,
    anio_fabricacion INTEGER,
    fecha_alta_flota DATE,
    odometro_km NUMERIC,
    horometro_h NUMERIC,
    estado_actual TEXT,
    motor_tipo TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 5 registros de ejemplo
INSERT INTO activos VALUES
('ACE-001', 'ZZZZ99', 'Volvo', 'FH16', 'Camión', 2018, '2020-01-15', 125000, NULL, 'Activo', 'D13', ...),
('ACE-002', 'ZZZZ98', 'Volvo', 'FH16', 'Camión', 2019, '2020-06-20', 95000, NULL, 'Activo', 'D13', ...),
...
```

#### Tabla: `ordenes_trabajo`

```sql
CREATE TABLE ordenes_trabajo (
    ot_id TEXT PRIMARY KEY,
    activo_id TEXT NOT NULL,
    fecha_apertura TIMESTAMP,
    fecha_cierre TIMESTAMP,
    tipo_ot TEXT,  -- 'preventiva', 'correctiva'
    descripcion TEXT,
    costo NUMERIC,
    tecnico TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (activo_id) REFERENCES activos(activo_id)
);

-- 25 registros (Mayo 2024)
-- Ejemplo:
INSERT INTO ordenes_trabajo VALUES
('OT-001', 'ACE-001', '2024-05-02 10:30:00', '2024-05-02 12:00:00', 'correctiva', 'Revisión motor', 1200, 'Juan', ...),
...
```

#### Tabla: `repuestos_consumidos`

```sql
CREATE TABLE repuestos_consumidos (
    consumo_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ot_id TEXT NOT NULL,
    sku TEXT,
    cantidad INTEGER,
    costo_unitario_clp NUMERIC,
    descripcion_repuesto TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (ot_id) REFERENCES ordenes_trabajo(ot_id)
);
```

#### Tabla: `modelos_registro` (⭐ Crítica)

```sql
CREATE TABLE modelos_registro (
    modelo_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version TEXT UNIQUE NOT NULL,  -- 'v1_rf', 'v1_xgb'
    nombre_archivo TEXT NOT NULL,
    fecha_entrenamiento DATE,
    fecha_creacion TIMESTAMP DEFAULT NOW(),

    -- Métricas
    auc_score NUMERIC,
    precision NUMERIC,
    recall NUMERIC,
    f1_score NUMERIC,

    -- Datos entrenamiento
    n_samples_train INTEGER,
    n_features INTEGER,
    features_utilizadas TEXT[],

    -- Hiperparámetros (JSON)
    hiperparametros JSONB,

    -- Control
    estado TEXT DEFAULT 'entrenado',  -- 'entrenado', 'evaluado'
    es_activo BOOLEAN DEFAULT FALSE,  -- ✅ Solo UNO puede ser TRUE
    entrenado_por TEXT DEFAULT 'sistema',
    notas TEXT,

    CONSTRAINT only_one_active CHECK (
        (SELECT COUNT(*) FROM modelos_registro WHERE es_activo = TRUE) <= 1
    )
);

-- Registros actuales:
INSERT INTO modelos_registro VALUES
('8bd5dcf-31f5-4a67-9869-d32368e8475c', 'v1_rf', 'modelo_rf_v1.joblib', '2026-05-19', ..., FALSE, ...),
('cd71947d-0bcd-463b-a93c-681957f2fd8f', 'v1_xgb', 'modelo_xgb_v1.joblib', '2026-05-20', ..., TRUE, ✅ ACTIVO),
```

#### Tabla: `scoring_resultados` (⭐ Crítica)

```sql
CREATE TABLE scoring_resultados (
    scoring_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activo_id TEXT NOT NULL,
    fecha_scoring DATE NOT NULL,
    horizonte_dias INTEGER DEFAULT 30,

    -- Predicciones
    probabilidad_falla NUMERIC NOT NULL,  -- [0, 1]
    prediccion INTEGER NOT NULL,  -- 0 o 1
    prioridad TEXT NOT NULL,  -- 'P1_critica', 'P2_alta', 'P3_media', 'P4_baja'

    -- Trazabilidad
    modelo_version TEXT,
    created_at TIMESTAMP DEFAULT NOW(),

    FOREIGN KEY (activo_id) REFERENCES activos(activo_id)
);

-- Se llena automáticamente con scoring_diario.py
CREATE INDEX idx_scoring_fecha ON scoring_resultados(fecha_scoring DESC);
CREATE INDEX idx_scoring_activo ON scoring_resultados(activo_id);
```

#### Tabla: `feedback_alertas` (⚠️ FUTURO - Requiere implementación)

```sql
CREATE TABLE feedback_alertas (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scoring_id UUID NOT NULL,
    activo_id TEXT NOT NULL,

    -- Validación
    estado TEXT NOT NULL,  -- 'revisada', 'confirmada', 'descartada', 'pendiente'
    falla_real BOOLEAN,  -- TRUE si alerta fue correcta

    -- Costos (para economía)
    costo_reparacion NUMERIC,
    horas_detencion NUMERIC,

    -- Metadata
    notas TEXT,
    taller_id TEXT,  -- Para RLS futura
    created_at TIMESTAMP DEFAULT NOW(),
    fecha_feedback DATE DEFAULT CURRENT_DATE,

    FOREIGN KEY (scoring_id) REFERENCES scoring_resultados(scoring_id),
    FOREIGN KEY (activo_id) REFERENCES activos(activo_id)
);

CREATE INDEX idx_feedback_estado ON feedback_alertas(estado);
CREATE INDEX idx_feedback_activo ON feedback_alertas(activo_id);
```

---

## Uso y Ejecución

### Ejecución Paso a Paso

#### 1. Carga Inicial
```bash
uv run python -c "from main import load_csv_files; load_csv_files()"
```

#### 2. Auditoría
```bash
uv run python -c "from main import reporte_auditoria; reporte_auditoria()"
```

#### 3. Entrenamiento
```bash
# XGBoost (Recomendado)
uv run python -c "from main import entrenar_xgboost; entrenar_xgboost()"
```

#### 4. Scoring Diario
```bash
# Fecha específica
uv run python -c "from scoring_diario import ejecutar_scoring_diario; ejecutar_scoring_diario('2024-05-15')"

# Hoy
uv run python -c "from scoring_diario import ejecutar_scoring_diario; ejecutar_scoring_diario()"
```

#### 5. Dashboard
```bash
uv run streamlit run dashboard.py
```

Abre en navegador: **http://localhost:8501**

### Ejecución Automatizada (Cron)

Para scoring automático a las 06:00 AM:

```bash
# Editar crontab
crontab -e

# Agregar línea:
0 6 * * * cd /path/to/baiteck-pdm-flotas && /usr/bin/python3 -c "from scoring_diario import ejecutar_scoring_diario; ejecutar_scoring_diario()"
```

---

## Limitaciones Conocidas

### ⚠️ Limitación 1: Métricas Hardcoded en Tendencia Mensual

**Problema:**
```python
col2.metric("Recall (Est.)", "75%", delta="↑ 5%")      # 🔴 FICTICIO
col3.metric("Falsos Positivos", "12%", delta="↓ 2%")   # 🔴 FICTICIO
col4.metric("Fallas Evitadas", "3", delta="↑")         # 🔴 FICTICIO
```

**Por qué:**
- No existe tabla `feedback_alertas` para validar fallas
- Recall requiere comparar predicciones vs fallas reales
- Falsos Positivos requiere confirmación del taller
- Sin datos de costo no se puede calcular ROI

**Solución (MVP+1):**
1. Crear tabla `feedback_alertas` en Supabase
2. Implementar recolección de feedback de talleres
3. Calcular métricas reales con consultas SQL
4. Reemplazar hardcoded por queries dinámicas

**Impacto:** ⚠️ ALTO - Los números son estimativos, no datos reales

---

### ⚠️ Limitación 2: Visualización Plotly Básica

**Problema:**
```python
fig_alertas = px.line(
    df_alertas,
    x='fecha',
    y=['total_alertas', 'alertas_altas'],
    title='Alertas por Día',
    markers=True
)
```

**Problemas:**
- Dos series con escalas diferentes hacen difícil interpretación
- No diferencia visualmente por tipo de alerta
- Sin subplots es confuso

**Solución:**
Usar `plotly.graph_objects` con subplots mejorados (ver código en Roadmap)

**Impacto:** ⚠️ MEDIO - Usabilidad limitada

---

### ⚠️ Limitación 3: Sin Paginación / Filtros

**Problema:**
```sql
LIMIT 15  -- Muy restrictivo para flota real (100+ activos)
```

**Sin filtros por:**
- Marca / Modelo
- Taller asignado
- Rango de fechas
- Estado de alerta

**Solución:**
Implementar paginación + filtros multidimensionales (código disponible en Roadmap)

**Impacto:** ⚠️ MEDIO - Escalabilidad limitada

---

### ⚠️ Limitación 4: Sin Autenticación

**Riesgo:**
Dashboard PÚBLICO → Cualquiera puede ver:
✗ Datos operacionales de la flota
✗ Predicciones futuras
✗ Probabilidades de falla
✗ Descargar histórico completo

**Solución:**
Implementar login Streamlit + RLS en Supabase (código en Roadmap)

**Impacto:** 🔴 CRÍTICO - Bloqueante para producción

---

### ⚠️ Limitación 5: Dataset Muy Pequeño

**Problema:**
- Solo 25 observaciones (5 activos × 5 fechas)
- Sin positivos en conjunto de test
- AUC = NaN (no se puede calcular)

**Impacto:**
- Modelos no pueden evaluar rendimiento real
- Predicciones basadas en patrones débiles
- Necesita datos históricos de 1-2 años mínimo

**Solución:**
- Recolectar datos históricos de OTs
- Entrenar con 100+ observaciones
- Validación con datos más recientes

**Impacto:** 🔴 CRÍTICO - Necesario para confiabilidad

---

## Troubleshooting

### Error 1: `ModuleNotFoundError: No module named 'src'`

**Causa:** Imports incorrectos o estructura de carpetas

**Solución:**
```bash
# Verificar estructura
ls -la src/models/ src/pipelines/

# Usar imports directos desde raíz
from predictor import Predictor
from scoring_diario import ScoringDiario
```

---

### Error 2: `UniqueViolation: duplicate key value`

**Causa:** Versión de modelo ya existe

**Solución:**
```sql
-- En Supabase SQL Editor
DELETE FROM modelos_registro WHERE version = 'v1_xgb';

-- O cambiar versión en main.py
version = "v1_xgb_v2"
```

---

### Error 3: `connection to server on socket "/tmp/.s.PGSQL.5432" failed`

**
