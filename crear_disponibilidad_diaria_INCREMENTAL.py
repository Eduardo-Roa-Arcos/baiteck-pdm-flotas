#!/usr/bin/env python3
"""
ACTUALIZAR DISPONIBILIDAD_DIARIA (VERSION INCREMENTAL)
=======================================================

Ejecutar DIARIAMENTE (cron: 0 2 * * *) a las 02:00 AM

Lógica:
  - Solo recalcula últimos 3 días
  - Solo procesa activos que tuvieron OT en esos días
  - Muy rápido (~5 segundos)
  - Evita recalcular el histórico innecesariamente

⭐ NUEVO: usa disponibilidad_diaria.py (utils) que aplica:
  1. DOWNTIME REAL desde fecha_cierre cuando está disponible.
  2. FALLBACK PONDERADO POR SEVERIDAD (ot_falla_evento) cuando no hay cierre.
  3. Marca cada fila con `fuente` = 'calculado' (real) o 'inferido' (heurístico).

Flujo:
  1. Lee OT relevantes para el período (apertura O cierre tocando últimos 3 días)
  2. Identifica activos únicos con movimiento
  3. Recalcula disponibilidad solo para esos activos/días usando el utils
  4. Borra registros previos del período y reinserta
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
print("⚡ DISPONIBILIDAD_DIARIA - ACTUALIZACIÓN INCREMENTAL")
print("="*70 + "\n")

# ============================================================
# PASO 0: ASEGURAR COLUMNA `fuente` (por si la tabla es vieja)
# ============================================================

try:
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE disponibilidad_diaria
            ADD COLUMN IF NOT EXISTS fuente TEXT NOT NULL DEFAULT 'calculado'
        """))
        conn.commit()
except Exception as e:
    # Si la tabla no existe aún, el INSERT más abajo fallará igual.
    print(f"   ⚠️ Aviso ALTER TABLE: {e}\n")

# ============================================================
# PASO 1: DETERMINAR PERÍODO A ACTUALIZAR
# ============================================================

hoy = pd.Timestamp.now().normalize().date()
ultima_fecha = pd.read_sql(
    "SELECT MAX(fecha) AS ultima FROM disponibilidad_diaria", 
    engine
).iloc[0]['ultima']

if ultima_fecha and pd.notna(ultima_fecha):
    fecha_inicio = ultima_fecha - timedelta(days=1)  # Overlap de 1 día para evitar glitches
else:
    fecha_inicio = hoy - timedelta(days=3) 

print(f"📅 Actualizando período: {fecha_inicio} a {hoy}\n")

# ============================================================
# PASO 2: CARGAR OT RELEVANTES PARA EL PERÍODO
# ============================================================
# Relevantes: cualquier OT cuyo intervalo [apertura, cierre] toque el rango.
#   - fecha_apertura <= hoy  (la OT ya existía o se abrió en el rango)
#   - fecha_cierre IS NULL O fecha_cierre >= fecha_inicio
# Esto incluye OT abiertas hace tiempo pero cerradas dentro del período (su
# downtime se distribuye real día a día).
# ============================================================

print("1️⃣ Cargando OT relevantes al período...")

try:
    query = """
        SELECT * FROM ordenes_trabajo
        WHERE DATE(fecha_apertura) <= %(hoy)s
          AND (fecha_cierre IS NULL OR DATE(fecha_cierre) >= %(fecha_inicio)s)
    """
    ots = pd.read_sql(query, engine, params={
        'fecha_inicio': fecha_inicio,
        'hoy': hoy
    })

    if len(ots) == 0:
        print("   ℹ️ No hay OT que toquen el período. Disponibilidad = 100%\n")
        print("="*70)
        print("✅ NADA QUE ACTUALIZAR")
        print("="*70 + "\n")
        sys.exit(0)

    print(f"   ✅ {len(ots)} OT encontradas\n")
except Exception as e:
    print(f"   ❌ Error: {e}\n")
    sys.exit(1)

# ============================================================
# PASO 3: IDENTIFICAR ACTIVOS CON MOVIMIENTO EN EL PERÍODO
# ============================================================

print("2️⃣ Identificando activos con OT...")

activos_con_ot = ots['activo_id'].dropna().unique().tolist()
print(f"   ✅ {len(activos_con_ot)} activos tienen movimiento\n")

# ============================================================
# PASO 4: PROCESAR FECHAS Y ENRIQUECER CON SEVERIDAD
# ============================================================

print("3️⃣ Procesando datos (severidad + tipos)...")

ots['fecha_apertura'] = pd.to_datetime(ots['fecha_apertura'], errors='coerce').dt.tz_localize(None)
ots['fecha_cierre']   = pd.to_datetime(ots['fecha_cierre'],   errors='coerce').dt.tz_localize(None)
ots['tipo_ot_lower']  = ots['tipo_ot'].fillna('').astype(str).str.lower().str.strip()

severidad_df = cargar_severidad_por_ot(engine)
if not severidad_df.empty and 'ot_id' in ots.columns:
    ots = ots.merge(severidad_df, on='ot_id', how='left')
else:
    ots['severidad'] = None

print(f"   ✅ Datos preparados (severidades cruzadas: {len(severidad_df)})\n")

# ============================================================
# PASO 5: CALCULAR DISPONIBILIDAD (INCREMENTAL) usando utils
# ============================================================

print("4️⃣ Calculando disponibilidad (downtime real + severidad)...\n")

disponibilidad_df = calcular_disponibilidad(
    ots=ots,
    activos_ids=activos_con_ot,
    fecha_inicio=fecha_inicio,
    hoy=hoy,
)

print(f"   ✅ {len(disponibilidad_df)} registros a actualizar")
if not disponibilidad_df.empty:
    n_calc = (disponibilidad_df['fuente'] == 'calculado').sum()
    n_inf  = (disponibilidad_df['fuente'] == 'inferido').sum()
    print(f"      • Fuente 'calculado': {n_calc:,}")
    print(f"      • Fuente 'inferido' : {n_inf:,}\n")

# ============================================================
# PASO 6: ACTUALIZAR EN BD (borrar período + reinsertar)
# ============================================================

print("5️⃣ Actualizando en base de datos...")

try:
    with engine.connect() as conn:
        # Borrar registros del período para los activos involucrados.
        # Usamos parámetro ARRAY para evitar interpolación manual de strings.
        delete_sql = text("""
            DELETE FROM disponibilidad_diaria
            WHERE activo_id = ANY(:activos)
              AND fecha >= :fecha_inicio
              AND fecha <= :hoy
        """)
        conn.execute(delete_sql, {
            'activos': list(activos_con_ot),
            'fecha_inicio': fecha_inicio,
            'hoy': hoy
        })
        conn.commit()

    # Insertar nuevos
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
        index=False
    )

    print(f"   ✅ {len(disponibilidad_df)} registros actualizados\n")
except Exception as e:
    print(f"   ❌ Error: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# RESUMEN FINAL
# ============================================================

print("="*70)
print("✅ ACTUALIZACIÓN INCREMENTAL COMPLETADA")
print("="*70)
print(f"\n📊 Activos con movimiento: {len(activos_con_ot)}")
print(f"   Registros actualizados: {len(disponibilidad_df)}\n")
print("⏭️  Próximo en pipeline: ejecutar_scoring.py")
print("   (Ejecutado automáticamente por ejecutar_pipeline_diario.sh)\n")
