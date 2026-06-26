#!/usr/bin/env python3
"""
PASO 2: Cargar consumo_sku_historico
====================================

Calcula consumo promedio mensual por cada SKU.

Lógica:
- Para cada SKU, suma todo lo consumido históricamente
- Divide por el número de meses en el histórico
- Resultado: cantidad promedio consumida por mes

Esto es la "línea base" histórica que se compara con demanda predicha.
"""

import sys
sys.path.insert(0, '/mnt/project')

import pandas as pd
from sqlalchemy import text
from src.db import engine

def crear_tabla_consumo_sku_historico():
    """Crea la tabla consumo_sku_historico si no existe."""
    query = text("""
        CREATE TABLE IF NOT EXISTS consumo_sku_historico (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sku TEXT NOT NULL UNIQUE,
            consumo_promedio_mensual NUMERIC NOT NULL,
            consumo_total_historico NUMERIC NOT NULL,
            num_meses_historico INTEGER NOT NULL,
            fecha_primera_transaccion DATE,
            fecha_ultima_transaccion DATE,
            fecha_calculo TIMESTAMP DEFAULT NOW()
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)
        print("✅ Tabla consumo_sku_historico creada/verificada")


def cargar_consumo_sku_historico():
    """
    Calcula consumo promedio mensual por SKU.
    
    Análisis:
    - Suma total de cada SKU
    - Calcula rango de fechas (primer consumo - último consumo)
    - Estima número de meses = (fecha_máx - fecha_mín) / 30 días
    - Promedio mensual = total / meses
    """
    
    print("\n📊 Analizando consumo histórico por SKU...")
    
    query = text("""
        WITH consumo_por_sku AS (
            SELECT
                sku,
                SUM(cantidad)::NUMERIC AS consumo_total,
                COUNT(*) AS num_transacciones,
                MIN(created_at)::DATE AS fecha_primera,
                MAX(created_at)::DATE AS fecha_ultima,
                (MAX(created_at)::DATE - MIN(created_at)::DATE) AS dias_rango
            FROM repuestos_consumidos
            WHERE sku IS NOT NULL
              AND TRIM(sku) <> ''
              AND cantidad IS NOT NULL
            GROUP BY sku
        )
        SELECT
            sku,
            consumo_total,
            num_transacciones,
            fecha_primera,
            fecha_ultima,
            GREATEST(
                CEIL(dias_rango / 30.0)::INTEGER,
                1
            ) AS num_meses,
            ROUND(
                consumo_total::NUMERIC / 
                GREATEST(
                    CEIL(dias_rango / 30.0)::INTEGER,
                    1
                ),
                2
            ) AS consumo_promedio_mensual
        FROM consumo_por_sku
        ORDER BY consumo_total DESC
    """)
    
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    
    print(f"✅ Se encontraron {len(df)} SKUs con histórico de consumo")
    
    if len(df) == 0:
        print("⚠️  No hay datos de consumo. Verifica tabla repuestos_consumidos.")
        return 0
    
    # Preview
    print("\n📋 Preview de consumos (top 15 por volumen):")
    print(df.head(15)[['sku', 'consumo_total', 'num_meses', 
                       'consumo_promedio_mensual', 'fecha_primera', 'fecha_ultima']].to_string())
    
    # Cargar en tabla
    print("\n📝 Cargando datos en tabla consumo_sku_historico...")
    
    # Renombrar columnas para match
    df_load = df.copy()
    df_load.columns = ['sku', 'consumo_total_historico', 'num_transacciones',
                       'fecha_primera_transaccion', 'fecha_ultima_transaccion',
                       'num_meses_historico', 'consumo_promedio_mensual']
    
    # Seleccionar solo columnas necesarias
    df_load = df_load[[
        'sku', 'consumo_promedio_mensual', 'consumo_total_historico',
        'num_meses_historico', 'fecha_primera_transaccion', 'fecha_ultima_transaccion'
    ]]
    
    with engine.begin() as conn:
        # Limpiar tabla anterior
        conn.execute(text("DELETE FROM consumo_sku_historico"))
        
        # Batch insert
        df_load.to_sql('consumo_sku_historico', conn, if_exists='append', index=False)
    
    print(f"✅ {len(df)} SKUs cargados exitosamente")
    
    # Estadísticas
    print("\n📈 Estadísticas de consumo:")
    print(f"  - SKUs con histórico: {len(df)}")
    print(f"  - Consumo total (rango): {df['consumo_total'].min():.0f} - {df['consumo_total'].max():.0f} unidades")
    print(f"  - Consumo promedio mensual (rango): {df['consumo_promedio_mensual'].min():.2f} - {df['consumo_promedio_mensual'].max():.2f} unidades/mes")
    print(f"  - Meses de histórico (rango): {df['num_meses'].min()} - {df['num_meses'].max()} meses")
    
    # Top 10 consumos
    print(f"\n🏆 Top 10 SKUs por consumo promedio mensual:")
    top_10 = df.nlargest(10, 'consumo_promedio_mensual')[['sku', 'consumo_promedio_mensual']]
    for idx, row in top_10.iterrows():
        print(f"   {row['sku']}: {row['consumo_promedio_mensual']:.2f} unidades/mes")
    
    return len(df)


def main():
    print("=" * 80)
    print("PASO 2: CARGAR CONSUMO_SKU_HISTORICO")
    print("=" * 80)
    
    try:
        crear_tabla_consumo_sku_historico()
        
        num_skus = cargar_consumo_sku_historico()
        
        if num_skus > 0:
            print("\n" + "=" * 80)
            print("✅ PASO 2 COMPLETADO EXITOSAMENTE")
            print("=" * 80)
            print("\nPróximo paso: PASO 3 - Calcular demanda proyectada para P1/P2")
            return 0
        else:
            return 1
            
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
