#!/usr/bin/env python3
"""
BAITECK: Cargador Ordenado de Datos
Carga: activos → órdenes de trabajo → ot_falla_evento → repuestos consumidos

Propósito:
  - Cargar datos en orden de dependencias (activos primero, luego OT, luego eventos, luego repuestos)
  - Validar que archivos existan antes de cargar
  - Manejar errores de integridad sin detener el flujo
  - Log detallado de qué se cargó

Uso:
  from carga_datos_ordenado import carga_datos_ordenado
  carga_datos_ordenado(
      ruta_csv_activos='data/raw/activos.csv',
      ruta_csv_ot='data/raw/ordenes_trabajo.csv',
      ruta_csv_ot_falla_evento='data/raw/ot_falla_evento.csv',
      ruta_csv_repuestos='data/raw/repuestos_consumidos.csv'
  )
"""

import os
import sys
import pandas as pd
import logging
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
    """Obtiene conexión a Supabase"""
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("ERROR: DATABASE_URL no está en .env")
        raise ValueError("DATABASE_URL no configurada")
    return create_engine(database_url, pool_pre_ping=True)

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def archivo_existe(ruta):
    """Verifica que un archivo exista"""
    if ruta is None:
        return False
    return os.path.exists(ruta)

def cargar_csv(ruta):
    """Carga un CSV de forma segura"""
    if not archivo_existe(ruta):
        logger.warning(f"⚠️  Archivo no encontrado: {ruta}")
        return None
    
    try:
        df = pd.read_csv(ruta, encoding='utf-8')
        logger.info(f"✅ CSV cargado: {ruta} ({len(df)} registros)")
        return df
    except Exception as e:
        logger.error(f"❌ Error cargando CSV {ruta}: {str(e)}")
        return None

# ============================================================================
# FASE 0: LIMPIAR TABLAS BASE EN ORDEN DE DEPENDENCIAS (FK)
# ============================================================================

def limpiar_tablas_base(conn):
    """Vacía las tablas base en orden inverso de dependencias FK.

    ⚠️ REGLA DE PROTECCIÓN DEL PROYECTO: las tablas base (y en particular
    ot_falla_evento, que contiene la clasificación de fallas) NUNCA se
    borran durante la ejecución del workflow. Esta función SOLO se invoca
    en modo manual explícito (recarga_completa=True) y SOLO después de
    validar que los 4 CSVs existen y tienen datos.

    Recibe una CONEXIÓN abierta (no el engine): el borrado y la carga
    posterior ocurren en la MISMA transacción. Si cualquier carga falla,
    el rollback restaura también lo borrado.

    Orden de borrado (hijos primero):
      repuestos_consumidos → ot_falla_evento → ordenes_trabajo → activos
    """
    orden_borrado = [
        'repuestos_consumidos',
        'ot_falla_evento',
        'ordenes_trabajo',
        'activos',
    ]
    logger.info("\n[0/5] Limpiando tablas base (orden FK, dentro de transacción)...")
    for tabla in orden_borrado:
        conn.execute(text(f"DELETE FROM {tabla};"))
        logger.info(f"   ✅ {tabla} vaciada (pendiente de commit)")


# ============================================================================
# FASE 1: CARGAR ACTIVOS (tabla maestra)
# ============================================================================

def cargar_activos(engine, df_activos):
    """Carga tabla maestra activos.

    IMPORTANTE: se usa DELETE + append (NO if_exists='replace').
    'replace' hace DROP TABLE y la recrea con tipos inferidos por pandas,
    destruyendo PK, FKs entrantes (disponibilidad_diaria, etc.) y defaults.
    """
    
    if df_activos is None or len(df_activos) == 0:
        logger.warning("⚠️  No hay activos para cargar (tabla será protegida)")
        return 0
    
    logger.info(f"\n[1/5] Cargando activos...")
    
    try:
        df_activos.to_sql(
            'activos',
            engine,
            if_exists='append',
            index=False,
            method='multi',
            chunksize=1000
        )
        logger.info(f"✅ {len(df_activos)} activos cargados")
        return len(df_activos)
    except Exception as e:
        logger.error(f"❌ Error cargando activos: {str(e)}")
        return 0

# ============================================================================
# FASE 2: CARGAR ÓRDENES DE TRABAJO
# ============================================================================

