# revisar_clasificaciones.py
"""
BAITECK — Revisor interactivo de clasificaciones pendientes

Propósito:
  Permite revisar manualmente las clasificaciones pendientes, aceptar sugerencias
  o proporcionar clasificación correcta.
  
Flujo:
  1. Cargar pendientes desde CSV generado por clasificar_fallas.py
  2. Para cada pendiente:
     - Mostrar descripción original
     - Mostrar candidatos sugeridos
     - Permitir: (a) aceptar un candidato, (b) rechazar, (c) clasificar manualmente
  3. Insertar en ot_falla_evento con fuente='manual'

Uso:
  uv run python revisar_clasificaciones.py pendientes_revision.csv
"""

import sys
import os
import pandas as pd
import json
import ast
from datetime import date
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

def cargar_taxonomia_completa() -> pd.DataFrame:
    """Carga toda la taxonomía para búsqueda manual"""
    query = text("""
        SELECT
            taxonomia_id,
            sistema,
            componente,
            modo_falla,
            descripcion_estandar
        FROM taxonomia_fallas
        WHERE activo = TRUE
        ORDER BY sistema, componente
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)

def insertar_evento_falla(ot_id: str, activo_id: str, fecha_evento: date, taxonomia_id: str, notas: str):
    """Inserta evento de falla clasificado manualmente"""
    insert_query = text("""
        INSERT INTO ot_falla_evento (
            ot_id, activo_id, fecha_evento, taxonomia_id,
            confianza_clasificacion, fuente, notas
        ) VALUES (:ot_id, :activo_id, :fecha_evento, :taxonomia_id, 1.0, 'manual', :notas)
        ON CONFLICT DO NOTHING
    """)
    with engine.begin() as conn:
        conn.execute(insert_query, {
            'ot_id': ot_id,
            'activo_id': activo_id,
            'fecha_evento': fecha_evento,
            'taxonomia_id': taxonomia_id,
            'notas': notas
        })

def mostrar_oportunidad(idx: int, total: int, ot: dict, taxonomia_df: pd.DataFrame):
    """Muestra la interfaz de revisión para una orden de trabajo"""
    
    print("\n" + "=" * 100)
    print(f"REVISIÓN {idx + 1}/{total}")
    print("=" * 100)
    
    print(f"\n📋 ORDEN DE TRABAJO")
    print(f"   OT ID:      {ot['ot_id']}")
    print(f"   Activo:     {ot['activo_id']}")
    print(f"   Fecha:      {ot['fecha_apertura']}")
    print(f"   Descripción: {ot['descripcion']}")
    
    # Candidatos sugeridos
    candidatos = ot.get('candidatos', [])
    if candidatos and isinstance(candidatos, str):
        candidatos = ast.literal_eval(candidatos)
    
    if candidatos:
        print(f"\n🤖 CANDIDATOS SUGERIDOS ({len(candidatos)} opciones):")
        for i, cand in enumerate(candidatos[:3], 1):
            score = cand.get('score', 0) if isinstance(cand, dict) else 0
            sistema = cand.get('sistema', cand) if isinstance(cand, dict) else cand
            componente = cand.get('componente', '') if isinstance(cand, dict) else ''
            modo = cand.get('modo_falla', '') if isinstance(cand, dict) else ''
            print(f"   [{i}] {sistema} → {componente} → {modo} (score: {score:.2f})")
    else:
        print("\n🤖 CANDIDATOS SUGERIDOS: Ninguno")
    
    # Menu
    print(f"\n⚙️  OPCIONES:")
    print(f"   [1-{min(3, len(candidatos) if candidatos else 0)}] Aceptar candidato N")
    print(f"   [m] Buscar y clasificar manualmente")
    print(f"   [s] Saltar (no clasificar)")
    print(f"   [q] Quit")
    
    while True:
        choice = input("\nTu opción: ").strip().lower()
        
        if choice == 'q':
            return 'quit'
        elif choice == 's':
            return 'skip'
        elif choice == 'm':
            return clasificar_manual(taxonomia_df)
        elif choice in ['1', '2', '3']:
            idx_cand = int(choice) - 1
            if candidatos and idx_cand < len(candidatos):
                cand = candidatos[idx_cand]
                return cand.get('taxonomia_id') if isinstance(cand, dict) else None
            else:
                print("   ❌ Candidato inválido")
        else:
            print("   ❌ Opción no válida")

def clasificar_manual(taxonomia_df: pd.DataFrame):
    """Interfaz para clasificar manualmente"""
    
    print("\n" + "-" * 100)
    print("BÚSQUEDA MANUAL EN TAXONOMÍA")
    print("-" * 100)
    
    # Buscar por sistema
    sistemas = taxonomia_df['sistema'].unique()
    print(f"\n📋 SISTEMAS DISPONIBLES:")
    for i, sistema in enumerate(sorted(sistemas), 1):
        print(f"   [{i:2d}] {sistema}")
    
    while True:
        try:
            sis_choice = input("\nElige sistema (número): ").strip()
            sis_idx = int(sis_choice) - 1
            if 0 <= sis_idx < len(sistemas):
                sistema_elegido = sorted(sistemas)[sis_idx]
                break
            else:
                print("   ❌ Número inválido")
        except ValueError:
            print("   ❌ Ingresa un número válido")
    
    # Filtrar por sistema y mostrar componentes
    df_sistema = taxonomia_df[taxonomia_df['sistema'] == sistema_elegido]
    componentes = df_sistema['componente'].unique()
    
    print(f"\n📋 COMPONENTES EN {sistema_elegido.upper()}:")
    for i, comp in enumerate(sorted(componentes), 1):
        print(f"   [{i:2d}] {comp}")
    
    while True:
        try:
            comp_choice = input("\nElige componente (número): ").strip()
            comp_idx = int(comp_choice) - 1
            if 0 <= comp_idx < len(componentes):
                componente_elegido = sorted(componentes)[comp_idx]
                break
            else:
                print("   ❌ Número inválido")
        except ValueError:
            print("   ❌ Ingresa un número válido")
    
    # Filtrar por componente y mostrar modos
    df_comp = df_sistema[df_sistema['componente'] == componente_elegido]
    modos = df_comp['modo_falla'].unique()
    
    print(f"\n📋 MODOS DE FALLA EN {componente_elegido.upper()}:")
    for i, modo in enumerate(sorted(modos), 1):
        print(f"   [{i:2d}] {modo}")
    
    while True:
        try:
            modo_choice = input("\nElige modo de falla (número): ").strip()
            modo_idx = int(modo_choice) - 1
            if 0 <= modo_idx < len(modos):
                modo_elegido = sorted(modos)[modo_idx]
                break
            else:
                print("   ❌ Número inválido")
        except ValueError:
            print("   ❌ Ingresa un número válido")
    
    # Obtener taxonomia_id
    df_final = df_comp[df_comp['modo_falla'] == modo_elegido]
    if len(df_final) > 0:
        taxonomia_id = df_final.iloc[0]['taxonomia_id']
        print(f"\n✅ Clasificación manual confirmada:")
        print(f"   Sistema: {sistema_elegido}")
        print(f"   Componente: {componente_elegido}")
        print(f"   Modo: {modo_elegido}")
        return taxonomia_id
    else:
        print("❌ No se encontró combinación válida")
        return None

def main():
    """Orquestación principal"""
    
    if len(sys.argv) < 2:
        print("USO: uv run python revisar_clasificaciones.py <archivo_pendientes.csv>")
        sys.exit(1)
    
    archivo_pendientes = sys.argv[1]
    
    if not os.path.exists(archivo_pendientes):
        print(f"❌ El archivo no existe: {archivo_pendientes}")
        sys.exit(1)
    
    # Cargar datos
    logger.info(f"Cargando pendientes desde: {archivo_pendientes}")
    df_pendientes = pd.read_csv(archivo_pendientes)
    logger.info(f"✅ {len(df_pendientes)} pendientes cargadas")
    
    logger.info("Cargando taxonomía...")
    taxonomia_df = cargar_taxonomia_completa()
    logger.info(f"✅ Taxonomía cargada: {len(taxonomia_df)} registros")
    
    # Revisar cada una
    insertadas = 0
    saltadas = 0
    
    for idx, row in df_pendientes.iterrows():
        resultado = mostrar_oportunidad(idx, len(df_pendientes), row.to_dict(), taxonomia_df)
        
        if resultado == 'quit':
            print("\n⚠️  Saliendo...")
            break
        elif resultado == 'skip':
            saltadas += 1
            print("⏭️  Saltada")
        elif resultado is not None:
            # Insertar en BD
            try:
                insertar_evento_falla(
                    ot_id=row['ot_id'],
                    activo_id=row['activo_id'],
                    fecha_evento=row['fecha_apertura'],
                    taxonomia_id=resultado,
                    notas='Clasificación manual'
                )
                insertadas += 1
                print(f"✅ Insertada en ot_falla_evento")
            except Exception as e:
                print(f"❌ Error: {str(e)}")
    
    # Resumen
    print("\n" + "=" * 100)
    print("RESUMEN")
    print("=" * 100)
    print(f"Revisadas: {idx + 1}")
    print(f"Insertadas: {insertadas}")
    print(f"Saltadas: {saltadas}")
    print("=" * 100)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Interrupción del usuario")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ ERROR: {str(e)}", exc_info=True)
        sys.exit(1)
