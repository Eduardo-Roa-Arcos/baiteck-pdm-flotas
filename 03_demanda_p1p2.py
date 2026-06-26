#!/usr/bin/env python3
"""
PASO 3: Calcular demanda proyectada para P1/P2
==============================================

Integra predicciones con mapeo de consumo para calcular demanda real.

Flujo:
1. Lee P1 + P2 de scoring_resultados
2. Para cada activo: obtiene marca, modelo, sistema_en_riesgo
3. Busca en consumo_sistema_modelo qué SKUs se necesitan
4. Proyecta demanda a 30 días (suma de todos los activos P1/P2)
5. Compara con consumo histórico promedio
6. Calcula cobertura (días) basado en demanda predicha
7. Define acción (OK, Comprar, Comprar urgente)

Resultado: tabla repuestos_panel_criticos (lista de SKUs con acciones para taller)
"""

import sys
sys.path.insert(0, '/mnt/project')

import pandas as pd
from sqlalchemy import text
from src.db import engine
from datetime import datetime

def crear_tabla_repuestos_panel():
    """Crea tabla repuestos_panel_criticos si no existe."""
    with engine.begin() as conn:
        # Dropear si existe (para evitar conflictos de constraints)
        conn.execute(text("DROP TABLE IF EXISTS repuestos_panel_criticos CASCADE"))
    
    query = text("""
        CREATE TABLE IF NOT EXISTS repuestos_panel_criticos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sku TEXT NOT NULL,
            descripcion TEXT,
            stock_actual NUMERIC,
            demanda_30d_prediccion NUMERIC NOT NULL,
            demanda_30d_historico NUMERIC,
            lead_time_dias NUMERIC,
            cobertura_dias NUMERIC,
            criticidad TEXT,
            accion TEXT,
            delta_demanda NUMERIC,
            fecha_calculo TIMESTAMP DEFAULT NOW()
        );
    """)
    with engine.begin() as conn:
        conn.execute(query)
        print("✅ Tabla repuestos_panel_criticos creada/verificada")


def calcular_demanda_proyectada():
    """
    Calcula demanda proyectada para P1/P2.
    
    Estrategia:
    - Toma todos los activos en P1 y P2
    - Para cada uno: marca + modelo + sistema_en_riesgo
    - Busca en consumo_sistema_modelo qué SKUs se consumen
    - Suma cantidades = demanda total proyectada
    """
    
    print("\n📊 Calculando demanda proyectada para P1/P2...")
    
    query = text("""
        WITH activos_p1p2 AS (
            SELECT DISTINCT
                sr.activo_id,
                a.marca,
                a.modelo,
                sr.sistema_en_riesgo,
                sr.prioridad
            FROM scoring_resultados sr
            JOIN activos a ON sr.activo_id = a.activo_id
            WHERE sr.prioridad IN ('P1_critica', 'P2_alta')
        ),
        consumo_por_activo AS (
            SELECT
                ap.sku,
                SUM(ap.cantidad_promedio) AS consumo_total_proyectado,
                COUNT(DISTINCT ap.sku) AS num_sistemas,
                MAX(ap.frecuencia_fallos_historico) AS frecuencia_fallos_historico
            FROM activos_p1p2 a
            JOIN consumo_sistema_modelo ap 
                ON a.marca = ap.marca 
                AND a.modelo = ap.modelo 
                AND a.sistema_en_riesgo = ap.sistema
            GROUP BY ap.sku
        )
        SELECT
            cp.sku,
            rm.descripcion,
            rm.stock_actual,
            ROUND(cp.consumo_total_proyectado, 2) AS demanda_prediccion,
            csh.consumo_promedio_mensual AS demanda_historico,
            rm.lead_time_dias_promedio,
            rm.criticidad
        FROM consumo_por_activo cp
        LEFT JOIN repuestos_maestro rm ON cp.sku = rm.sku
        LEFT JOIN consumo_sku_historico csh ON cp.sku = csh.sku
        ORDER BY cp.consumo_total_proyectado DESC
    """)
    
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    
    if len(df) == 0:
        print("⚠️  No hay activos P1/P2, o sin consumo proyectado")
        return None
    
    print(f"✅ Se calculó demanda para {len(df)} SKUs únicos")
    
    return df


def calcular_metricas(df):
    """
    Calcula métricas de cobertura y acciones.
    
    Métricas:
    - Cobertura (días) = (stock_actual / demanda_30d) * 30
    - Delta = demanda_predicción vs demanda_histórico
    - Acción = OK / Comprar / Comprar urgente
    """
    
    print("\n🔢 Calculando cobertura y acciones...")
    
    # Llenar NaN
    df = df.fillna(0)
    
    # Cobertura en días
    # Si demanda = 0, no calcular cobertura (usar N/A)
    df['cobertura_dias'] = df.apply(
        lambda row: (row['stock_actual'] / row['demanda_prediccion'] * 30) 
                    if row['demanda_prediccion'] > 0 else None,
        axis=1
    )
    
    # Lead time (si no existe, asumir 7 días)
    df['lead_time_dias'] = df['lead_time_dias_promedio'].fillna(7)
    
    # Delta demanda (diferencia porcentual)
    df['delta_demanda'] = df.apply(
        lambda row: ((row['demanda_prediccion'] - row['demanda_historico']) / 
                    row['demanda_historico'] * 100) 
                    if row['demanda_historico'] > 0 else 0,
        axis=1
    )
    
    # Lógica de Acción
    def determinar_accion(row):
        if row['demanda_prediccion'] == 0:
            return "N/A"
        
        cobertura = row['cobertura_dias']
        lead_time = row['lead_time_dias']
        
        if cobertura is None or pd.isna(cobertura):
            # Sin stock
            return "🔴 Comprar urgente"
        elif cobertura < lead_time:
            # No alcanza para la reposición
            return "🔴 Comprar urgente"
        elif cobertura < (lead_time + 7):
            # Marginal
            return "🟡 Comprar"
        else:
            # Suficiente cobertura
            return "✅ OK"
    
    df['accion'] = df.apply(determinar_accion, axis=1)
    
    print(f"✅ Métricas calculadas")
    
    return df

