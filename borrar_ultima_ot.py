#!/usr/bin/env python3
"""
BAITECK PDM - BORRAR ÚLTIMA ORDEN DE TRABAJO
================================================================================
Elimina la última OT de una unidad junto con todas sus derivadas:
  • repuestos_consumidos (asociados a los eventos)
  • ot_falla_evento (eventos de la OT)
  • ordenes_trabajo (la OT misma)

Mantiene integridad referencial: borra en orden inverso a las FKs.
Transacción atómica: TODO o NADA.

Parámetro: patente (ej: WRYY32)

Uso:
  uv run python borrar_ultima_ot.py
  
O con parámetro:
  uv run python borrar_ultima_ot.py WRYY32
"""

import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no está definido en .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

# ============================================================================
# UTILIDADES
# ============================================================================

class Color:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_titulo(texto):
    print(f"\n{Color.HEADER}{Color.BOLD}{'='*80}{Color.ENDC}")
    print(f"{Color.HEADER}{Color.BOLD}{texto}{Color.ENDC}")
    print(f"{Color.HEADER}{Color.BOLD}{'='*80}{Color.ENDC}\n")

def log_paso(numero, mensaje):
    print(f"\n{numero} {mensaje}")

def log_exito(mensaje):
    print(f"   {Color.OKGREEN}✅ {mensaje}{Color.ENDC}")

def log_error(mensaje):
    print(f"   {Color.FAIL}❌ ERROR: {mensaje}{Color.ENDC}")
    sys.exit(1)

def log_alerta(mensaje):
    print(f"   {Color.WARNING}⚠️  {mensaje}{Color.ENDC}")

# ============================================================================
# FUNCIONES DE BÚSQUEDA
# ============================================================================

def obtener_activo_id(patente):
    """Obtiene activo_id de una patente"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT activo_id, patente, marca, modelo
                    FROM activos
                    WHERE UPPER(patente) = UPPER(:patente)
                """),
                {"patente": patente}
            ).fetchone()
        return result
    except Exception as e:
        log_error(f"Error buscando activo: {str(e)}")

def obtener_ultima_ot(activo_id):
    """Obtiene la última OT del activo"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT 
                        ot_id,
                        fecha_apertura,
                        tipo_ot,
                        descripcion_falla
                    FROM ordenes_trabajo
                    WHERE activo_id = :activo_id
                    ORDER BY fecha_apertura DESC
                    LIMIT 1
                """),
                {"activo_id": activo_id}
            ).fetchone()
        return result
    except Exception as e:
        log_error(f"Error obteniendo última OT: {str(e)}")

def obtener_eventos_de_ot(ot_id):
    """Obtiene IDs de eventos asociados a una OT"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id_evento
                    FROM ot_falla_evento
                    WHERE ot_id = :ot_id
                """),
                {"ot_id": ot_id}
            ).fetchall()
        return [row[0] for row in result]
    except Exception as e:
        log_error(f"Error obteniendo eventos: {str(e)}")

def contar_registros_asociados(ot_id, ids_evento):
    """Cuenta repuestos asociados a los eventos"""
    try:
        with engine.connect() as conn:
            if ids_evento:
                placeholders = ','.join([str(id) for id in ids_evento])
                query = f"""
                    SELECT COUNT(*)
                    FROM repuestos_consumidos
                    WHERE id_evento IN ({placeholders})
                """
            else:
                query = "SELECT 0"
            
            result = conn.execute(text(query)).fetchone()
        return result[0] if result else 0
    except Exception as e:
        return 0

# ============================================================================
# PROGRAMA PRINCIPAL
# ============================================================================

