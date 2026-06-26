#!/usr/bin/env python3
"""
ANÁLISIS: Estructura de feedback_taller
========================================

Revisa la estructura actual y propone campos necesarios para la carga batch.

Uso: uv run python analizar_feedback_taller.py
"""

import os
import sys
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no configurada")
    sys.exit(1)

def get_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        return conn
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

conn = get_connection()
if conn is None:
    sys.exit(1)

print("\n" + "█"*80)
print("█" + "ANÁLISIS: ESTRUCTURA feedback_taller".center(80) + "█")
print("█"*80)

# ============================================================================
# 1. ESTRUCTURA ACTUAL
# ============================================================================
print("\n1️⃣ ESTRUCTURA ACTUAL")
print("="*80)

df = pd.read_sql("""
    SELECT 
        column_name,
        data_type,
        is_nullable,
        column_default
    FROM information_schema.columns
    WHERE table_name = 'feedback_taller'
    ORDER BY ordinal_position
""", conn)

print("\n📋 Columnas:")
for idx, row in df.iterrows():
    nullable = "✓ NULL" if row['is_nullable'] == 'YES' else "✗ NOT NULL"
    default = f" (default: {row['column_default']})" if row['column_default'] else ""
    print(f"  • {row['column_name']:<35} {row['data_type']:<20} {nullable}{default}")

# ============================================================================
# 2. RELACIONES CON OTRAS TABLAS
# ============================================================================
print("\n" + "="*80)
print("2️⃣ RELACIONES (Foreign Keys)")
print("="*80)

df = pd.read_sql("""
    SELECT 
        constraint_name,
        column_name,
        referenced_table_name,
        referenced_column_name
    FROM information_schema.referential_constraints rc
    JOIN information_schema.key_column_usage kcu 
        ON rc.constraint_name = kcu.constraint_name
    WHERE kcu.table_name = 'feedback_taller'
""", conn)

if len(df) > 0:
    print(df.to_string(index=False))
else:
    print("  (sin FKs definidas — revisar si debería haber)")

# ============================================================================
# 3. DATOS ACTUALES
# ============================================================================
print("\n" + "="*80)
print("3️⃣ DATOS ACTUALES")
print("="*80)

df_count = pd.read_sql("SELECT COUNT(*) AS n FROM feedback_taller", conn)
n_registros = int(df_count.iloc[0]['n'])
print(f"\n  Total registros: {n_registros}")

if n_registros == 0:
    print("  ⚠️  Tabla vacía — no hay datos para analizar")
else:
    df_sample = pd.read_sql("SELECT * FROM feedback_taller LIMIT 3", conn)
    print("\n  Primeras 3 filas:")
    print(df_sample.to_string(index=False))

# ============================================================================
# 4. CAMPOS PROPUESTOS PARA CARGA
# ============================================================================
print("\n" + "="*80)
print("4️⃣ CAMPOS PROPUESTOS PARA CARGA BATCH")
print("="*80)

print("""
Basado en la lógica de Costo evitado y Downtime evitado, feedback_taller debería:

┌─ IDENTIFICADORES (relación con otras tablas)
│
├─ scoring_id (uuid)
│   └─ ¿De dónde viene? ¿Del modelo de scoring?
│   └─ ¿Siempre presente o puede ser NULL?
│
├─ ot_id (text)
│   └─ ¿ID de la OT que se creó en respuesta a la alerta?
│   └─ ¿Puede haber múltiples OTs por alerta?
│
├─ activo_id (text)
│   └─ ¿Del modelo o de la OT?
│
└─ fecha_alerta (date)
    └─ ¿Fecha de la predicción del modelo?

┌─ RESULTADO DE LA PREDICCIÓN (lo crítico)
│
├─ falla_confirmada (boolean) ← CLAVE para Costo evitado
│   └─ ¿Verdadero si: la predicción fue correcta?
│   └─ ¿Quién determina esto? ¿Mecánico? ¿Sistema?
│
├─ falsa_alarma (boolean)
│   └─ ¿Verdadero si: se predijo pero NO pasó nada?
│
└─ resultado_revision (text)
    └─ Enum: 'confirmado', 'falsa_alarma', 'no_revisado', etc.

┌─ DETALLES DE LA ACCIÓN TOMADA
│
├─ accion_realizada (text)
│   └─ ¿Descripción de qué se hizo?
│   └─ ¿Enum o libre?
│
├─ comentario_mecanico (text)
│   └─ ¿Observaciones del taller?
│
└─ created_at (timestamp)
    └─ ¿Fecha/hora de cuándo se registró el feedback?

""")

# ============================================================================
# 5. RELACIONES CON ORDENES_TRABAJO
# ============================================================================
print("="*80)
print("5️⃣ RELACIÓN CON ordenes_trabajo")
print("="*80)

df = pd.read_sql("""
    SELECT 
        column_name,
        data_type
    FROM information_schema.columns
    WHERE table_name = 'ordenes_trabajo'
    ORDER BY ordinal_position
    LIMIT 15
""", conn)

print("\nCampos en ordenes_trabajo (primeros 15):")
for idx, row in df.iterrows():
    print(f"  • {row['column_name']:<30} {row['data_type']}")

# ============================================================================
# 6. PREGUNTAS PARA DEFINIR LA CARGA
# ============================================================================
print("\n" + "="*80)
print("❓ PREGUNTAS PARA DEFINIR LA CARGA")
print("="*80)

print("""
Antes de implementar cargar_feedback_taller.py, necesitas responder:

1. FUENTE DE DATOS:
   ¿De dónde exactamente vienen los datos de feedback?
   • Sistema de órdenes de trabajo (¿cuál exactamente?)
   • Base de datos legacy
   • Archivo CSV/Excel
   • API
   • Formulario en UI

2. IDENTIFICADORES:
   ¿Cómo se relaciona el feedback con el modelo?
   • ¿Viene scoring_id desde la fuente?
   • ¿Se busca por ot_id + activo_id?
   • ¿Se busca matching en scoring_resultados?

3. LÓGICA DE CONFIRMACIÓN:
   ¿Cuál es la regla para falla_confirmada = TRUE?
   • ¿Se abre una OT y se cierra exitosamente?
   • ¿El mecánico marca como "confirmado"?
   • ¿Se detecta automáticamente desde otra tabla?

4. PERÍODO E INCREMENTALIDAD:
   • ¿Diariamente? ¿Cada N horas?
   • ¿Desde cuándo hay historia? (días/meses atrás)
   • ¿Cómo trackear "última carga"?

5. VOLUMEN:
   • ¿Cuántos registros esperados por día?
   • ¿Hay "picos" (ej: cargas semanales masivas)?

6. VALIDACIONES:
   • ¿Qué datos son obligatorios?
   • ¿Hay duplicados posibles?
   • ¿Timeout o reintentos?
""")

conn.close()

print("\n" + "="*80)
print("✅ Revisa estas preguntas y defini el detalle de la carga.")
print("="*80 + "\n")