def cargar_panel(df):
    """Carga datos en tabla repuestos_panel_criticos.
    
    Lógica:
    - Primero: todos los SKUs con acción "Comprar urgente" o "Comprar"
    - Luego: Top 10 SKUs con "OK" ordenados por mayor demanda
    """
    
    print("\n📝 Cargando panel de repuestos críticos...")
    
    # Seleccionar y renombrar columnas
    df_load = df[[
        'sku', 'descripcion', 'stock_actual',
        'demanda_prediccion', 'demanda_historico',
        'lead_time_dias', 'cobertura_dias', 'criticidad',
        'accion', 'delta_demanda'
    ]].copy()
    
    df_load.columns = [
        'sku', 'descripcion', 'stock_actual',
        'demanda_30d_prediccion', 'demanda_30d_historico',
        'lead_time_dias', 'cobertura_dias', 'criticidad',
        'accion', 'delta_demanda'
    ]
    
    # Filtrar por acción
    urgentes = df_load[df_load['accion'].str.contains('urgente', case=False, na=False)]
    comprar = df_load[df_load['accion'].str.contains('Comprar', case=False, na=False) & 
                      ~df_load['accion'].str.contains('urgente', case=False, na=False)]
    ok = df_load[df_load['accion'] == '✅ OK'].nlargest(10, 'demanda_30d_prediccion')
    
    # Concatenar: urgentes → comprar → top 10 OK
    df_final = pd.concat([urgentes, comprar, ok], ignore_index=True)
    
    with engine.begin() as conn:
        # Limpiar tabla anterior
        conn.execute(text("DELETE FROM repuestos_panel_criticos"))
        
        # Batch insert (solo registros filtrados)
        df_final.to_sql('repuestos_panel_criticos', conn, if_exists='append', index=False)
    
    print(f"✅ {len(df_final)} SKUs cargados en panel ({len(urgentes)} urgentes + {len(comprar)} comprar + {len(ok)} OK)")
    
    return df_final

def mostrar_resumenes(df):
    """Muestra resúmenes del panel."""
    
    print("\n" + "=" * 80)
    print("RESUMEN DE ACCIONES REQUERIDAS")
    print("=" * 80)
    
    # Por acción
    resumen = df['accion'].value_counts()
    print("\n📊 Distribución por acción:")
    for accion, count in resumen.items():
        print(f"  {accion}: {count} SKUs")
    
    # Top críticos (Comprar urgente)
    urgentes = df[df['accion'].str.contains('urgente', case=False, na=False)]
    if len(urgentes) > 0:
        print(f"\n🔴 SKUs que requieren COMPRA URGENTE ({len(urgentes)}):")
        print(urgentes[['sku', 'descripcion', 'stock_actual', 'demanda_30d_prediccion', 
                        'cobertura_dias', 'lead_time_dias']].head(10).to_string(index=False))
    
    # Top consumidos (por demanda predicha)
    print(f"\n📈 Top 15 SKUs por demanda proyectada:")
    top = df.nlargest(15, 'demanda_30d_prediccion')[
        ['sku', 'descripcion', 'demanda_30d_prediccion', 'demanda_30d_historico', 
         'delta_demanda', 'stock_actual', 'accion']
    ]
    print(top.to_string(index=False))

def main():
    print("=" * 80)
    print("PASO 3: CALCULAR DEMANDA PROYECTADA P1/P2")
    print("=" * 80)
    
    try:
        # Crear tabla
        crear_tabla_repuestos_panel()
        
        # Calcular demanda
        df = calcular_demanda_proyectada()
        if df is None:
            return 1
        
        # Calcular métricas
        df = calcular_metricas(df)
        
        # Cargar panel
        df = cargar_panel(df)
        
        # Mostrar resúmenes
        mostrar_resumenes(df)
        
        print("\n" + "=" * 80)
        print("✅ PASO 3 COMPLETADO EXITOSAMENTE")
        print("=" * 80)
        print("\n📊 Panel de demanda P1/P2 generado:")
        print("   Tabla: repuestos_panel_criticos")
        print(f"   Registros: {len(df)}\n")        
        print("⏭️  Próximo en pipeline: actualizar_repuestos_diario.py")
        print("   (Ejecutado automáticamente por ejecutar_pipeline_diario.sh)\n")        
        return 0
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