def main():
    print_titulo("BAITECK PDM - BORRAR ÚLTIMA ORDEN DE TRABAJO")
    
    # PASO 1: Obtener patente
    log_paso("1️⃣", "SOLICITAR PATENTE")
    
    if len(sys.argv) > 1:
        patente = sys.argv[1].strip().upper()
        print(f"   Patente (parámetro): {patente}")
    else:
        patente = input("   Ingrese patente del activo: ").strip().upper()
    
    if not patente:
        log_error("Patente no puede estar vacía")
    
    # PASO 2: Buscar activo
    log_paso("2️⃣", f"BUSCAR ACTIVO '{patente}'")
    activo_info = obtener_activo_id(patente)
    
    if not activo_info:
        log_error(f"Activo '{patente}' no encontrado")
    
    activo_id, patente_bd, marca, modelo = activo_info
    log_exito(f"{marca} {modelo} ({activo_id})")
    
    # PASO 3: Obtener última OT
    log_paso("3️⃣", "OBTENER ÚLTIMA ORDEN DE TRABAJO")
    ultima_ot = obtener_ultima_ot(activo_id)
    
    if not ultima_ot:
        log_error(f"No hay órdenes de trabajo para {patente}")
    
    ot_id, fecha_ap, tipo_ot, descripcion = ultima_ot
    log_exito(f"OT: {ot_id}")
    print(f"      Tipo: {tipo_ot}")
    print(f"      Fecha: {fecha_ap.strftime('%Y-%m-%d %H:%M')}")
    print(f"      Descripción: {descripcion}")
    
    # PASO 4: Obtener eventos asociados
    log_paso("4️⃣", "OBTENER EVENTOS ASOCIADOS")
    ids_evento = obtener_eventos_de_ot(ot_id)
    
    if ids_evento:
        log_exito(f"Encontrados {len(ids_evento)} evento(s)")
        for idx, id_ev in enumerate(ids_evento, 1):
            print(f"      {idx}. id_evento: {id_ev}")
    else:
        log_alerta("No hay eventos asociados")
        ids_evento = []
    
    # PASO 5: Contar registros a borrar
    log_paso("5️⃣", "CONTAR REGISTROS A BORRAR")
    repuestos_count = contar_registros_asociados(ot_id, ids_evento)
    eventos_count = len(ids_evento)
    
    print(f"      Repuestos: {repuestos_count}")
    print(f"      Eventos: {eventos_count}")
    print(f"      OTs: 1")
    log_exito(f"Total: {repuestos_count + eventos_count + 1} registros")
    
    # PASO 6: Confirmación
    log_paso("6️⃣", "CONFIRMACIÓN DE BORRADO")
    print(f"\n   {Color.FAIL}{Color.BOLD}⚠️  ADVERTENCIA:{Color.ENDC}")
    print(f"   Se borrará la OT {ot_id} y todos sus registros asociados.")
    print(f"   Esta acción NO se puede deshacer.\n")
    
    confirmacion = input("   ¿Desea continuar? (SÍ/no): ").strip().upper()
    
    if confirmacion not in ["SÍ", "SI", "S", "YES", "Y"]:
        print(f"\n   {Color.OKBLUE}Operación cancelada{Color.ENDC}")
        sys.exit(0)
    
    # PASO 7: BORRAR (TRANSACCIÓN ATÓMICA)
    log_paso("7️⃣", "BORRAR EN ORDEN DE INTEGRIDAD REFERENCIAL (TRANSACCIÓN ATÓMICA)")
    
    try:
        with engine.begin() as conn:
            
            # 1. Borrar repuestos_consumidos
            if ids_evento:
                print("   Paso 1/3: Borrar repuestos consumidos...")
                placeholders = ','.join([str(id) for id in ids_evento])
                conn.execute(
                    text(f"""
                        DELETE FROM repuestos_consumidos
                        WHERE id_evento IN ({placeholders})
                    """)
                )
                log_exito(f"Borrados {repuestos_count} repuestos")
            
            # 2. Borrar ot_falla_evento
            print("   Paso 2/3: Borrar eventos de falla...")
            conn.execute(
                text("""
                    DELETE FROM ot_falla_evento
                    WHERE ot_id = :ot_id
                """),
                {"ot_id": ot_id}
            )
            log_exito(f"Borrados {eventos_count} evento(s)")
            
            # 3. Borrar ordenes_trabajo
            print("   Paso 3/3: Borrar orden de trabajo...")
            conn.execute(
                text("""
                    DELETE FROM ordenes_trabajo
                    WHERE ot_id = :ot_id
                """),
                {"ot_id": ot_id}
            )
            log_exito(f"Borrada OT: {ot_id}")
            
            # COMMIT automático al salir del bloque begin()
            print("   Confirmar transacción...")
    
    except Exception as e:
        log_error(f"Error en transacción: {str(e)}\n   🔄 Se revierte automáticamente (ROLLBACK)")
    
    # PASO 8: Verificación final
    log_paso("8️⃣", "VERIFICACIÓN FINAL")
    
    try:
        with engine.connect() as conn:
            ot_existe = conn.execute(
                text("SELECT COUNT(*) FROM ordenes_trabajo WHERE ot_id = :ot_id"),
                {"ot_id": ot_id}
            ).fetchone()[0]
        
        if ot_existe == 0:
            log_exito("Verificación exitosa - OT completamente borrada")
        else:
            log_alerta("La OT aún existe en la BD")
    
    except Exception as e:
        log_error(f"Error en verificación: {str(e)}")
    
    # RESUMEN FINAL
    print("\n" + "=" * 80)
    print(f"{Color.OKGREEN}{Color.BOLD}✅ ORDEN DE TRABAJO BORRADA EXITOSAMENTE{Color.ENDC}")
    print("=" * 80)
    print(f"\n📊 RESUMEN:")
    print(f"   Patente:        {patente_bd} ({marca} {modelo})")
    print(f"   OT_ID:          {ot_id}")
    print(f"   Tipo:           {tipo_ot}")
    print(f"   Registros borrados:")
    print(f"      • Repuestos:     {repuestos_count}")
    print(f"      • Eventos:       {eventos_count}")
    print(f"      • Órdenes:       1")
    print(f"      • TOTAL:         {repuestos_count + eventos_count + 1}")
    print("\n" + "=" * 80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Color.WARNING}Operación cancelada por el usuario{Color.ENDC}")
        sys.exit(0)
    except Exception as e:
        log_error(f"Error inesperado: {str(e)}")
