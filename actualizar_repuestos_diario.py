#!/usr/bin/env python3
"""
ACTUALIZAR REPUESTOS DIARIO
=============================

Actualiza estado de repuestos combinando:
1. Consumo histórico (desde consumo_historico_cache)
2. Intervenciones recomendadas próximas (30 días)
3. Stock actual en repuestos_maestro

EJECUCIÓN: Diariamente (después de ejecutar_scoring.py)
DURACIÓN: ~5-10 segundos (muy rápido, solo lee cache)

Uso:
    uv run python actualizar_repuestos_diario.py

Output:
    - Inserciones en tabla 'paneles_repuestos'
    - Log detallado
    - Resumen final

Tablas requeridas:
    - paneles_repuestos
    - consumo_historico_cache (actualizado domingo por calcular_consumo_historico.py)
    - repuestos_maestro
    - intervenciones_sugeridas
    - mapeo_sistemas
"""

import os
import sys
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import logging

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no configurada en .env")
    sys.exit(1)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('actualizar_repuestos_diario.log')
    ]
)
log = logging.getLogger(__name__)

# ============================================================================
# CONEXIÓN A BD
# ============================================================================

def get_connection():
    """Obtiene conexión a Supabase."""
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        return conn
    except Exception as e:
        log.error(f"Error conectando a BD: {e}")
        return None


def query_db(query_sql, params=None):
    """Ejecuta query y retorna resultado como dict list o None si error."""
    conn = get_connection()
    if conn is None:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query_sql, params)
            result = cur.fetchall()
        return result
    except Exception as e:
        log.warning(f"Query fallida: {str(e)[:100]}")
        return None
    finally:
        conn.close()


