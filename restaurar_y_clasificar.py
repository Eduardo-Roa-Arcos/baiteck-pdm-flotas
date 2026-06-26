#!/usr/bin/env python3
"""
BAITECK — Restaurador de órdenes de trabajo desde CSV antiguo

Propósito:
  1. Lee CSV antiguo (ordenes_trabajo.csv)
  2. Extrae descripcion_falla
  3. Puebla ordenes_trabajo.descripcion_falla
  4. Clasifica contra taxonomia_fallas
  5. Genera ot_falla_evento automáticamente
  
  TODO EN UN SOLO SCRIPT. Sin necesidad de SQL manual.

Uso:
  uv run python restaurar_y_clasificar.py ordenes_trabajo.csv
"""

import sys
import os
import pandas as pd
import logging
from datetime import date
from difflib import SequenceMatcher
from sqlalchemy import text, create_engine
from dotenv import load_dotenv

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)8s | %(message)s'
)
logger = logging.getLogger(__name__)

def get_engine():
    """Conexión a Supabase"""
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("ERROR: DATABASE_URL no está en .env")
        sys.exit(1)
    return create_engine(database_url, pool_pre_ping=True)

engine = get_engine()

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparación"""
    if not isinstance(texto, str):
        return ""
    texto = texto.lower().strip()
    for char in ['.,;:', '!?', '"\'']:
        texto = texto.replace(char, '')
    texto = ' '.join(texto.split())
    return texto

def calcular_similitud(texto1: str, texto2: str) -> float:
    """Similitud entre dos textos"""
    return SequenceMatcher(None, texto1, texto2).ratio()

def cargar_csv_antiguo(archivo: str) -> pd.DataFrame:
    """Carga el CSV antiguo"""
    logger.info(f"Cargando CSV: {archivo}")
    df = pd.read_csv(archivo, encoding='utf-8')
    logger.info(f"✅ CSV cargado: {len(df)} registros")
    return df

def cargar_taxonomia() -> pd.DataFrame:
    """Carga taxonomía con palabras clave"""
    query = text("""
        SELECT
            tf.taxonomia_id,
            tf.sistema,
            tf.componente,
            tf.id_modo_falla,
            mf.modo,
            mf.palabras_claves,
            tf.descripcion_estandar
        FROM taxonomia_fallas tf
        LEFT JOIN modo_falla mf ON tf.id_modo_falla = mf.id_modo_falla
        WHERE tf.activo = TRUE
        ORDER BY tf.sistema, tf.componente
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    logger.info(f"✅ Taxonomía cargada: {len(df)} registros")
    return df

def clasificar_descripcion(descripcion: str, taxonomia: pd.DataFrame) -> dict:
    """Clasifica UNA descripción contra taxonomía"""
    
    if not descripcion or pd.isna(descripcion):
        return {'taxonomia_id': None, 'confianza': 0.0}
    
    desc_norm = normalizar_texto(descripcion)
    palabras_desc = set(desc_norm.split())
    
    mejores = []
    
    for _, row in taxonomia.iterrows():
        # Palabras clave de modo_falla
        palabras_clave_str = str(row['palabras_claves']).lower() if pd.notna(row['palabras_claves']) else ""
        palabras_clave = set(pc.strip() for pc in palabras_clave_str.split(',') if pc.strip())
        
        if not palabras_clave:
            continue
        
        # Score
        interseccion = palabras_desc & palabras_clave
        score_kw = len(interseccion) / len(palabras_clave) if palabras_clave else 0.0
        
        desc_est = normalizar_texto(row['descripcion_estandar']) if pd.notna(row['descripcion_estandar']) else ""
        score_sim = calcular_similitud(desc_norm, desc_est)
        
        score = score_kw * 0.6 + score_sim * 0.4
        
        if score > 0.0:
            mejores.append({
                'taxonomia_id': row['taxonomia_id'],
                'score': score,
                'sistema': row['sistema'],
                'componente': row['componente'],
                'modo': row['modo']
            })
    
    if not mejores:
        return {'taxonomia_id': None, 'confianza': 0.0}
    
    mejor = sorted(mejores, key=lambda x: x['score'], reverse=True)[0]
    return {
        'taxonomia_id': mejor['taxonomia_id'],
        'confianza': mejor['score'],
        'sistema': mejor['sistema'],
        'componente': mejor['componente'],
        'modo': mejor['modo']
    }

