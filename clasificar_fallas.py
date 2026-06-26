# clasificar_fallas.py
"""
BAITECK — Clasificador automático de fallas desde órdenes de trabajo

Propósito:
  Recorrer TODA la tabla ordenes_trabajo y, para cada OT sin evento de falla registrado,
  clasificar automáticamente contra taxonomia_fallas extrayendo sistema, componente y modo_falla.
  
Flujo:
  1. Cargar taxonomía completa desde Supabase
  2. Cargar todas las OT no clasificadas (sin ot_falla_evento)
  3. Para cada OT:
     - Buscar coincidencias en descripción contra palabras_clave de taxonomía
     - Si hay coincidencia clara → insertar en ot_falla_evento (fuente='automático')
     - Si hay ambigüedad → registrar en CSV para revisión manual (fuente='pendiente_revision')
  4. Generar reporte de confianza y sugerencias

Uso:
  uv run python clasificar_fallas.py [--dry-run] [--confidence MIN] [--output FILE.csv]
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np
from datetime import date
from difflib import SequenceMatcher
from collections import defaultdict
import logging
from typing import Dict, List, Tuple, Optional
from sqlalchemy import text, create_engine

# ============================================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)8s | %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONEXIÓN A SUPABASE
# ============================================================================

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

# ============================================================================
# PASO 1: CARGAR TAXONOMÍA
# ============================================================================

def cargar_taxonomia() -> pd.DataFrame:
    """
    Carga la tabla taxonomia_fallas con JOIN a modo_falla para obtener palabras_claves.
    
    Estructura:
    - taxonomia_id
    - sistema
    - componente
    - subsistema
    - descripcion_estandar
    - id_modo_falla
    - modo (nombre del modo de falla)
    - palabras_claves (del modo_falla)
    - activo
    """
    query = text("""
        SELECT
            tf.taxonomia_id,
            tf.sistema,
            tf.componente,
            tf.subsistema,
            tf.descripcion_estandar,
            tf.id_modo_falla,
            mf.modo,
            mf.palabras_claves,
            tf.activo
        FROM taxonomia_fallas tf
        LEFT JOIN modo_falla mf ON tf.id_modo_falla = mf.id_modo_falla
        WHERE tf.activo = TRUE
        ORDER BY tf.sistema, tf.componente, tf.id_modo_falla
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    logger.info(f"✅ Taxonomía cargada: {len(df)} registros activos")
    return df

# ============================================================================
# PASO 2: CARGAR ÓRDENES SIN CLASIFICAR
# ============================================================================

