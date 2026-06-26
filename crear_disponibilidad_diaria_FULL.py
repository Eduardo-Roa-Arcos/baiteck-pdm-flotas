#!/usr/bin/env python3
"""
CREAR DISPONIBILIDAD_DIARIA (VERSION FULL)
==========================================

Ejecutar SOLO cuando:
  1. Cargas datos nuevos (ejecutar_workflow.py)
  2. Cambias archivos CSV en data/raw/
  3. Necesitas recalcular TODO el histórico

NO ejecutar diariamente - ver crear_disponibilidad_diaria_INCREMENTAL.py

Lógica:
  - Borra toda la tabla disponibilidad_diaria
  - Recalcula histórico completo (últimos 180 días)
  - Rellena con ceros si activo tiene fecha_alta_flota posterior

⭐ NUEVO: usa disponibilidad_diaria.py (utils) que aplica:
  1. DOWNTIME REAL desde fecha_cierre cuando está disponible.
  2. FALLBACK PONDERADO POR SEVERIDAD (ot_falla_evento) cuando no hay cierre.
  3. Marca cada fila con `fuente` = 'calculado' (real) o 'inferido' (heurístico).
"""

import os
import sys
from datetime import timedelta
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# ============================================================
# ⭐ NUEVO: lógica compartida de cálculo de disponibilidad
# ============================================================
from disponibilidad_diaria import calcular_disponibilidad, cargar_severidad_por_ot

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no configurada en .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

print("="*70)
print("🔄 DISPONIBILIDAD_DIARIA - RECALCULO COMPLETO (FULL)")
print("="*70 + "\n")

# ============================================================
# PASO 1: CREAR TABLA SI NO EXISTE / AGREGAR COLUMNA `fuente`
# ============================================================

print("1️⃣ Creando tabla disponibilidad_diaria (si no existe)...")

try:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS disponibilidad_diaria (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                activo_id TEXT NOT NULL,
                fecha DATE NOT NULL,
                horas_operativas NUMERIC NOT NULL DEFAULT 24,
                horas_detenido_planificado NUMERIC NOT NULL DEFAULT 0,
                horas_detenido_no_planificado NUMERIC NOT NULL DEFAULT 0,
                fuente TEXT NOT NULL DEFAULT 'calculado',
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(activo_id, fecha)
            )
        """))

        # Si la tabla ya existía sin `fuente`, agregarla de forma segura.
        conn.execute(text("""
            ALTER TABLE disponibilidad_diaria
            ADD COLUMN IF NOT EXISTS fuente TEXT NOT NULL DEFAULT 'calculado'
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_disponibilidad_activo_fecha 
                ON disponibilidad_diaria(activo_id, fecha)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_disponibilidad_fecha 
                ON disponibilidad_diaria(fecha)
        """))

        conn.commit()
    print("   ✅ Tabla lista (incluye columna `fuente`)\n")
except Exception as e:
    print(f"   ⚠️ Tabla ya existe / aviso: {e}\n")

# ============================================================
# PASO 2: LIMPIAR TABLA (borrar TODO)
# ============================================================

print("2️⃣ Borrando registros anteriores...")

try:
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE disponibilidad_diaria"))
        conn.commit()
    print("   ✅ Tabla limpiada\n")
except Exception as e:
    print(f"   ❌ Error: {e}\n")
    sys.exit(1)

# ============================================================
# PASO 3: CARGAR DATOS
# ============================================================

print("3️⃣ Cargando datos...")

try:
    ots = pd.read_sql("SELECT * FROM ordenes_trabajo", engine)
    activos = pd.read_sql("SELECT activo_id, fecha_alta_flota FROM activos", engine)

    print(f"   ✅ OT: {len(ots)} registros")
    print(f"   ✅ Activos: {len(activos)} registros")
except Exception as e:
    print(f"   ❌ Error: {e}\n")
    sys.exit(1)

if len(ots) == 0 or len(activos) == 0:
    print("   ⚠️ Datos vacíos. Tabla creada sin registros.")
    sys.exit(0)

# ⭐ NUEVO: cargar severidad desde ot_falla_evento para usar en el fallback.
print("   • Cargando severidad por OT (ot_falla_evento)...")
severidad_df = cargar_severidad_por_ot(engine)
print(f"   ✅ Severidades: {len(severidad_df)} OT clasificadas\n")

# ============================================================
# PASO 4: PROCESAR FECHAS Y ENRIQUECER CON SEVERIDAD
# ============================================================

print("4️⃣ Procesando fechas y normalizando OT...")

ots['fecha_apertura'] = pd.to_datetime(ots['fecha_apertura'], errors='coerce').dt.tz_localize(None)
ots['fecha_cierre']   = pd.to_datetime(ots['fecha_cierre'],   errors='coerce').dt.tz_localize(None)
ots['tipo_ot_lower']  = ots['tipo_ot'].fillna('').astype(str).str.lower().str.strip()

# Merge severidad (si la tabla está vacía, queda como NaN y el utils usa fallback por tipo).
if not severidad_df.empty and 'ot_id' in ots.columns:
    ots = ots.merge(severidad_df, on='ot_id', how='left')
else:
    ots['severidad'] = None

hoy = pd.Timestamp.now().normalize().date()
fecha_inicio = hoy - timedelta(days=365)

print(f"   Período: {fecha_inicio} a {hoy}\n")

# ============================================================
# PASO 5: GENERAR MATRIZ DISPONIBILIDAD (FULL)
# ============================================================

print("5️⃣ Calculando disponibilidad (downtime real + severidad)...\n")

# Determinar activos válidos respetando fecha_alta_flota:
# si un activo se dio de alta DESPUÉS de fecha_inicio, su rango propio es
# acotado por el utils (queda con horas operativas = 24 default en días previos
# porque no hay OT que toque esos días — comportamiento conservador).
activos_ids = activos['activo_id'].unique().tolist()

disponibilidad_df = calcular_disponibilidad(
    ots=ots,
    activos_ids=activos_ids,
    fecha_inicio=fecha_inicio,
    hoy=hoy,
)

print(f"   ✅ {len(disponibilidad_df)} registros generados")
if not disponibilidad_df.empty:
    n_calc = (disponibilidad_df['fuente'] == 'calculado').sum()
    n_inf  = (disponibilidad_df['fuente'] == 'inferido').sum()
    print(f"      • Fuente 'calculado' (downtime real): {n_calc:,}")
    print(f"      • Fuente 'inferido'  (fallback severidad/tipo): {n_inf:,}\n")

# ============================================================
# PASO 6: INSERTAR EN BD
# ============================================================

print("6️⃣ Insertando en base de datos...")

try:
    # Reordenar columnas para coincidir con el esquema esperado.
    cols_destino = [
        'activo_id', 'fecha',
        'horas_operativas',
        'horas_detenido_planificado',
        'horas_detenido_no_planificado',
        'fuente',
    ]
    disponibilidad_df[cols_destino].to_sql(
        'disponibilidad_diaria',
        engine,
        if_exists='append',
        index=False,
        method='multi',
        chunksize=1000
    )
    print(f"   ✅ {len(disponibilidad_df)} registros insertados\n")
except Exception as e:
    print(f"   ❌ Error: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# PASO 7: VALIDACIÓN
# ============================================================

print("7️⃣ Validando...")

try:
    count_df = pd.read_sql("SELECT COUNT(*) as n FROM disponibilidad_diaria", engine)
    n_registros = int(count_df.iloc[0]['n'])

    disp_df = pd.read_sql("""
        SELECT 
            ROUND(AVG((horas_operativas / 24.0) * 100), 2) as disp_pct,
            COUNT(DISTINCT activo_id) as n_activos,
            COUNT(DISTINCT fecha) as n_dias
        FROM disponibilidad_diaria
    """, engine)

    fuente_df = pd.read_sql("""
        SELECT fuente, COUNT(*) AS n
        FROM disponibilidad_diaria
        GROUP BY fuente
        ORDER BY n DESC
    """, engine)

    print(f"   ✅ Total registros: {n_registros:,}")
    print(f"   ✅ Activos: {disp_df.iloc[0]['n_activos']}")
    print(f"   ✅ Días: {disp_df.iloc[0]['n_dias']}")
    print(f"   ✅ Disponibilidad promedio: {disp_df.iloc[0]['disp_pct']}%")
    print(f"   ✅ Desglose por fuente:")
    for _, r in fuente_df.iterrows():
        print(f"        - {r['fuente']:<10}: {int(r['n']):,}")
    print()

except Exception as e:
    print(f"   ⚠️ Error en validación: {e}\n")

# ============================================================
# RESUMEN FINAL
# ============================================================

print("="*70)
print("✅ DISPONIBILIDAD_DIARIA (FULL) COMPLETADA")
print("="*70)
print("\n📋 Próximos pasos:")
print("   1. Entrenar modelo:      uv run python -m src.models.train_xgboost")
print("   2. Generar predicciones: uv run python ejecutar_scoring.py")
print("   3. Plan de repuestos:    uv run python generar_plan_repuestos_financiero.py")
print("   4. Calcular paneles:     uv run python calcular_paneles.py")
print("   5. Ver dashboard:        uv run streamlit run dashboard.py")
print("   6. Configurar cron DIARIO para actualización incremental:")
print("      0 2 * * * cd /Users/eduardoroa/baiteck-pdm-flotas && \\")
print("                uv run python crear_disponibilidad_diaria_INCREMENTAL.py\n")
