#!/usr/bin/env python3
"""
SCRIPT 2 - CORREGIDO: RESTAURAR TABLA REPUESTOS_MAESTRO
========================================================

⭐ CORRECCIÓN:
El CSV tiene columnas extra (vacías) que pandas nombra "Unnamed: X"
Estas columnas no existen en la BD, así que las ignoramos.

Uso: uv run python 02_restaurar_repuestos_maestro.py
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
print("🔄 RESTAURACIÓN DE TABLA REPUESTOS_MAESTRO (CORREGIDO)")
print("="*70 + "\n")

# ============================================================
# PASO 1: CARGAR CSV (con separador ; y encoding)
# ============================================================

print("1️⃣ Cargando repuestos_maestro.csv...")
try:
    df_repuestos = pd.read_csv(
        'data/raw/repuestos_maestro.csv',
        sep=';',  # ⚠️ CSV usa punto y coma
        encoding='utf-8-sig'  # ⚠️ Encoding con BOM
    )
    print(f"   ✅ {len(df_repuestos)} repuestos cargados")
    print(f"   ℹ️  Columnas originales: {list(df_repuestos.columns)}\n")
except FileNotFoundError:
    print(f"   ❌ ERROR: data/raw/repuestos_maestro.csv no encontrado\n")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ ERROR: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# PASO 2: LIMPIAR COLUMNAS (eliminar "Unnamed: X")
# ============================================================

print("2️⃣ Limpiando columnas extra...")

# ⭐ Eliminar columnas "Unnamed" que pandas crea de más
columnas_a_mantener = [col for col in df_repuestos.columns if not col.startswith('Unnamed')]
df_repuestos = df_repuestos[columnas_a_mantener]

print(f"   ✅ Columnas después de limpiar: {list(df_repuestos.columns)}\n")

# ============================================================
# PASO 3: VALIDAR ESTRUCTURA
# ============================================================

print("3️⃣ Validando estructura...")

columnas_esperadas = {
    'sku', 'descripcion', 'sistema', 'componente', 'proveedor_principal',
    'lead_time_dias_promedio', 'costo_unitario_clp', 'stock_actual',
    'stock_minimo', 'criticidad', 'rotacion', 'activo'
}

columnas_faltantes = columnas_esperadas - set(df_repuestos.columns)
if columnas_faltantes:
    print(f"   ⚠️  Columnas esperadas faltantes: {columnas_faltantes}")
    print(f"   Columnas disponibles: {sorted(df_repuestos.columns)}\n")

# Validar PK
if 'sku' not in df_repuestos.columns:
    print(f"   ❌ Columna 'sku' (PK) no encontrada\n")
    sys.exit(1)

duplicados = df_repuestos['sku'].duplicated().sum()
if duplicados > 0:
    print(f"   ❌ {duplicados} repuestos duplicados (PK violada)\n")
    sys.exit(1)

print(f"   ✅ Estructura válida\n")

# ============================================================
# PASO 4: LIMPIAR Y PREPARAR DATOS
# ============================================================

print("4️⃣ Limpiando datos...")

# Reemplazar NaN con None
df_repuestos = df_repuestos.where(pd.notna(df_repuestos), None)

# Reemplazar 'null' (string) con None
df_repuestos = df_repuestos.replace('null', None)

# Convertir booleanos si existen
if 'activo' in df_repuestos.columns:
    df_repuestos['activo'] = df_repuestos['activo'].astype(bool, errors='ignore')

# Asegurar tipos de datos numéricos
for col in ['lead_time_dias_promedio', 'costo_unitario_clp', 'stock_actual', 'stock_minimo']:
    if col in df_repuestos.columns:
        df_repuestos[col] = pd.to_numeric(df_repuestos[col], errors='coerce')

print(f"   ✅ Datos limpios\n")

# ============================================================
# PASO 5: TRUNCAR TABLA EXISTENTE
# ============================================================

print("5️⃣ Preparando tabla en BD...")

try:
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM repuestos_maestro;"))
        conn.commit()
    print(f"   ✅ Tabla vaciada\n")
except Exception as e:
    print(f"   ⚠️  Error al vaciar (tabla podría no existir): {e}\n")

# ============================================================
# PASO 6: CARGAR EN BD
# ============================================================

print("6️⃣ Insertando datos en BD...")

try:
    df_repuestos.to_sql(
        'repuestos_maestro',
        engine,
        if_exists='append',
        index=False,
        method='multi',
        chunksize=500
    )
    print(f"   ✅ {len(df_repuestos)} repuestos insertados\n")
except Exception as e:
    print(f"   ❌ ERROR al insertar: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# PASO 7: VALIDACIÓN
# ============================================================

print("7️⃣ Validando en BD...")

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM repuestos_maestro")).fetchone()
        n_en_bd = result[0]
    
    if n_en_bd == len(df_repuestos):
        print(f"   ✅ {n_en_bd} repuestos confirmados en BD\n")
    else:
        print(f"   ⚠️  Discrepancia: {len(df_repuestos)} en CSV vs {n_en_bd} en BD\n")
except Exception as e:
    print(f"   ⚠️  Error en validación: {e}\n")

# ============================================================
# RESUMEN
# ============================================================

print("="*70)
print("✅ RESTAURACIÓN DE REPUESTOS_MAESTRO COMPLETADA")
print("="*70)
print(f"\n📊 {len(df_repuestos)} repuestos restaurados")
print("\n⏭️  Próximo paso: Verificar en Supabase\n")