# ============================================================================
# PASO 0: INSERTAR OT EN ordenes_trabajo (SI NO EXISTEN)
# ============================================================================

def insertar_ordenes_trabajo(df_csv: pd.DataFrame):
    """Inserta las OT en ordenes_trabajo si no existen"""
    
    logger.info("\n[0/5] Insertando órdenes de trabajo...")
    
    insertadas = 0
    ya_existen = 0
    errores = 0
    
    for idx, row in df_csv.iterrows():
        ot_id = row.get('ot_id', '').strip()
        activo_id = row.get('activo_id', '').strip()
        fecha_apertura = row.get('fecha_apertura')
        descripcion_falla = row.get('descripcion_falla', '').strip()
        
        if not ot_id or not activo_id:
            continue
        
        # Insertar SOLO con columnas que sabemos que existen
        # (ot_id, activo_id, fecha_apertura, descripcion_falla)
        insert_query = text("""
            INSERT INTO ordenes_trabajo (
                ot_id, activo_id, fecha_apertura, descripcion_falla
            ) VALUES (
                :ot_id, :activo_id, :fecha_apertura, :descripcion_falla
            )
            ON CONFLICT (ot_id) DO UPDATE 
            SET descripcion_falla = EXCLUDED.descripcion_falla
        """)
        
        try:
            with engine.begin() as conn:
                result = conn.execute(insert_query, {
                    'ot_id': ot_id,
                    'activo_id': activo_id,
                    'fecha_apertura': fecha_apertura,
                    'descripcion_falla': descripcion_falla
                })
                if result.rowcount > 0:
                    insertadas += 1
                else:
                    ya_existen += 1
        except Exception as e:
            errores += 1
            logger.debug(f"⚠️  Error en {ot_id}: {str(e)}")
    
    logger.info(f"✅ {insertadas} OT insertadas, {ya_existen} ya existían, {errores} errores")

# ============================================================================
# PASO 1: ACTUALIZAR DESCRIPCIONES EN ordenes_trabajo
# ============================================================================

def actualizar_descripciones(df_csv: pd.DataFrame):
    """Actualiza descripciones en OT que ya existen"""
    
    logger.info("\n[1/5] Actualizando descripciones...")
    
    actualizadas = 0
    for idx, row in df_csv.iterrows():
        ot_id = row.get('ot_id', '').strip()
        descripcion = row.get('descripcion_falla', '').strip()
        
        if not ot_id or not descripcion:
            continue
        
        query = text("""
            UPDATE ordenes_trabajo 
            SET descripcion_falla = :desc 
            WHERE ot_id = :ot_id
        """)
        
        try:
            with engine.begin() as conn:
                result = conn.execute(query, {'desc': descripcion, 'ot_id': ot_id})
                if result.rowcount > 0:
                    actualizadas += 1
        except Exception as e:
            logger.warning(f"⚠️  Error actualizando {ot_id}: {str(e)}")
    
    logger.info(f"✅ {actualizadas} descripciones actualizadas")

# ============================================================================
# PASO 2: CLASIFICAR Y GENERAR ot_falla_evento
# ============================================================================

def generar_eventos_falla(df_csv: pd.DataFrame, taxonomia: pd.DataFrame):
    """Clasifica cada OT y genera evento en ot_falla_evento"""
    
    logger.info("\n[1/4] Clasificando y generando eventos de falla...")
    
    insertadas = 0
    pendientes = 0
    
    for idx, row in df_csv.iterrows():
        ot_id = row.get('ot_id', '').strip()
        activo_id = row.get('activo_id', '').strip()
        fecha_apertura = row.get('fecha_apertura')
        descripcion = row.get('descripcion_falla', '').strip()
        
        if not ot_id or not activo_id or not descripcion:
            continue
        
        # Clasificar
        clasificacion = clasificar_descripcion(descripcion, taxonomia)
        
        if clasificacion['taxonomia_id'] is None:
            pendientes += 1
            continue
        
        # Insertar en ot_falla_evento
        insert_query = text("""
            INSERT INTO ot_falla_evento (
                ot_id, activo_id, fecha_evento, taxonomia_id,
                confianza, fuente, texto_evidencia
            ) VALUES (
                :ot_id, :activo_id, :fecha_evento, :taxonomia_id,
                :confianza, 'migracion', :notas
            )
            ON CONFLICT DO NOTHING
        """)
        
        try:
            with engine.begin() as conn:
                conn.execute(insert_query, {
                    'ot_id': ot_id,
                    'activo_id': activo_id,
                    'fecha_evento': pd.to_datetime(fecha_apertura).date() if pd.notna(fecha_apertura) else date.today(),
                    'taxonomia_id': clasificacion['taxonomia_id'],
                    'confianza': clasificacion['confianza'],
                    'notas': f"Migración automática - {clasificacion['modo']} ({clasificacion['confianza']:.2f})"
                })
            insertadas += 1
        except Exception as e:
            logger.error(f"❌ Error insertando {ot_id}: {str(e)}")
    
    logger.info(f"✅ {insertadas} eventos insertados")
    logger.info(f"⚠️  {pendientes} eventos pendientes de revisión")
    
    return insertadas, pendientes

