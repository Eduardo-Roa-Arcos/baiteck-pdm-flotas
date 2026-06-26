# validar_clasificacion.py
"""
BAITECK — Validador y diagnóstico de clasificación de fallas

Propósito:
  Verificar que la clasificación se ejecutó correctamente y mostrar estadísticas.
  
Verifica:
  1. Que todas las OT tengan evento de falla
  2. Distribución de confianza
  3. Distribución por sistema/componente/modo
  4. OT huérfanas (sin taxonomía válida)
  5. Duplicados

Uso:
  uv run python validar_clasificacion.py [--detalle]
"""

import sys
import os
import pandas as pd
from sqlalchemy import text, create_engine
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def get_engine():
    """Obtiene la conexión a Supabase desde .env"""
    from dotenv import load_dotenv
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("ERROR: DATABASE_URL no está en .env")
        sys.exit(1)
    return create_engine(database_url, pool_pre_ping=True)

engine = get_engine()

def validar():
    """Ejecuta validaciones completas"""
    
    logger.info("=" * 100)
    logger.info("VALIDADOR DE CLASIFICACIÓN DE FALLAS")
    logger.info("=" * 100)
    
    # Query 1: Conteo de OT y eventos
    logger.info("\n[1] CONTEO BÁSICO")
    query1 = text("""
        SELECT
            COUNT(*) as total_ot,
            COUNT(CASE WHEN ot.ot_id IN (SELECT ot_id FROM ot_falla_evento) THEN 1 END) as con_evento,
            COUNT(CASE WHEN ot.ot_id NOT IN (SELECT ot_id FROM ot_falla_evento WHERE ot_id IS NOT NULL) THEN 1 END) as sin_evento
        FROM ordenes_trabajo ot
    """)
    with engine.connect() as conn:
        resultado = conn.execute(query1).fetchone()
        total, con_evento, sin_evento = resultado
    
    print(f"   Total órdenes de trabajo:     {total}")
    print(f"   Con evento de falla:          {con_evento}")
    print(f"   Sin evento de falla:          {sin_evento}")
    print(f"   Cobertura:                    {100*con_evento/total:.1f}%")
    
    # Query 2: Distribución de confianza
    logger.info("\n[2] DISTRIBUCIÓN DE CONFIANZA")
    query2 = text("""
        SELECT
            CASE 
                WHEN confianza >= 0.8 THEN 'Muy alta (≥0.80)'
                WHEN confianza >= 0.6 THEN 'Alta (0.60-0.79)'
                WHEN confianza >= 0.4 THEN 'Media (0.40-0.59)'
                WHEN confianza >= 0.2 THEN 'Baja (0.20-0.39)'
                ELSE 'Muy baja (<0.20)'
            END as rango_confianza,
            COUNT(*) as cantidad,
            ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM ot_falla_evento), 1) as porcentaje
        FROM ot_falla_evento
        WHERE confianza IS NOT NULL
        GROUP BY rango_confianza
        ORDER BY 
            CASE 
                WHEN confianza >= 0.8 THEN 1
                WHEN confianza >= 0.6 THEN 2
                WHEN confianza >= 0.4 THEN 3
                WHEN confianza >= 0.2 THEN 4
                ELSE 5
            END
    """)
    with engine.connect() as conn:
        df_confianza = pd.read_sql(query2, conn)
    
    for _, row in df_confianza.iterrows():
        print(f"   {row['rango_confianza']:25s} : {row['cantidad']:3.0f} ({row['porcentaje']:5.1f}%)")
    
    # Query 3: Distribución por sistema
    logger.info("\n[3] DISTRIBUCIÓN POR SISTEMA")
    query3 = text("""
        SELECT
            tf.sistema,
            COUNT(*) as cantidad,
            ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM ot_falla_evento), 1) as porcentaje,
            COUNT(DISTINCT ofe.activo_id) as activos_afectados,
            ROUND(AVG(ofe.confianza), 2) as confianza_promedio
        FROM ot_falla_evento ofe
        LEFT JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
        GROUP BY tf.sistema
        ORDER BY cantidad DESC
    """)
    with engine.connect() as conn:
        df_sistema = pd.read_sql(query3, conn)
    
    if len(df_sistema) > 0:
        for _, row in df_sistema.iterrows():
            print(f"   {row['sistema']:20s}: {row['cantidad']:3.0f} ({row['porcentaje']:5.1f}%) | "
                  f"Activos: {row['activos_afectados']:2.0f} | Conf: {row['confianza_promedio']:.2f}")
    else:
        print("   (sin datos)")
    
    # Query 4: Distribución por componente (top 10)
    logger.info("\n[4] TOP 10 COMPONENTES MÁS AFECTADOS")
    query4 = text("""
        SELECT
            tf.sistema,
            tf.componente,
            COUNT(*) as cantidad,
            ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM ot_falla_evento), 1) as porcentaje
        FROM ot_falla_evento ofe
        LEFT JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
        GROUP BY tf.sistema, tf.componente
        ORDER BY cantidad DESC
        LIMIT 10
    """)
    with engine.connect() as conn:
        df_componente = pd.read_sql(query4, conn)
    
    if len(df_componente) > 0:
        for i, (_, row) in enumerate(df_componente.iterrows(), 1):
            print(f"   [{i:2d}] {row['sistema']:15s} → {row['componente']:25s}: {row['cantidad']:3.0f} ({row['porcentaje']:5.1f}%)")
    else:
        print("   (sin datos)")
    
    # Query 5: Distribución por fuente
    logger.info("\n[5] DISTRIBUCIÓN POR FUENTE DE CLASIFICACIÓN")
    query5 = text("""
        SELECT
            fuente,
            COUNT(*) as cantidad,
            ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM ot_falla_evento), 1) as porcentaje
        FROM ot_falla_evento
        GROUP BY fuente
        ORDER BY cantidad DESC
    """)
    with engine.connect() as conn:
        df_fuente = pd.read_sql(query5, conn)
    
    if len(df_fuente) > 0:
        for _, row in df_fuente.iterrows():
            print(f"   {row['fuente']:20s}: {row['cantidad']:3.0f} ({row['porcentaje']:5.1f}%)")
    else:
        print("   (sin datos)")
    
    # Query 6: OT sin taxonomía válida
    logger.info("\n[6] OT SIN TAXONOMÍA VÁLIDA (HUÉRFANAS)")
    query6 = text("""
        SELECT
            ofe.ot_id,
            ofe.activo_id,
            ofe.taxonomia_id,
            ot.descripcion
        FROM ot_falla_evento ofe
        LEFT JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
        LEFT JOIN ordenes_trabajo ot ON ofe.ot_id = ot.ot_id
        WHERE tf.taxonomia_id IS NULL
        LIMIT 10
    """)
    with engine.connect() as conn:
        df_huerfanas = pd.read_sql(query6, conn)
    
    if len(df_huerfanas) > 0:
        print(f"   ⚠️  Encontradas {len(df_huerfanas)} OT con taxonomía inválida (mostrando primeras 10):")
        for _, row in df_huerfanas.iterrows():
            print(f"      • OT {row['ot_id']}: {row['descripcion'][:50]}...")
    else:
        print("   ✅ Ninguna OT huérfana")
    
    # Query 7: Duplicados
    logger.info("\n[7] ÓRDENES CON MÚLTIPLES EVENTOS")
    query7 = text("""
        SELECT
            ot_id,
            COUNT(*) as cantidad_eventos
        FROM ot_falla_evento
        WHERE ot_id IS NOT NULL
        GROUP BY ot_id
        HAVING COUNT(*) > 1
        LIMIT 10
    """)
    with engine.connect() as conn:
        df_duplicados = pd.read_sql(query7, conn)
    
    if len(df_duplicados) > 0:
        print(f"   ⚠️  Encontradas {len(df_duplicados)} OT con múltiples eventos:")
        for _, row in df_duplicados.iterrows():
            print(f"      • OT {row['ot_id']}: {row['cantidad_eventos']} eventos")
    else:
        print("   ✅ Ninguna OT con múltiples eventos")
    
    # Query 8: Últimas OT clasificadas
    logger.info("\n[8] ÚLTIMAS 5 OT CLASIFICADAS")
    query8 = text("""
        SELECT
            ofe.ot_id,
            ofe.activo_id,
            tf.sistema,
            tf.componente,
            mf.modo,
            ofe.confianza,
            ofe.fuente,
            ofe.created_at
        FROM ot_falla_evento ofe
        LEFT JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
        LEFT JOIN modo_falla mf ON tf.id_modo_falla = mf.id_modo_falla
        ORDER BY ofe.created_at DESC
        LIMIT 5
    """)
    with engine.connect() as conn:
        df_ultimas = pd.read_sql(query8, conn)
    
    if len(df_ultimas) > 0:
        for _, row in df_ultimas.iterrows():
            print(f"   • OT {row['ot_id']:15s} ({row['activo_id']:10s}): "
                  f"{row['sistema']:15s} → {row['modo']:30s} (conf: {row['confianza']:.2f})")
    else:
        print("   (sin datos)")
    
    # Resumen final
    logger.info("\n" + "=" * 100)
    logger.info("RECOMENDACIONES")
    logger.info("=" * 100)
    
    recomendaciones = []
    
    if sin_evento > 0:
        recomendaciones.append(f"⚠️  {sin_evento} OT aún no clasificadas. Ejecutar: uv run python clasificar_fallas.py")
    
    if len(df_huerfanas) > 0:
        recomendaciones.append(f"⚠️  {len(df_huerfanas)} OT con taxonomía inválida. Verificar que la taxonomía no fue truncada.")
    
    baja_conf = df_confianza[df_confianza['rango_confianza'].str.contains('Muy baja|Baja')]
    if len(baja_conf) > 0:
        total_baja = baja_conf['cantidad'].sum()
        recomendaciones.append(f"⚠️  {total_baja} clasificaciones con confianza baja. Considerar revisar manualmente.")
    
    if len(recomendaciones) == 0:
        recomendaciones.append("✅ Todo está en orden. Clasificación lista para usar.")
    
    for recom in recomendaciones:
        print(f"   {recom}")
    
    logger.info("=" * 100)

if __name__ == "__main__":
    try:
        validar()
    except Exception as e:
        logger.error(f"❌ ERROR: {str(e)}", exc_info=True)
        sys.exit(1)
