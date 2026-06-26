#!/usr/bin/env python3
"""
CALCULAR CONSUMO HISTÓRICO (CACHE)
===================================

Calcula consumo promedio por sistema y SKU (últimos 180 días).
Guarda en tabla consumo_historico_cache para uso diario.

EJECUCIÓN: Domingo noche (una vez por semana)
DURACIÓN: ~30 segundos

Uso:
    uv run python calcular_consumo_historico.py

Output:
    - Inserciones en tabla 'consumo_historico_cache'
    - Log detallado
    - Resumen final

Tablas requeridas:
    - consumo_historico_cache
    - repuestos_consumidos
    - ordenes_trabajo
    - ot_falla_evento
    - taxonomia_fallas
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
        logging.FileHandler('calcular_consumo_historico.log')
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


def execute_sql(query_sql, params=None):
    """Ejecuta INSERT/UPDATE sin retorno."""
    conn = get_connection()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(query_sql, params)
        conn.commit()
        return True
    except Exception as e:
        log.error(f"Execute fallido: {str(e)[:100]}")
        return False
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

def calcular_consumo_historico() -> dict:
    """
    Calcula consumo promedio por sistema y SKU (últimos 180 días).
    
    Retorna:
    {
        'n_registros': 1250,
        'n_sistemas': 12,
        'n_skus': 450
    }
    """
    
    # Verificar tablas requeridas
    tablas_requeridas = [
        "consumo_historico_cache",
        "repuestos_consumidos",
        "ordenes_trabajo",
        "ot_falla_evento",
        "taxonomia_fallas",
        "mapeo_sistemas"
    ]
    
    for tabla in tablas_requeridas:
        if not check_table_exists(tabla):
            log.error(f"❌ Tabla '{tabla}' no existe")
            return {}
    
    log.info("✓ Todas las tablas requeridas existen")
    
    # Calcular consumo histórico con mapeo de sistemas
    log.info("  → Calculando consumo histórico (últimos 180 días)...")
    
    resultado = query_db("""
        SELECT
            LOWER(ms.sistema_repuestos) AS sistema,
            rc.sku,
            SUM(rc.cantidad) / COUNT(DISTINCT rc.ot_id) AS cantidad_promedio_por_intervencion
        FROM repuestos_consumidos rc
        JOIN ordenes_trabajo ot ON rc.ot_id = ot.ot_id
        JOIN ot_falla_evento ofe ON ot.ot_id = ofe.ot_id
        JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
        JOIN mapeo_sistemas ms ON LOWER(tf.sistema) = LOWER(ms.sistema_fallas)
        WHERE ot.fecha_apertura >= CURRENT_DATE - INTERVAL '180 days'
          AND rc.sku IS NOT NULL
        GROUP BY LOWER(ms.sistema_repuestos), rc.sku
    """)
    
    if not resultado:
        log.warning("⚠️ No hay consumo histórico en últimos 180 días")
        return {}
    
    log.info(f"✓ Encontrado consumo para {len(resultado)} (sistema, SKU)")
    
    # Limpiar tabla anterior y actualizar
    log.info("  → Actualizando tabla consumo_historico_cache...")
    
    conn = get_connection()
    if conn is None:
        log.error("❌ Sin conexión a BD")
        return {}
    
    try:
        with conn:
            with conn.cursor() as cur:
                # Vaciar tabla
                cur.execute("DELETE FROM consumo_historico_cache")
                
                # Insertar nuevos registros
                for row in resultado:
                    cur.execute("""
                        INSERT INTO consumo_historico_cache
                        (sistema, sku, cantidad_promedio_por_intervencion, fecha_calculo)
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    """, (
                        row['sistema'],
                        row['sku'],
                        row['cantidad_promedio_por_intervencion']
                    ))
        
        log.info(f"✓ Insertados {len(resultado)} registros en cache")
        
        # Estadísticas
        stats = query_db("""
            SELECT
                COUNT(*) as n_registros,
                COUNT(DISTINCT sistema) as n_sistemas,
                COUNT(DISTINCT sku) as n_skus
            FROM consumo_historico_cache
        """)
        
        if stats:
            return {
                'n_registros': stats[0]['n_registros'],
                'n_sistemas': stats[0]['n_sistemas'],
                'n_skus': stats[0]['n_skus']
            }
        
        return {'n_registros': len(resultado)}
        
    except Exception as e:
        log.error(f"Error actualizando cache: {str(e)[:100]}")
        return {}
    finally:
        conn.close()

# ============================================================================
# ORQUESTADOR PRINCIPAL
# ============================================================================

def main():
    """Ejecuta cálculo de consumo histórico."""
    
    log.info("\n" + "=" * 90)
    log.info("📊 CÁLCULO DE CONSUMO HISTÓRICO (CACHE SEMANAL)")
    log.info("=" * 90)
    
    inicio = datetime.now()
    
    stats = calcular_consumo_historico()
    
    duracion = (datetime.now() - inicio).total_seconds()
    
    if stats:
        log.info("\n" + "=" * 90)
        log.info(f"✅ CACHE ACTUALIZADO")
        log.info(f"   Registros: {stats.get('n_registros', '?')}")
        log.info(f"   Sistemas: {stats.get('n_sistemas', '?')}")
        log.info(f"   SKUs: {stats.get('n_skus', '?')}")
        log.info(f"   Duración: {duracion:.1f}s")
        log.info("=" * 90 + "\n")
    else:
        log.error("\n❌ CACHE NO SE PUDO ACTUALIZAR\n")


if __name__ == "__main__":
    main()