def cargar_ordenes_trabajo(engine, df_ot):
    """Carga órdenes de trabajo (con soporte para nuevas columnas)"""
    
    if df_ot is None or len(df_ot) == 0:
        logger.warning("⚠️  No hay órdenes de trabajo para cargar")
        return 0
    
    logger.info(f"\n[2/5] Cargando órdenes de trabajo...")
    
    # Mapeo de nombres de columnas (CSV antiguo → tabla destino)
    columnas_mapeo = {
        'ot_id': 'ot_id',
        'activo_id': 'activo_id',
        'fecha_apertura': 'fecha_apertura',
        'fecha_cierre': 'fecha_cierre',
        'tipo_ot': 'tipo_ot',
        'descripcion_falla': 'descripcion_falla',
        'odometro_km': 'odometro_km',
        'horometro_h': 'horometro_h',
        'taller_id': 'taller_id',
        'costo_total_clp': 'costo_total_clp',
        'responsable': 'responsable',
        'observaciones': 'observaciones',
        'created_at': 'created_at'
    }
    
    # Filtrar solo columnas que existen en el CSV
    columnas_validas = [col for col in columnas_mapeo.keys() if col in df_ot.columns]
    df_ot_subset = df_ot[columnas_validas].copy()
    
    logger.info(f"   Columnas a cargar: {columnas_validas}")
    
    try:
        df_ot_subset.to_sql(
            'ordenes_trabajo',
            engine,
            if_exists='append',  # APPEND: no reemplaza, agrega/actualiza
            index=False,
            method='multi',
            chunksize=1000
        )
        logger.info(f"✅ {len(df_ot_subset)} órdenes de trabajo cargadas")
        return len(df_ot_subset)
    except Exception as e:
        logger.error(f"❌ Error cargando órdenes de trabajo: {str(e)}")
        logger.debug(f"   DataFrame shape: {df_ot_subset.shape}")
        logger.debug(f"   Columnas: {list(df_ot_subset.columns)}")
        return 0

# ============================================================================
# FASE 3: CARGAR ot_falla_evento (NUEVA)
# ============================================================================

def cargar_ot_falla_evento(engine, df_ot_eventos):
    """Carga eventos de falla de órdenes de trabajo"""
    
    if df_ot_eventos is None or len(df_ot_eventos) == 0:
        logger.warning("⚠️  No hay eventos de falla para cargar")
        return 0
    
    logger.info(f"\n[3/5] Cargando eventos de falla (ot_falla_evento)...")
    
    # Mapeo de columnas
    columnas_mapeo = {
        'id_evento': 'id_evento',
        'ot_id': 'ot_id',
        'activo_id': 'activo_id',
        'fecha_evento': 'fecha_evento',
        'taxonomia_id': 'taxonomia_id',
        'causa_probable': 'causa_probable',
        'accion_realizada': 'accion_realizada',
        'texto_evidencia': 'texto_evidencia',
        'fuente': 'fuente',
        'confianza': 'confianza',
        'severidad': 'severidad',
        'es_causa_raiz': 'es_causa_raiz',
        'tipo_mantenimiento': 'tipo_mantenimiento',
        'km_evento': 'km_evento',
        'created_at': 'created_at'
    }
    
    # Filtrar solo columnas que existen
    columnas_validas = [col for col in columnas_mapeo.keys() if col in df_ot_eventos.columns]
    df_eventos_subset = df_ot_eventos[columnas_validas].copy()
    
    logger.info(f"   Columnas a cargar: {columnas_validas}")
    
    try:
        df_eventos_subset.to_sql(
            'ot_falla_evento',
            engine,
            if_exists='append',  # APPEND: agrega sin reemplazar
            index=False,
            method='multi',
            chunksize=1000
        )
        logger.info(f"✅ {len(df_eventos_subset)} eventos de falla cargados")
        return len(df_eventos_subset)
    except Exception as e:
        logger.error(f"❌ Error cargando eventos de falla: {str(e)}")
        logger.debug(f"   DataFrame shape: {df_eventos_subset.shape}")
        logger.debug(f"   Columnas: {list(df_eventos_subset.columns)}")
        return 0

# ============================================================================
# FASE 4: CARGAR REPUESTOS CONSUMIDOS
# ============================================================================