def check_table_exists(table_name: str) -> bool:
    """Verifica si una tabla existe en el schema public."""
    result = query_db("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        ) AS existe;
    """, (table_name,))
    if result:
        return result[0]['existe']
    return False

# ============================================================================
# FUNCIONES DE CÁLCULO
# ============================================================================

def obtener_consumo_del_cache() -> dict:
    """
    Lee consumo histórico desde consumo_historico_cache.
    
    Retorna: {(sistema, sku): cantidad_promedio, ...}
    """
    resultado = query_db("""
        SELECT
            sistema,
            sku,
            cantidad_promedio_por_intervencion
        FROM consumo_historico_cache
    """)
    
    if not resultado:
        log.warning("⚠️ Cache de consumo histórico está vacío")
        return {}
    
    consumo_dict = {
        (row['sistema'], row['sku']): row['cantidad_promedio_por_intervencion']
        for row in resultado
    }
    
    log.info(f"✓ Cargados {len(consumo_dict)} registros de consumo del cache")
    return consumo_dict


def obtener_intervenciones_proximas() -> dict:
    """
    Obtiene intervenciones recomendadas próximas (30 días) por sistema.
    
    Retorna: {sistema: n_intervenciones, ...}
    """
    resultado = query_db("""
        SELECT
            LOWER(ms.sistema_repuestos) AS sistema,
            COUNT(*) AS n_intervenciones_proximas
        FROM intervenciones_sugeridas i
        JOIN mapeo_sistemas ms ON LOWER(i.sistema) = LOWER(ms.sistema_fallas)
        WHERE i.h30 = 1 AND i.sistema IS NOT NULL
        GROUP BY LOWER(ms.sistema_repuestos)
    """)
    
    if not resultado:
        log.warning("⚠️ No hay intervenciones recomendadas para próximos 30 días")
        return {}
    
    intervenciones_dict = {
        row['sistema']: row['n_intervenciones_proximas']
        for row in resultado
    }
    
    log.info(f"✓ Encontradas intervenciones en {len(intervenciones_dict)} sistemas")
    return intervenciones_dict


def actualizar_repuestos_diario() -> list:
    """
    Calcula stock requerido para todos los repuestos.
    
    Retorna lista de dicts con stock_actual, stock_requerido, brecha, etc.
    """
    
    # Verificar tablas requeridas
    tablas_requeridas = [
        "paneles_repuestos",
        "consumo_historico_cache",
        "repuestos_maestro",
        "intervenciones_sugeridas",
        "mapeo_sistemas"
    ]
    
    for tabla in tablas_requeridas:
        if not check_table_exists(tabla):
            log.error(f"❌ Tabla '{tabla}' no existe")
            return []
    
    log.info("✓ Todas las tablas requeridas existen")
    
    # PASO 1: Cargar consumo del cache
    log.info("  → Cargando consumo histórico del cache...")
    consumo_dict = obtener_consumo_del_cache()
    if not consumo_dict:
        return []
    
    # PASO 2: Obtener intervenciones próximas
    log.info("  → Obteniendo intervenciones próximas (30 días)...")
    intervenciones_dict = obtener_intervenciones_proximas()
    if not intervenciones_dict:
        log.warning("⚠️ Sin intervenciones próximas, aún continuamos...")
    
    # PASO 3: Obtener repuestos maestro y calcular stock requerido
    log.info("  → Calculando stock requerido para todos los repuestos...")
    repuestos_maestro = query_db("""
        SELECT
            sku,
            descripcion,
            LOWER(sistema) AS sistema,
            stock_actual,
            criticidad,
            lead_time_dias_promedio,
            costo_unitario_clp
        FROM repuestos_maestro
        WHERE sku IS NOT NULL
    """)
    
    if not repuestos_maestro:
        log.warning("⚠️ No hay repuestos en maestro")
        return []
    
    rows = []
    for rep in repuestos_maestro:
        sistema = rep['sistema']
        sku = rep['sku']
        stock_actual = rep['stock_actual'] or 0
        
        # Obtener cantidad promedio consumida (del cache)
        cantidad_promedio = consumo_dict.get((sistema, sku), 0)
        
        # Obtener número de intervenciones próximas
        n_intervenciones = intervenciones_dict.get(sistema, 0)
        
        # Calcular stock requerido
        stock_requerido = cantidad_promedio * n_intervenciones
        
        # Calcular brecha
        brecha = stock_actual - stock_requerido
        
        # Solo incluir si hay consumo histórico o intervenciones próximas
        if cantidad_promedio > 0 or n_intervenciones > 0:
            rows.append({
                'sku': sku,
                'descripcion': rep['descripcion'],
                'sistema': sistema,
                'stock_actual': float(stock_actual),
                'cantidad_promedio_por_intervencion': float(cantidad_promedio),
                'n_intervenciones_proximas': int(n_intervenciones),
                'stock_requerido': float(stock_requerido),
                'brecha': float(brecha),
                'criticidad': rep['criticidad'],
                'lead_time_dias': rep['lead_time_dias_promedio'],
                'costo_unitario_clp': rep['costo_unitario_clp']
            })
    
    log.info(f"✓ Procesados {len(rows)} repuestos con stock requerido")
    return rows


def insertar_repuesto(rep: dict) -> bool:
    """Inserta o actualiza un repuesto en paneles_repuestos."""
    
    delete_q = """
        DELETE FROM paneles_repuestos
        WHERE sku = %s
          AND DATE(fecha_calculo) = CURRENT_DATE
    """
    
    insert_q = """
        INSERT INTO paneles_repuestos
        (sku, descripcion, sistema, stock_actual, 
         cantidad_promedio_por_intervencion, n_intervenciones_proximas,
         stock_requerido, brecha, criticidad, lead_time_dias, 
         costo_unitario_clp, fecha_calculo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    """
    
    conn = get_connection()
    if conn is None:
        log.error(f"Insert fallido [{rep['sku']}]: sin conexión a BD")
        return False
    
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(delete_q, (rep['sku'],))
                cur.execute(insert_q, (
                    rep['sku'],
                    rep['descripcion'],
                    rep['sistema'],
                    rep['stock_actual'],
                    rep['cantidad_promedio_por_intervencion'],
                    rep['n_intervenciones_proximas'],
                    rep['stock_requerido'],
                    rep['brecha'],
                    rep['criticidad'],
                    rep['lead_time_dias'],
                    rep['costo_unitario_clp']
                ))
        
        brecha_str = f"({rep['brecha']:+.0f})" if rep['brecha'] != 0 else ""
        log.info(f"✓ {rep['sku']:12s} | {rep['sistema']:25s} | "
                f"stock={rep['stock_actual']:.0f} | req={rep['stock_requerido']:.1f} {brecha_str}")
        return True
    except Exception as e:
        log.error(f"Insert fallido [{rep['sku']}]: {str(e)[:80]}")
        return False
    finally:
        conn.close()


# ============================================================================
# ORQUESTADOR PRINCIPAL
# ============================================================================

def main():
    """Ejecuta actualización diaria de repuestos."""
    
    log.info("\n" + "=" * 90)
    log.info("📦 ACTUALIZAR REPUESTOS DIARIO (usando cache)")
    log.info("=" * 90)
    
    inicio = datetime.now()
    
    # Calcular
    repuestos = actualizar_repuestos_diario()
    
    if not repuestos:
        log.warning("⚠️ No hay repuestos para procesar")
        return
    
    log.info(f"\n📋 Procesando {len(repuestos)} SKUs")
    log.info("-" * 90)
    
    # Insertar
    conteo = {'exitosos': 0, 'fallidos': 0}
    
    for rep in repuestos:
        if insertar_repuesto(rep):
            conteo['exitosos'] += 1
        else:
            conteo['fallidos'] += 1
    
    # Resumen
    duracion = (datetime.now() - inicio).total_seconds()
    
    log.info("\n" + "=" * 90)
    log.info(f"✅ RESUMEN FINAL")
    log.info(f"   Exitosos: {conteo['exitosos']}")
    log.info(f"   Fallidos: {conteo['fallidos']}")
    log.info(f"   Duración: {duracion:.1f}s")
    log.info("⏭️  Próximo en pipeline: generar_plan_repuestos_financiero.py")
    log.info("   (Ejecutado automáticamente por ejecutar_pipeline_diario.sh)\n")
    log.info("=" * 90 + "\n")


if __name__ == "__main__":
    main()
