#!/usr/bin/env python3
"""
SCRIPT 1: RESTAURAR TABLA ACTIVOS
==================================

Restaura la tabla `activos` desde activos.csv (respaldo)

Uso: uv run python 01_restaurar_activos.py

⚠️  CRÍTICO: Esta es una tabla paramétrica de carga inicial.
    Solo debe truncarse si es necesario recargar desde respaldo.
"""

import os
import sys
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Cargar .env
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    raise RuntimeError(f"No se encontró .env en {Path(__file__).parent}")

load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en .env")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

print("="*70)
print("🔄 RESTAURACIÓN DE TABLA ACTIVOS")
print("="*70 + "\n")

# ============================================================
# PASO 1: CARGAR CSV
# ============================================================

print("1️⃣ Cargando activos.csv...")
try:
    df_activos = pd.read_csv('data/raw/activos.csv')
    print(f"   ✅ {len(df_activos)} activos cargados\n")
except FileNotFoundError:
    print(f"   ❌ ERROR: data/raw/activos.csv no encontrado\n")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ ERROR: {e}\n")
    sys.exit(1)

# ============================================================
# PASO 2: VALIDAR ESTRUCTURA
# ============================================================

print("2️⃣ Validando estructura...")

columnas_esperadas = {
    'activo_id', 'patente', 'marca', 'modelo', 'anio_fabricacion',
    'fecha_alta_flota', 'tipo_vehiculo', 'motor_tipo', 'estado_actual',
    'odometro_km', 'horometro_h'
}

columnas_faltantes = columnas_esperadas - set(df_activos.columns)
if columnas_faltantes:
    print(f"   ❌ Columnas faltantes: {columnas_faltantes}\n")
    sys.exit(1)

# Validar PK
duplicados = df_activos['activo_id'].duplicated().sum()
if duplicados > 0:
    print(f"   ❌ {duplicados} activos duplicados (PK violada)\n")
    sys.exit(1)

print(f"   ✅ Estructura válida\n")

# ============================================================
# PASO 3: LIMPIAR Y PREPARAR DATOS
# ============================================================

print("3️⃣ Limpiando datos...")

# Reemplazar NaN con None para que PostgreSQL lo interprete como NULL
df_activos = df_activos.where(pd.notna(df_activos), None)

# Asegurar que activo_id no sea nulo
n_nulos = df_activos['activo_id'].isna().sum()
if n_nulos > 0:
    print(f"   ❌ {n_nulos} activos con activo_id nulo\n")
    sys.exit(1)

print(f"   ✅ Datos limpios\n")

# ============================================================
# PASO 4: TRUNCAR TABLA EXISTENTE
# ============================================================

print("4️⃣ Preparando tabla en BD...")

try:
    with engine.connect() as conn:
        # Borrar registros existentes (sin CASCADE)
        conn.execute(text("DELETE FROM activos;"))
        conn.commit()
    print(f"   ✅ Tabla vaciada\n")
except Exception as e:
    print(f"   ⚠️  Error al vaciar (tabla podría no existir): {e}\n")

# ============================================================
# PASO 5: CARGAR EN BD
# ============================================================

print("5️⃣ Insertando datos en BD...")

try:
    df_activos.to_sql(
        'activos',
        engine,
        if_exists='append',
        index=False,
        method='multi',
        chunksize=500
    )
    print(f"   ✅ {len(df_activos)} activos insertados\n")
except Exception as e:
    print(f"   ❌ ERROR al insertar: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# PASO 6: VALIDACIÓN
# ============================================================

print("6️⃣ Validando en BD...")

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM activos")).fetchone()
        n_en_bd = result[0]
    
    if n_en_bd == len(df_activos):
        print(f"   ✅ {n_en_bd} activos confirmados en BD\n")
    else:
        print(f"   ⚠️  Discrepancia: {len(df_activos)} en CSV vs {n_en_bd} en BD\n")
except Exception as e:
    print(f"   ⚠️  Error en validación: {e}\n")

# ============================================================
# RESUMEN
# ============================================================

print("="*70)
print("✅ RESTAURACIÓN DE ACTIVOS COMPLETADA")
print("="*70)
print(f"\n📊 {len(df_activos)} activos restaurados")
print("\n⏭️  Próximo paso: 02_restaurar_repuestos_maestro.py\n")