def cargar_repuestos_consumidos(engine, df_repuestos):
    """Carga repuestos consumidos"""
    
    if df_repuestos is None or len(df_repuestos) == 0:
        logger.warning("⚠️  No hay repuestos consumidos para cargar")
        return 0
    
    logger.info(f"\n[4/5] Cargando repuestos consumidos...")
    
    columnas_mapeo = {
        'ot_id': 'ot_id',
        'repuesto_id': 'repuesto_id',
        'sku': 'sku',
        'descripcion_repuesto': 'descripcion_repuesto',
        'cantidad': 'cantidad',
        'costo_unitario': 'costo_unitario',
        'costo_unitario_clp': 'costo_unitario_clp',
        'activo_id': 'activo_id',
        'fecha_consumo': 'fecha_consumo',
        'created_at': 'created_at'
    }
    
    columnas_validas = [col for col in columnas_mapeo.keys() if col in df_repuestos.columns]
    df_repuestos_subset = df_repuestos[columnas_validas].copy()
    
    logger.info(f"   Columnas a cargar: {columnas_validas}")
    
    try:
        df_repuestos_subset.to_sql(
            'repuestos_consumidos',
            engine,
            if_exists='append',
            index=False,
            method='multi',
            chunksize=1000
        )
        logger.info(f"✅ {len(df_repuestos_subset)} repuestos consumidos cargados")
        return len(df_repuestos_subset)
    except Exception as e:
        logger.error(f"❌ Error cargando repuestos: {str(e)}")
        return 0

# ============================================================================
# VALIDACIÓN POST-CARGA
# ============================================================================

def validar_carga(engine):
    """Valida que la carga fue exitosa"""
    
    logger.info(f"\n[5/5] Validando carga...")
    
    try:
        with engine.connect() as conn:
            # Contar registros en cada tabla
            query_ot = text("SELECT COUNT(*) as total FROM ordenes_trabajo")
            query_eventos = text("SELECT COUNT(*) as total FROM ot_falla_evento")
            query_repuestos = text("SELECT COUNT(*) as total FROM repuestos_consumidos")
            
            total_ot = conn.execute(query_ot).scalar() or 0
            total_eventos = conn.execute(query_eventos).scalar() or 0
            total_repuestos = conn.execute(query_repuestos).scalar() or 0
            
            logger.info(f"""
    ✅ VALIDACIÓN COMPLETA
    
    Registros en base de datos:
    ├─ ordenes_trabajo: {total_ot:,}
    ├─ ot_falla_evento: {total_eventos:,}
    └─ repuestos_consumidos: {total_repuestos:,}
    """)
            
            return True
    except Exception as e:
        logger.error(f"⚠️  Error en validación: {str(e)}")
        return False

# ============================================================================
# ORQUESTACIÓN PRINCIPAL
# ============================================================================

