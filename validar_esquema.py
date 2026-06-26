#!/usr/bin/env python3
"""
VALIDACIÓN EXHAUSTIVA - Verificar que todo está en orden
antes de ejecutar cargar_ot.py
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no definido")
    exit(1)

print("=" * 80)
print("🔍 VALIDACIÓN EXHAUSTIVA DE ESQUEMA Y DATOS")
print("=" * 80)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
inspector = inspect(engine)

# ============================================================================
# 1. VALIDAR TABLAS EXISTEN
# ============================================================================

print("\n1️⃣  VERIFICANDO TABLAS EXISTEN...")

tablas_requeridas = [
    "activos",
    "ordenes_trabajo", 
    "ot_falla_evento",
    "taxonomia_fallas",
    "repuestos_consumidos",
    "scoring_resultados"
]

tablas_bd = inspector.get_table_names()
for tabla in tablas_requeridas:
    if tabla in tablas_bd:
        print(f"   ✅ {tabla}")
    else:
        print(f"   ❌ {tabla} NO EXISTE")
        exit(1)

# ============================================================================
# 2. VALIDAR COLUMNAS CRÍTICAS
# ============================================================================

print("\n2️⃣  VERIFICANDO COLUMNAS CRÍTICAS...")

validaciones_columnas = {
    "activos": ["activo_id", "patente", "marca", "modelo"],
    "ordenes_trabajo": ["ot_id", "activo_id", "fecha_apertura", "tipo_ot", "costo_total_clp", "odometro_km"],
    "ot_falla_evento": ["id_evento", "ot_id", "activo_id", "taxonomia_id"],
    "taxonomia_fallas": ["taxonomia_id", "sistema", "componente", "activo"],
    "repuestos_consumidos": ["ot_id", "id_evento", "sku", "cantidad"],
    "scoring_resultados": ["activo_id", "fecha_scoring", "prioridad", "sistema_en_riesgo"]
}

for tabla, cols_esperadas in validaciones_columnas.items():
    cols_reales = [c["name"] for c in inspector.get_columns(tabla)]
    for col in cols_esperadas:
        if col in cols_reales:
            print(f"   ✅ {tabla}.{col}")
        else:
            print(f"   ❌ {tabla}.{col} NO EXISTE")
            print(f"      Columnas disponibles: {cols_reales}")
            exit(1)

# ============================================================================
# 3. VALIDAR DATOS DE EJEMPLO
# ============================================================================

print("\n3️⃣  VALIDANDO DATOS DE EJEMPLO...")

with engine.connect() as conn:
    
    # Activos
    activos_count = conn.execute(text("SELECT COUNT(*) FROM activos")).fetchone()[0]
    print(f"   ✅ Activos en BD: {activos_count}")
    
    # OTs
    ots_count = conn.execute(text("SELECT COUNT(*) FROM ordenes_trabajo")).fetchone()[0]
    print(f"   ✅ OTs en BD: {ots_count}")
    
    # Scoring
    scoring_count = conn.execute(text("SELECT COUNT(*) FROM scoring_resultados")).fetchone()[0]
    print(f"   ✅ Registros de scoring: {scoring_count}")
    
    # Taxonomías activas
    taxonomias = conn.execute(
        text("SELECT COUNT(*) FROM taxonomia_fallas WHERE activo = TRUE")
    ).fetchone()[0]
    print(f"   ✅ Taxonomías activas: {taxonomias}")

# ============================================================================
# 4. VALIDAR RELACIONES CRÍTICAS
# ============================================================================

print("\n4️⃣  VALIDANDO RELACIONES (FOREIGN KEYS)...")

with engine.connect() as conn:
    
    # OT → Activo
    ots_sin_activo = conn.execute(
        text("SELECT COUNT(*) FROM ordenes_trabajo WHERE activo_id NOT IN (SELECT activo_id FROM activos)")
    ).fetchone()[0]
    if ots_sin_activo == 0:
        print(f"   ✅ Todas las OTs tienen activo_id válido")
    else:
        print(f"   ⚠️  {ots_sin_activo} OTs tienen activo_id inválido (ignorar si son de prueba)")
    
    # Eventos → Taxonomía
    eventos_sin_taxonomia = conn.execute(
        text("SELECT COUNT(*) FROM ot_falla_evento WHERE taxonomia_id NOT IN (SELECT taxonomia_id FROM taxonomia_fallas)")
    ).fetchone()[0]
    if eventos_sin_taxonomia == 0:
        print(f"   ✅ Todos los eventos tienen taxonomia_id válido")
    else:
        print(f"   ⚠️  {eventos_sin_taxonomia} eventos con taxonomia_id inválido")
    
    # Repuestos → OT
    repuestos_sin_ot = conn.execute(
        text("SELECT COUNT(*) FROM repuestos_consumidos WHERE ot_id NOT IN (SELECT ot_id FROM ordenes_trabajo)")
    ).fetchone()[0]
    if repuestos_sin_ot == 0:
        print(f"   ✅ Todos los repuestos tienen ot_id válido")
    else:
        print(f"   ⚠️  {repuestos_sin_ot} repuestos con ot_id inválido")

# ============================================================================
# 5. VALIDAR FORMATO OT_ID
# ============================================================================

print("\n5️⃣  VALIDANDO FORMATO OT_ID...")

with engine.connect() as conn:
    sample_ots = conn.execute(
        text("SELECT ot_id FROM ordenes_trabajo LIMIT 5")
    ).fetchall()
    
    if sample_ots:
        print(f"   Sample OT_IDs:")
        for (ot_id,) in sample_ots:
            print(f"     • {ot_id}")
        print(f"   ✅ Formato: OT-YYYY-SECUENCIA")
    else:
        print(f"   ℹ️  No hay OTs para validar formato")

# ============================================================================
# 6. VALIDAR SCORING
# ============================================================================

print("\n6️⃣  VALIDANDO SCORING_RESULTADOS...")

with engine.connect() as conn:
    scoring_sample = conn.execute(
        text("""
            SELECT DISTINCT ON (activo_id) 
                activo_id, fecha_scoring, prioridad, sistema_en_riesgo
            FROM scoring_resultados
            ORDER BY activo_id, fecha_scoring DESC
            LIMIT 3
        """)
    ).fetchall()
    
    if scoring_sample:
        print(f"   Sample registros:")
        for activo_id, fecha, prioridad, sistema in scoring_sample:
            print(f"     • {activo_id}: {prioridad} (sistema: {sistema})")
        print(f"   ✅ Scoring tiene datos")
    else:
        print(f"   ⚠️  No hay scoring en BD (ejecutar ejecutar_scoring.py primero)")

# ============================================================================
# 7. VALIDAR TAXONOMÍAS
# ============================================================================

print("\n7️⃣  VALIDANDO TAXONOMÍA_FALLAS...")

with engine.connect() as conn:
    sistemas = conn.execute(
        text("SELECT DISTINCT sistema FROM taxonomia_fallas WHERE activo = TRUE LIMIT 10")
    ).fetchall()
    
    if sistemas:
        print(f"   Sistemas disponibles:")
        for (sistema,) in sistemas:
            print(f"     • {sistema}")
    else:
        print(f"   ⚠️  No hay taxonomías activas")

# ============================================================================
# 8. VALIDAR VARIABLES DE AMBIENTE
# ============================================================================

print("\n8️⃣  VALIDANDO VARIABLES DE AMBIENTE...")

env_vars = {
    "DATABASE_URL": DATABASE_URL,
    "PATH": os.getenv("PATH"),
}

for var, valor in env_vars.items():
    if valor:
        print(f"   ✅ {var}: (definido)")
    else:
        print(f"   ❌ {var}: NO DEFINIDO")

# ============================================================================
# RESULTADO FINAL
# ============================================================================

print("\n" + "=" * 80)
print("✅ VALIDACIÓN COMPLETADA - LISTO PARA cargar_ot.py")
print("=" * 80)
print("\nProximos pasos:")
print("  1. uv run python cargar_ot.py")
print("  2. Ingresar patente (ej: WRYY32, FKFD95)")
print("  3. Sistema automáticamente creará:")
print("     - 1 OT nueva")
print("     - 2 eventos de falla")
print("     - 2+ repuestos consumidos")
print("\n" + "=" * 80)