def cargar_ordenes_trabajo_sin_clasificar() -> pd.DataFrame:
    """
    Carga TODAS las OT que no tienen evento de falla registrado.
    
    Criterio: ot_id NO existe en ot_falla_evento
    """
    query = text("""
        SELECT
            ot.ot_id,
            ot.activo_id,
            ot.fecha_apertura,
            ot.descripcion_falla,
            ot.sistema as sistema_actual,
            ot.componente as componente_actual
        FROM ordenes_trabajo ot
        WHERE ot.ot_id NOT IN (
            SELECT DISTINCT ot_id FROM ot_falla_evento WHERE ot_id IS NOT NULL
        )
        ORDER BY ot.fecha_apertura DESC
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    logger.info(f"📋 Órdenes sin clasificar: {len(df)} registros")
    return df

def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparación: minúsculas, espacios extras, sin puntuación"""
    if not isinstance(texto, str):
        return ""
    texto = texto.lower().strip()
    # Eliminar puntuación común
    for char in ['.,;:', '!?', '"\'']:
        texto = texto.replace(char, '')
    # Normalizar espacios
    texto = ' '.join(texto.split())
    return texto

def calcular_similitud(texto1: str, texto2: str) -> float:
    """Calcula similitud entre dos textos (0.0 a 1.0)"""
    return SequenceMatcher(None, texto1, texto2).ratio()

def clasificar_ot_individual(
    ot_id: str,
    descripcion: str,
    sistema_actual: Optional[str],
    componente_actual: Optional[str],
    taxonomia: pd.DataFrame
) -> Dict:
    """
    Clasifica UNA orden de trabajo contra taxonomía.
    
    Estrategia:
      1. Split descripción en palabras
      2. Para cada fila de taxonomía, buscar coincidencia en palabras_claves
      3. Calcular score de confianza basado en:
         - Número de palabras clave que coinciden
         - Similitud de texto
         - Coincidencia con sistema/componente actuales (si existen)
      4. Retornar mejor clasificación + score
    
    Returns:
        {
            'taxonomia_id': UUID o None,
            'sistema': str o None,
            'componente': str o None,
            'modo': str o None,
            'confianza': float (0.0 a 1.0),
            'motivo': str,
            'candidatos': List[Dict] (alternativas, para debug)
        }
    """
    
    desc_normalizada = normalizar_texto(descripcion)
    palabras_descripcion = set(desc_normalizada.split())
    
    candidatos = []
    
    for _, row in taxonomia.iterrows():
        # Parsear palabras_claves (separadas por coma, desde modo_falla)
        palabras_clave_str = str(row['palabras_claves']).lower() if pd.notna(row['palabras_claves']) else ""
        palabras_clave = set(pc.strip() for pc in palabras_clave_str.split(',') if pc.strip())
        
        if not palabras_clave:
            continue  # Esta fila no tiene palabras clave, saltar
        
        # Medir intersección de palabras clave
        interseccion = palabras_descripcion & palabras_clave
        score_palabras_clave = len(interseccion) / len(palabras_clave) if palabras_clave else 0.0
        
        # Similitud textual con descripción estándar
        desc_estandar_norm = normalizar_texto(row['descripcion_estandar']) if pd.notna(row['descripcion_estandar']) else ""
        score_similaridad = calcular_similitud(desc_normalizada, desc_estandar_norm)
        
        # Bonus si coincide sistema/componente actual
        score_sistema = 1.0 if (sistema_actual and normalizar_texto(sistema_actual) == normalizar_texto(row['sistema'])) else 0.0
        score_componente = 1.0 if (componente_actual and normalizar_texto(componente_actual) == normalizar_texto(row['componente'])) else 0.0
        
        # Score compuesto (pesos arbitrarios, calibrar según resultados)
        score = (
            score_palabras_clave * 0.50 +  # 50% peso en coincidencia de palabras clave
            score_similaridad * 0.30 +      # 30% en similitud textual
            score_sistema * 0.10 +           # 10% en coincidencia de sistema
            score_componente * 0.10          # 10% en coincidencia de componente
        )
        
        if score > 0.0:  # Solo guardar candidatos con algo de score
            candidatos.append({
                'taxonomia_id': row['taxonomia_id'],
                'sistema': row['sistema'],
                'componente': row['componente'],
                'modo': row['modo'],
                'descripcion_estandar': row['descripcion_estandar'],
                'score': score,
                'palabras_clave_coincidentes': list(interseccion)
            })
    
    if not candidatos:
        return {
            'taxonomia_id': None,
            'sistema': None,
            'componente': None,
            'modo': None,
            'confianza': 0.0,
            'motivo': 'Sin coincidencias en taxonomía',
            'candidatos': []
        }
    
    # Ordenar por score descendente
    candidatos.sort(key=lambda x: x['score'], reverse=True)
    mejor = candidatos[0]
    
    # Determinar confianza
    confianza = mejor['score']
    
    # Motivo descriptivo
    palabras_coincidentes = ', '.join(mejor['palabras_clave_coincidentes'][:3])
    motivo = f"Clasificado automático (score: {confianza:.2f}, palabras: {palabras_coincidentes})"
    
    return {
        'taxonomia_id': mejor['taxonomia_id'],
        'sistema': mejor['sistema'],
        'componente': mejor['componente'],
        'modo': mejor['modo'],
        'confianza': confianza,
        'motivo': motivo,
        'candidatos': candidatos
    }

# ============================================================================
# PASO 4: INSERTAR EN ot_falla_evento
# ============================================================================

def insertar_evento_falla(
    ot_id: str,
    activo_id: str,
    fecha_evento: date,
    taxonomia_id: str,
    confianza: float,
    fuente: str,
    notas: Optional[str] = None,
    dry_run: bool = False
) -> bool:
    """
    Inserta un evento de falla en ot_falla_evento.
    
    Tabla: ot_falla_evento
      - id_evento (bigint, auto)
      - ot_id
      - activo_id
      - fecha_evento
      - taxonomia_id
      - confianza (0.0 a 1.0)
      - fuente (automático, manual, migracion, pendiente_revision)
      - texto_evidencia (para notas)
      - created_at (auto)
    """
    
    if dry_run:
        logger.info(f"[DRY-RUN] Insertaría evento: OT={ot_id}, taxo={taxonomia_id}, conf={confianza:.2f}")
        return True
    
    insert_query = text("""
        INSERT INTO ot_falla_evento (
            ot_id,
            activo_id,
            fecha_evento,
            taxonomia_id,
            confianza,
            fuente,
            texto_evidencia
        ) VALUES (
            :ot_id,
            :activo_id,
            :fecha_evento,
            :taxonomia_id,
            :confianza,
            :fuente,
            :notas
        )
        ON CONFLICT DO NOTHING;
    """)
    
    try:
        with engine.begin() as conn:
            conn.execute(insert_query, {
                'ot_id': ot_id,
                'activo_id': activo_id,
                'fecha_evento': fecha_evento,
                'taxonomia_id': taxonomia_id,
                'confianza': confianza,
                'fuente': fuente,
                'notas': notas
            })
        return True
    except Exception as e:
        logger.error(f"❌ Error insertando evento {ot_id}: {str(e)}")
        return False

# ============================================================================
# PASO 5: PROCESO PRINCIPAL
# ============================================================================

def main(args):
    """Orquestación principal"""
    
    logger.info("=" * 80)
    logger.info("BAITECK — Clasificador de fallas desde órdenes de trabajo")
    logger.info("=" * 80)
    
    # Config
    DRY_RUN = args.dry_run
    CONFIANZA_MIN = args.confidence
    OUTPUT_CSV = args.output
    
    if DRY_RUN:
        logger.warning("⚠️  MODO DRY-RUN ACTIVO: no se insertará nada en la BD")
    
    # Paso 1: Cargar taxonomía
    logger.info("\n[1/5] Cargando taxonomía...")
    taxonomia = cargar_taxonomia()
    if len(taxonomia) == 0:
        logger.error("❌ La tabla taxonomia_fallas está vacía. Cancelandoclasiación.")
        sys.exit(1)
    
    # Paso 2: Cargar OT sin clasificar
    logger.info("\n[2/5] Cargando órdenes sin clasificar...")
    ordenes = cargar_ordenes_trabajo_sin_clasificar()
    if len(ordenes) == 0:
        logger.info("✅ Todas las órdenes de trabajo ya tienen eventos clasificados.")
        return
    
    # Paso 3: Clasificar cada OT
    logger.info(f"\n[3/5] Clasificando {len(ordenes)} órdenes...")
    resultados = []
    insertados = 0
    pendientes_revision = []
    
    for idx, row in ordenes.iterrows():
        if (idx + 1) % max(1, len(ordenes) // 10) == 0:
            logger.info(f"   Progreso: {idx+1}/{len(ordenes)} ({100*(idx+1)/len(ordenes):.0f}%)")
        
        clasificacion = clasificar_ot_individual(
            ot_id=row['ot_id'],
            descripcion=row['descripcion_falla'],
            sistema_actual=row['sistema_actual'],
            componente_actual=row['componente_actual'],
            taxonomia=taxonomia
        )
        
        resultado = {
            'ot_id': row['ot_id'],
            'activo_id': row['activo_id'],
            'fecha_apertura': row['fecha_apertura'],
            'descripcion': row['descripcion_falla'],
            'sistema': clasificacion['sistema'],
            'componente': clasificacion['componente'],
            'modo': clasificacion['modo'],
            'confianza': clasificacion['confianza'],
            'motivo': clasificacion['motivo'],
            'insertado': False
        }
        
        # Decidir si insertar
        if clasificacion['taxonomia_id'] is not None and clasificacion['confianza'] >= CONFIANZA_MIN:
            # Insertar en BD
            inserted = insertar_evento_falla(
                ot_id=row['ot_id'],
                activo_id=row['activo_id'],
                fecha_evento=row['fecha_apertura'],
                taxonomia_id=clasificacion['taxonomia_id'],
                confianza=clasificacion['confianza'],
                fuente='automático',
                notas=clasificacion['motivo'],
                dry_run=DRY_RUN
            )
            if inserted:
                insertados += 1
                resultado['insertado'] = True
            
            # Log
            if clasificacion['confianza'] >= 0.8:
                logger.debug(f"✅ {row['ot_id']}: {clasificacion['sistema']} → {clasificacion['modo']} (conf: {clasificacion['confianza']:.2f})")
        
        else:
            # Pendiente revisión manual
            pendientes_revision.append({
                'ot_id': row['ot_id'],
                'activo_id': row['activo_id'],
                'fecha_apertura': row['fecha_apertura'],
                'descripcion': row['descripcion'],
                'confianza': clasificacion['confianza'],
                'candidatos': clasificacion['candidatos']
            })
            logger.debug(f"⚠️  {row['ot_id']}: Sin clasificación clara (conf: {clasificacion['confianza']:.2f})")
        
        resultados.append(resultado)
    
    # Paso 4: Reporte
    logger.info(f"\n[4/5] Reporte de clasificación...")
    df_resultados = pd.DataFrame(resultados)
    
    logger.info(f"""
    ┌─────────────────────────────────────────┐
    │ RESUMEN DE CLASIFICACIÓN                │
    ├─────────────────────────────────────────┤
    │ Total órdenes procesadas: {len(ordenes):3d}       │
    │ Insertadas automáticamente: {insertados:3d}      │
    │ Pendientes de revisión:     {len(pendientes_revision):3d}      │
    │ Confianza mínima requerida: {CONFIANZA_MIN:.2f}    │
    └─────────────────────────────────────────┘
    """)
    
    # Estadísticas por sistema
    if len(df_resultados[df_resultados['sistema'].notna()]) > 0:
        print("\n   DISTRIBUCIÓN POR SISTEMA:")
        dist_sistema = df_resultados[df_resultados['insertado']].groupby('sistema').size()
        for sistema, count in dist_sistema.sort_values(ascending=False).items():
            print(f"      • {sistema}: {count} fallas")
    
    # Paso 5: Guardar CSV de pendientes
    logger.info(f"\n[5/5] Exportando resultados...")
    if OUTPUT_CSV and len(pendientes_revision) > 0:
        df_pendientes = pd.DataFrame(pendientes_revision)
        df_pendientes.to_csv(OUTPUT_CSV, index=False, encoding='utf-8')
        logger.info(f"✅ Pendientes de revisión exportados a: {OUTPUT_CSV}")
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ CLASIFICACIÓN COMPLETADA")
    logger.info("=" * 80)

# ============================================================================
# ENTRADA
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clasificador automático de fallas desde órdenes de trabajo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EJEMPLOS:
  # Ejecutar con valores por defecto
  uv run python clasificar_fallas.py
  
  # Dry-run (sin insertar en BD)
  uv run python clasificar_fallas.py --dry-run
  
  # Solo insertar si confianza > 0.7
  uv run python clasificar_fallas.py --confidence 0.7
  
  # Guardar pendientes en archivo
  uv run python clasificar_fallas.py --output pendientes_revision.csv
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Ejecutar sin insertar en la BD (simular)'
    )
    
    parser.add_argument(
        '--confidence',
        type=float,
        default=0.50,
        help='Confianza mínima para insertar (0.0-1.0, default=0.50)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Archivo CSV para guardar pendientes de revisión (default=no guardar)'
    )
    
    args = parser.parse_args()
    
    try:
        main(args)
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupción del usuario")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ ERROR FATAL: {str(e)}", exc_info=True)
        sys.exit(1)