def carga_datos_ordenado(
    ruta_csv_activos=None,
    ruta_csv_ot=None,
    ruta_csv_ot_falla_evento=None,
    ruta_csv_repuestos=None,
    recarga_completa=False
):
    """
    Carga todos los datos en orden de dependencias

    Parámetros:
    -----------
    ruta_csv_activos : str
        Ruta al CSV de activos (tabla maestra)
    ruta_csv_ot : str
        Ruta al CSV de órdenes de trabajo
    ruta_csv_ot_falla_evento : str
        Ruta al CSV de eventos de falla
    ruta_csv_repuestos : str
        Ruta al CSV de repuestos consumidos
    recarga_completa : bool
        False (DEFAULT — modo seguro): solo agrega (append) sobre lo
        existente. NUNCA borra. Es el único modo que el workflow usa.
        Si las tablas ya tienen datos, se emite una advertencia de
        posibles duplicados y la decisión queda en el operador.

        True (SOLO uso manual explícito): vacía las 4 tablas base y las
        recarga desde CSV. Doble salvaguarda:
          1. Se aborta ANTES de borrar si falta CUALQUIERA de los 4 CSVs
             o alguno viene vacío.
          2. Borrado + carga ocurren en UNA transacción: si una carga
             falla, el rollback restaura también lo borrado.
        ⚠️ ot_falla_evento contiene la clasificación de fallas: nunca
        invocar este modo desde el workflow ni desde cron.
    """

    logger.info("="*70)
    logger.info("BAITECK: CARGADOR ORDENADO DE DATOS")
    logger.info(f"Modo: {'RECARGA COMPLETA (destructivo, manual)' if recarga_completa else 'APPEND (seguro)'}")
    logger.info("="*70)

    # Obtener conexión
    try:
        engine = get_engine()
        logger.info("✅ Conexión a Supabase establecida")
    except Exception as e:
        logger.error(f"❌ Error de conexión: {str(e)}")
        sys.exit(1)

    # Cargar CSVs
    logger.info("\n📂 Leyendo archivos CSV...")
    df_activos = cargar_csv(ruta_csv_activos) if ruta_csv_activos else None
    df_ot = cargar_csv(ruta_csv_ot) if ruta_csv_ot else None
    df_ot_eventos = cargar_csv(ruta_csv_ot_falla_evento) if ruta_csv_ot_falla_evento else None
    df_repuestos = cargar_csv(ruta_csv_repuestos) if ruta_csv_repuestos else None

    if recarga_completa:
        # ── SALVAGUARDA 1: nada se borra si falta un solo CSV ──────────
        faltantes = [nombre for nombre, df in [
            ('activos', df_activos),
            ('ordenes_trabajo', df_ot),
            ('ot_falla_evento', df_ot_eventos),
            ('repuestos_consumidos', df_repuestos),
        ] if df is None or len(df) == 0]

        if faltantes:
            logger.error("❌ RECARGA ABORTADA — NO SE BORRÓ NADA.")
            logger.error(f"   CSVs faltantes o vacíos para: {faltantes}")
            logger.error("   La recarga completa exige los 4 CSVs con datos.")
            sys.exit(1)

        # ── SALVAGUARDA 2: borrado + carga en UNA transacción ──────────
        logger.info("\n📥 RECARGA COMPLETA (transacción única, todo-o-nada)...")
        try:
            with engine.begin() as conn:
                limpiar_tablas_base(conn)
                total_activos = cargar_activos(conn, df_activos)
                total_ot = cargar_ordenes_trabajo(conn, df_ot)
                total_eventos = cargar_ot_falla_evento(conn, df_ot_eventos)
                total_repuestos = cargar_repuestos_consumidos(conn, df_repuestos)
                if 0 in (total_activos, total_ot, total_eventos, total_repuestos):
                    raise RuntimeError(
                        "Una de las cargas devolvió 0 filas; rollback total "
                        "(las tablas quedan como estaban antes de la recarga)."
                    )
            logger.info("✅ Transacción commiteada: recarga completa exitosa")
        except Exception as e:
            logger.error(f"❌ RECARGA FALLIDA — rollback aplicado, BD intacta: {str(e)[:100]}")
            sys.exit(1)
    else:
        # ── MODO SEGURO (default): append puro, sin borrados ───────────
        _advertir_si_hay_datos(engine)
        logger.info("\n📥 CARGANDO DATOS EN ORDEN (append)...")
        total_activos = cargar_activos(engine, df_activos)
        total_ot = cargar_ordenes_trabajo(engine, df_ot)
        total_eventos = cargar_ot_falla_evento(engine, df_ot_eventos)
        total_repuestos = cargar_repuestos_consumidos(engine, df_repuestos)

    # Validar
    validar_carga(engine)

    # Resumen
    logger.info("\n" + "="*70)
    logger.info("✅ CARGA COMPLETADA")
    logger.info("="*70)
    logger.info(f"""
Totales cargados:
├─ Activos: {total_activos:,}
├─ Órdenes de trabajo: {total_ot:,}
├─ Eventos de falla: {total_eventos:,}
└─ Repuestos consumidos: {total_repuestos:,}

Próximos pasos:
1. Clasificar fallas automáticamente (si es necesario)
2. Calcular disponibilidad histórica
3. Entrenar modelo predictivo
4. Generar scoring y dashboard
""")


def _advertir_si_hay_datos(engine):
    """En modo append, advierte si las tablas base ya contienen datos
    (una nueva carga del mismo CSV generaría duplicados)."""
    try:
        with engine.connect() as conn:
            n = conn.execute(text("SELECT COUNT(*) FROM ordenes_trabajo")).scalar() or 0
        if n > 0:
            logger.warning(f"⚠️  ordenes_trabajo ya tiene {n:,} filas. "
                           f"Cargar el mismo CSV en modo append DUPLICARÁ registros. "
                           f"Si la intención es repoblar desde cero, usar "
                           f"recarga_completa=True manualmente (nunca desde el workflow).")
    except Exception:
        pass


if __name__ == "__main__":
    # Ejemplo de uso directo — modo seguro (append).
    # Para recarga total manual: agregar recarga_completa=True (exige 4 CSVs).
    carga_datos_ordenado(
        ruta_csv_activos='data/raw/activos.csv',
        ruta_csv_ot='data/raw/ordenes_trabajo.csv',
        ruta_csv_ot_falla_evento='data/raw/ot_falla_evento.csv',
        ruta_csv_repuestos='data/raw/repuestos_consumidos.csv'
    )
