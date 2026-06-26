#!/usr/bin/env python3
"""
Script de Diagnóstico: Top 5 Repuestos por Costo
Verifica por qué no se muestra el Top 5 en el dashboard
"""

import os
from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import psycopg2
from psycopg2 import sql

DATABASE_URL = os.getenv("DATABASE_URL")

print("\n" + "="*70)
print("🔍 DIAGNÓSTICO: Top 5 Repuestos por Costo")
print("="*70)

# ============================================================================
# 1. VERIFICAR CONEXIÓN
# ============================================================================

print("\n[1] Verificando conexión a BD...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    print("✅ Conexión exitosa")
except Exception as e:
    print(f"❌ Error de conexión: {e}")
    exit(1)

# ============================================================================
# 2. VERIFICAR QUE TABLA EXISTE
# ============================================================================

print("\n[2] Verificando que tabla 'repuestos_maestro' existe...")
try:
    query = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'repuestos_maestro'
        ) AS existe;
    """
    df = pd.read_sql(query, conn)
    existe = bool(df.iloc[0]["existe"])
    
    if existe:
        print("✅ Tabla 'repuestos_maestro' existe")
    else:
        print("❌ Tabla 'repuestos_maestro' NO existe")
        exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# ============================================================================
# 3. VERIFICAR COLUMNA costo_unitario_clp
# ============================================================================

print("\n[3] Verificando columna 'costo_unitario_clp'...")
try:
    query = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'repuestos_maestro'
              AND column_name = 'costo_unitario_clp'
        ) AS existe;
    """
    df = pd.read_sql(query, conn)
    existe = bool(df.iloc[0]["existe"])
    
    if existe:
        print("✅ Columna 'costo_unitario_clp' existe")
    else:
        print("❌ Columna 'costo_unitario_clp' NO existe")
        exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# ============================================================================
# 4. LISTAR TODAS LAS COLUMNAS
# ============================================================================

print("\n[4] Listando todas las columnas de 'repuestos_maestro'...")
try:
    query = """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'repuestos_maestro'
        ORDER BY ordinal_position;
    """
    df = pd.read_sql(query, conn)
    print("\nColumnas disponibles:")
    for _, row in df.iterrows():
        print(f"  • {row['column_name']:30} ({row['data_type']})")
except Exception as e:
    print(f"❌ Error: {e}")

# ============================================================================
# 5. CONTAR REGISTROS
# ============================================================================

print("\n[5] Contando registros...")
try:
    query = "SELECT COUNT(*) AS total FROM repuestos_maestro;"
    df = pd.read_sql(query, conn)
    total = int(df.iloc[0]["total"])
    
    if total == 0:
        print(f"⚠️  La tabla está VACÍA ({total} registros)")
    else:
        print(f"✅ {total:,} registros en la tabla")
except Exception as e:
    print(f"❌ Error: {e}")

# ============================================================================
# 6. VERIFICAR NULL EN costo_unitario_clp
# ============================================================================

print("\n[6] Verificando valores en 'costo_unitario_clp'...")
try:
    query = """
        SELECT
            COUNT(*) AS total,
            COUNT(CASE WHEN costo_unitario_clp IS NOT NULL THEN 1 END) AS con_costo,
            COUNT(CASE WHEN costo_unitario_clp IS NULL THEN 1 END) AS sin_costo,
            COUNT(CASE WHEN costo_unitario_clp > 0 THEN 1 END) AS con_costo_positivo
        FROM repuestos_maestro;
    """
    df = pd.read_sql(query, conn)
    
    total = int(df.iloc[0]["total"])
    con_costo = int(df.iloc[0]["con_costo"])
    sin_costo = int(df.iloc[0]["sin_costo"])
    con_costo_positivo = int(df.iloc[0]["con_costo_positivo"])
    
    print(f"  • Total registros: {total:,}")
    print(f"  • Con costo (NOT NULL): {con_costo:,}")
    print(f"  • Sin costo (NULL): {sin_costo:,}")
    print(f"  • Con costo > 0: {con_costo_positivo:,}")
    
    if con_costo == 0:
        print("\n⚠️  PROBLEMA: Todos los valores de 'costo_unitario_clp' son NULL")
        print("   → Necesita cargar datos en esa columna")
    elif con_costo_positivo == 0:
        print("\n⚠️  PROBLEMA: Todos los costos son 0 o negativos")
        print("   → Verifique que los datos sean correctos")
    else:
        print("\n✅ Datos de costos parecen estar bien")
        