# ============================================================================
# PASO 3: VALIDAR RESULTADO
# ============================================================================

def validar_resultado(df_csv: pd.DataFrame):
    """Valida que todo esté sincronizado"""
    
    logger.info("\n[2/4] Validando resultado...")
    
    # Total OT
    query_total = text("SELECT COUNT(*) as n FROM ordenes_trabajo")
    with engine.connect() as conn:
        total_ot = conn.execute(query_total).scalar()
    
    # OT con evento
    query_eventos = text("""
        SELECT COUNT(DISTINCT ot_id) as n 
        FROM ot_falla_evento 
        WHERE ot_id IS NOT NULL
    """)
    with engine.connect() as conn:
        ot_con_evento = conn.execute(query_eventos).scalar()
    
    # OT con descripción
    query_desc = text("""
        SELECT COUNT(*) as n FROM ordenes_trabajo 
        WHERE descripcion_falla IS NOT NULL
    """)
    with engine.connect() as conn:
        ot_con_desc = conn.execute(query_desc).scalar()
    
    logger.info(f"""
    ┌─────────────────────────────────────┐
    │ RESULTADO FINAL                     │
    ├─────────────────────────────────────┤
    │ Total OT: {total_ot:3d}                       │
    │ Con descripción: {ot_con_desc:3d}             │
    │ Con evento falla: {ot_con_evento:3d}          │
    │ Cobertura: {100*ot_con_evento/max(1,total_ot):.1f}%               │
    └─────────────────────────────────────┘
    """)

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Orquestación principal"""
    
    logger.info("=" * 80)
    logger.info("BAITECK — Restaurador y Clasificador de Órdenes de Trabajo")
    logger.info("=" * 80)
    
    if len(sys.argv) < 2:
        print("USO: uv run python restaurar_y_clasificar.py ordenes_trabajo.csv")
        sys.exit(1)
    
    archivo_csv = sys.argv[1]
    
    if not os.path.exists(archivo_csv):
        logger.error(f"❌ Archivo no encontrado: {archivo_csv}")
        sys.exit(1)
    
    # Cargar datos
    df_csv = cargar_csv_antiguo(archivo_csv)
    taxonomia = cargar_taxonomia()
    
    # Paso 0: Insertar OT (incluye descripciones en el INSERT)
    insertar_ordenes_trabajo(df_csv)
    
    # Paso 1: Clasificar y generar eventos (antes era paso 2)
    insertadas, pendientes = generar_eventos_falla(df_csv, taxonomia)
    
    # Paso 2: Validar (antes era paso 3)
    validar_resultado(df_csv)
    
    # Paso 3: Reporte final (antes era paso 4)
    logger.info("\n[3/4] Reporte final")
    logger.info(f"""
    ✅ PROCESO COMPLETADO
    
    Acciones realizadas:
    ├─ Descripciones pobladas: {len(df_csv)}
    ├─ Eventos insertados: {insertadas}
    ├─ Eventos pendientes: {pendientes}
    └─ Taxonomía usada: {len(taxonomia)} registros
    
    Próximos pasos:
    1. Si hay pendientes: uv run python revisar_clasificaciones.py
    2. Validar: uv run python validar_clasificacion.py
    3. Continuar con el pipeline de entrenamiento
    """)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupción del usuario")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ ERROR FATAL: {str(e)}", exc_info=True)
        sys.exit(1)
