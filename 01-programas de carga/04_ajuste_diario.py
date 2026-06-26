#!/usr/bin/env python3
"""
PASO 2: Ajuste diario - Actualizar consumo_sistema_modelo
===========================================================

Ejecutar DIARIAMENTE después de que nuevas OTs se registren.

Lógica:
1. Lee última fecha de ejecución en consumo_sistema_modelo
2. Busca todos los repuestos_consumidos desde esa fecha
3. Recalcula cantidad_promedio y frecuencia_fallos
4. Hace UPSERT en consumo_sistema_modelo (actualiza valores existentes)

Resultado: tabla consumo_sistema_modelo siempre reflejará histórico completo + últimos datos
"""

import sys
sys.path.insert(0, '/mnt/project')

import pandas as pd
from sqlalchemy import text
from src.db import engine
from datetime import datetime

def obtener_ultima_fecha_calculo():
    """Obtiene la fecha de última ejecución de consumo_sistema_modelo."""
    query = text("SELECT MAX(fecha_calculo) as ultima_fecha FROM consumo_sistema_modelo")
    with engine.connect() as conn:
        result = conn.execute(query).fetchone()
        ultima_fecha = result[0] if result[0] else None
    
    if ultima_fecha:
        print(f"📅 Última carga: {ultima_fecha.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("⚠️  Tabla consumo_sistema_modelo vacía. Ejecuta 01_carga_consumo.py primero.")
    
    return ultima_fecha


def calcular_nuevos_datos(ultima_fecha):
    """
    Calcula datos actualizados desde ultima_fecha hasta ahora.
    
    Incluye:
    - Todos los repuestos consumidos desde ultima_fecha
    - Agrupados por marca + modelo + sistema + sku
    - Con nuevos promedios y frecuencias
    """
    
    if ultima_fecha is None:
        print("❌ No hay fecha anterior. Ejecuta 01_carga_consumo.py primero.")
        return None
    
    print(f"\n🔄 Buscando nuevos datos desde {ultima_fecha.strftime('%Y-%m-%d')}...")
    
    query = text("""
        WITH nuevos_datos AS (
            SELECT
                a.marca,
                a.modelo,
                tf.sistema,
                rc.sku,
                rc.cantidad,
                ofe.ot_id,
                rc.created_at
            FROM ordenes_trabajo ot
            JOIN ot_falla_evento ofe ON ot.ot_id = ofe.ot_id
            JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
            JOIN repuestos_consumidos rc ON ot.ot_id = rc.ot_id
            JOIN activos a ON ot.activo_id = a.activo_id
            WHERE rc.created_at >= :ultima_fecha
              AND a.marca IS NOT NULL
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
            COUNT(DISTINCT ot_id)::INTEGER AS frecuencia_fallos_nuevo,
            COUNT(*)::INTEGER AS num_registros_nuevo
        FROM nuevos_datos
        GROUP BY marca, modelo, sistema, sku
        ORDER BY marca, modelo, sistema, sku
    """)
    
    with engine.connect() as conn:
        df_nuevos = pd.read_sql(query, {"ultima_fecha": ultima_fecha}, conn)
    
    if len(df_nuevos) == 0:
        print("✅ Sin nuevos datos desde última ejecución")
        return None
    
    print(f"✅ Se encontraron {len(df_nuevos)} combinaciones con nuevos datos")
    print(f"\n📋 Preview de nuevos datos:")
    print(df_nuevos.head(10).to_string())
    
    return df_nuevos


def combinar_datos_historicos(df_nuevos):
    """
    Combina datos históricos (en tabla) con nuevos datos.
    
    Calcula:
    - Promedio ponderado entre datos viejos y nuevos
    - Suma de frecuencias
    """
    
    print("\n🔀 Combinando datos históricos con nuevos...")
    
    query = text("""
        SELECT
            marca,
            modelo,
            sistema,
            sku,
            cantidad_promedio AS cantidad_promedio_viejo,
            frecuencia_fallos_historico AS frecuencia_vieja,
            num_registros_analizados AS num_registros_viejo
        FROM consumo_sistema_modelo
    """)
    
    with engine.connect() as conn:
        df_viejo = pd.read_sql(query, conn)
    
    # Merge: nuevos datos con viejos
    df_merge = df_nuevos.merge(
        df_viejo,
        on=['marca', 'modelo', 'sistema', 'sku'],
        how='outer',
        suffixes=('_nuevo', '_viejo')
    )
    
    # Llenar NaN con 0 para el cálculo
    df_merge = df_merge.fillna(0)
    
    # Calcular promedios ponderados
    df_merge['cantidad_promedio_final'] = (
        (df_merge['cantidad_promedio_nuevo'] * df_merge['num_registros_nuevo'] + 
         df_merge['cantidad_promedio_viejo'] * df_merge['num_registros_viejo']) /
        (df_merge['num_registros_nuevo'] + df_merge['num_registros_viejo'])
    ).round(2)
    
    # Sumar frecuencias
    df_merge['frecuencia_final'] = (
        df_merge['frecuencia_nuevo'] + df_merge['frecuencia_vieja']
    ).astype(int)
    
    # Sumar registros
    df_merge['num_registros_final'] = (
        df_merge['num_registros_nuevo'] + df_merge['num_registros_viejo']
    ).astype(int)
    
    # Seleccionar columnas necesarias
    df_resultado = df_merge[[
        'marca', 'modelo', 'sistema', 'sku',
        'cantidad_promedio_final', 'frecuencia_final', 'num_registros_final'
    ]].copy()
    
    df_resultado.columns = [
        'marca', 'modelo', 'sistema', 'sku',
        'cantidad_promedio', 'frecuencia_fallos_historico', 'num_registros_analizados'
    ]
    
    print(f"✅ Combinación completada: {len(df_resultado)} registros a actualizar")
    
    return df_resultado


def actualizar_tabla(df_actualizado):
    """
    Hace UPSERT en consumo_sistema_modelo con los datos actualizados.
    
    Actualiza tanto registros existentes como inserta nuevos.
    """
    
    print("\n📝 Actualizando tabla consumo_sistema_modelo...")
    
    with engine.begin() as conn:
        # Limpiar tabla (en ajuste diario, recalculamos desde cero con datos históricos)
        conn.execute(text("DELETE FROM consumo_sistema_modelo"))
        
        # Usar to_sql para batch insert
        df_actualizado.to_sql(
            'consumo_sistema_modelo',
            conn,
            if_exists='append',
            index=False
        )
    
    print(f"✅ {len(df_actualizado)} registros actualizados exitosamente")
    
    # Estadísticas
    print("\n📈 Estadísticas de actualización:")
    print(f"  - Marcas únicas: {df_actualizado['marca'].nunique()}")
    print(f"  - Modelos únicos: {df_actualizado['modelo'].nunique()}")
    print(f"  - Sistemas únicos: {df_actualizado['sistema'].nunique()}")
    print(f"  - SKUs únicos: {df_actualizado['sku'].nunique()}")
    print(f"  - Cantidad promedio (rango): {df_actualizado['cantidad_promedio'].min():.2f} - {df_actualizado['cantidad_promedio'].max():.2f}")
    print(f"  - Frecuencia de fallos (rango): {df_actualizado['frecuencia_fallos_historico'].min()} - {df_actualizado['frecuencia_fallos_historico'].max()}")


def main():
    print("=" * 80)
    print("AJUSTE DIARIO: ACTUALIZAR CONSUMO_SISTEMA_MODELO")
    print("=" * 80)
    
    try:
        # Paso 1: Obtener última fecha
        ultima_fecha = obtener_ultima_fecha_calculo()
        if ultima_fecha is None:
            return 1
        
        # Paso 2: Calcular nuevos datos
        df_nuevos = calcular_nuevos_datos(ultima_fecha)
        if df_nuevos is None:
            print("\n✅ Ajuste finalizado: sin cambios")
            return 0
        
        # Paso 3: Combinar datos históricos con nuevos
        df_actualizado = combinar_datos_historicos(df_nuevos)
        
        # Paso 4: Actualizar tabla
        actualizar_tabla(df_actualizado)
        
        print("\n" + "=" * 80)
        print("✅ AJUSTE DIARIO COMPLETADO EXITOSAMENTE")
        print("=" * 80)
        print("\nTabla consumo_sistema_modelo actualizada con todos los datos históricos")
        print(f"Próxima ejecución: mañana a la misma hora")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