except Exception as e:
    print(f"❌ Error: {e}")

# ============================================================================
# 7. MOSTRAR TOP 5 COSTOS
# ============================================================================

print("\n[7] Top 5 repuestos por costo (si existen)...")
try:
    query = """
        SELECT
            sku,
            descripcion,
            costo_unitario_clp,
            stock_actual
        FROM repuestos_maestro
        WHERE costo_unitario_clp IS NOT NULL AND costo_unitario_clp > 0
        ORDER BY costo_unitario_clp DESC
        LIMIT 5;
    """
    df = pd.read_sql(query, conn)
    
    if df.empty:
        print("❌ No hay datos para mostrar Top 5")
    else:
        print("\nTop 5:")
        for idx, row in df.iterrows():
            sku = row['sku']
            desc = row['descripcion'][:30]
            costo = row['costo_unitario_clp']
            stock = row['stock_actual']
            print(f"  {idx+1}. {sku:15} | {desc:30} | Costo: ${costo:>10,.0f} | Stock: {stock}")
            
except Exception as e:
    print(f"❌ Error: {e}")

# ============================================================================
# 8. VERIFICAR QUERY DEL DASHBOARD
# ============================================================================

print("\n[8] Ejecutando la query EXACTA que usa el dashboard...")
try:
    query = """
        SELECT
            sku,
            descripcion,
            stock_actual,
            lead_time_dias_promedio AS lead_time,
            criticidad,
            costo_unitario_clp,
            stock_actual::numeric / NULLIF(
                GREATEST(1,
                    (SELECT COALESCE(SUM(cantidad), 0)
                     FROM repuestos_consumidos rc
                     JOIN ordenes_trabajo o ON o.ot_id = rc.ot_id
                     WHERE rc.sku = rm.sku
                       AND o.fecha_apertura >= CURRENT_DATE - INTERVAL '30 days'
                    )
                ), 0) * 30.0 AS cobertura_dias
        FROM repuestos_maestro rm;
    """
    df = pd.read_sql(query, conn)
    
    if df.empty:
        print("❌ Query retorna DataFrame vacío")
    else:
        print(f"✅ Query retorna {len(df)} registros")
        print(f"\nPrimeras 3 filas:")
        print(df.head(3).to_string())
        
        # Verificar si costo_unitario_clp está presente
        if 'costo_unitario_clp' not in df.columns:
            print("\n❌ PROBLEMA: 'costo_unitario_clp' NO está en el resultado de la query")
        else:
            nulls = df['costo_unitario_clp'].isna().sum()
            no_nulls = len(df) - nulls
            print(f"\n✅ 'costo_unitario_clp' está en resultado: {no_nulls} con valor, {nulls} NULL")
            
except Exception as e:
    print(f"❌ Error en query: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# RESUMEN
# ============================================================================

print("\n" + "="*70)
print("📊 RESUMEN")
print("="*70)
print("""
Si ves "❌ PROBLEMA" arriba, el issue es:
  
1. Si 'costo_unitario_clp' tiene todos NULL:
   → Necesita cargar datos: UPDATE repuestos_maestro SET costo_unitario_clp = [valor]
   
2. Si la query no incluye 'costo_unitario_clp':
   → El cambio en dashboard.py NO se guardó correctamente
   → Verifica que la línea ~746 tenga: costo_unitario_clp,
   
3. Si todo parece bien arriba pero en dashboard sigue sin mostrar:
   → El problema está en la lógica del dashboard (línea 1527)
   → Verifíca que el bloque fue copiado EXACTAMENTE

Si ves "✅" en todo, el problema está en otra parte del código.
""")

conn.close()
print("\n✅ Diagnóstico completado")
