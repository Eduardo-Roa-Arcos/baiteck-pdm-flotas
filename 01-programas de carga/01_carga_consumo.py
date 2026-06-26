#!/usr/bin/env python3
"""
PASO 1: Carga inicial - Construir mapeo consumo_sistema_modelo
=====================================================================

Analiza TODO el histórico de órdenes de trabajo para construir un mapeo:
    Marca + Modelo + Sistema → SKUs consumidos (cantidad_promedio, frecuencia)

Este mapeo será la base para proyectar demanda de repuestos basada en P1/P2.

Flujo:
1. ordenes_trabajo → ot_falla_evento → taxonomia_fallas (para obtener sistema)
2. ot_falla_evento → repuestos_consumidos (para obtener SKUs)
3. ordenes_trabajo → activos (para obtener marca, modelo)
4. Agrupar por: marca + modelo + sistema + sku
5. Calcular: cantidad_promedio, frecuencia_fallos
6. Cargar en tabla consumo_sistema_modelo (con UPSERT)
"""

import sys
sys.path.insert(0, '/mnt/project')

import pandas as pd
from sqlalchemy import text
from src.db import engine
from datetime import datetime

def crear_tabla_consumo_sistema_modelo():
    """Crea la tabla consumo_sistema_modelo si no existe."""
    query = text("""
        CREATE TABLE IF NOT EXISTS consumo_sistema_modelo (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            marca TEXT NOT NULL,
            modelo TEXT NOT NULL,
            sistema TEXT NOT NULL,
            sku TEXT NOT NULL,
            cantidad_promedio NUMERIC NOT NULL,
            frecuencia_fallos_historico INTEGER NOT NULL,
            num_registros_analizados INTEGER NOT NULL,
            fecha_calculo TIMESTAMP DEFAULT NOW(),
            UNIQUE(marca, modelo, sistema, sku)
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)
        print("✅ Tabla consumo_sistema_modelo creada/verificada")


def cargar_consumo_sistema_modelo():
    """
    Construye el mapeo desde histórico completo.
    
    Query:
    - Toma todas las OTs
    - Las relaciona con fallas (ot_falla_evento)
    - Obtiene sistema de taxonomia_fallas
    - Obtiene repuestos de repuestos_consumidos
    - Obtiene marca/modelo de activos
    - Agrupa por: marca + modelo + sistema + sku
    - Calcula: cantidad_promedio, frecuencia_fallos
    """
    
    print("\n📊 Analizando histórico COMPLETO de órdenes de trabajo...")
    
    query = text("""
        WITH datos_consolidados AS (
            SELECT
                a.marca,
                a.modelo,
                tf.sistema,
                rc.sku,
                rc.cantidad,
                ofe.ot_id
            FROM ordenes_trabajo ot
            JOIN ot_falla_evento ofe ON ot.ot_id = ofe.ot_id
            JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
            JOIN repuestos_consumidos rc ON ot.ot_id = rc.ot_id
            JOIN activos a ON ot.activo_id = a.activo_id
            WHERE a.marca IS NOT NULL
              AND a.modelo IS NOT NULL
              AND tf.sistema IS NOT NULL
              AND TRIM(tf.sistema) <> ''
              AND rc.sku IS NOT NULL
              AND TRIM(rc.sku) <> ''
              AND rc.cantidad IS NOT NULL
        )
        SELECT
            marca,
            modelo,
            sistema,
            sku,
            AVG(cantidad)::NUMERIC AS cantidad_promedio,
            COUNT(DISTINCT ot_id)::INTEGER AS frecuencia_fallos_historico,
            COUNT(*)::INTEGER AS num_registros_analizados
        FROM datos_consolidados
        GROUP BY marca, modelo, sistema, sku
        ORDER BY marca, modelo, sistema, sku
    """)
    
    # Ejecutar query
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    
    print(f"✅ Se encontraron {len(df)} combinaciones de (marca, modelo, sistema, sku)")
    
    if len(df) == 0:
        print("⚠️  No hay datos para cargar. Verifica que existan:")
        print("   - Órdenes de trabajo con ot_falla_evento")
        print("   - Eventos de falla con taxonomia_fallas clasificada")
        print("   - Repuestos consumidos asociados")
        return 0
    
    # Mostrar preview
    print("\n📋 Preview de datos:")
    print(df.head(10).to_string())
    
    # Cargar en tabla (batch insert)
    print("\n📝 Cargando datos en tabla consumo_sistema_modelo...")
    print("   (usando batch insert para mejor rendimiento)")
    
    # Renombrar columnas para match con tabla
    df_load = df.copy()
    df_load.columns = ['marca', 'modelo', 'sistema', 'sku', 
                       'cantidad_promedio', 'frecuencia_fallos_historico', 
                       'num_registros_analizados']
    
    with engine.begin() as conn:
        # Limpiar tabla anterior (estamos haciendo carga inicial)
        conn.execute(text("DELETE FROM consumo_sistema_modelo"))
        print("   Tabla limpiada")
        
        # Usar to_sql de pandas para batch insert (más eficiente)
        df_load.to_sql('consumo_sistema_modelo', conn, if_exists='append', index=False)
    
    print(f"✅ {len(df)} registros cargados exitosamente")
    
    # Mostrar estadísticas
    print("\n📈 Estadísticas de carga:")
    print(f"  - Marcas únicas: {df['marca'].nunique()}")
    print(f"  - Modelos únicos: {df['modelo'].nunique()}")
    print(f"  - Sistemas únicos: {df['sistema'].nunique()}")
    print(f"  - SKUs únicos: {df['sku'].nunique()}")
    print(f"  - Cantidad promedio (rango): {df['cantidad_promedio'].min():.2f} - {df['cantidad_promedio'].max():.2f}")
    print(f"  - Frecuencia de fallos (rango): {df['frecuencia_fallos_historico'].min()} - {df['frecuencia_fallos_historico'].max()}")
    
    return len(df)


def main():
    print("=" * 80)
    print("PASO 1: CARGAR MAPEO CONSUMO_SISTEMA_MODELO")
    print("=" * 80)
    
    try:
        # Crear tabla
        crear_tabla_consumo_sistema_modelo()
        
        # Cargar datos
        num_registros = cargar_consumo_sistema_modelo()
        
        if num_registros > 0:
            print("\n" + "=" * 80)
            print("✅ PASO 1 COMPLETADO EXITOSAMENTE")
            print("=" * 80)
            print("\nPróximo paso: PASO 2 - Cargar consumo_sku_historico")
            return 0
        else:
            print("\n⚠️  No se cargaron registros. Revisa los datos.")
            return 1
            
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
