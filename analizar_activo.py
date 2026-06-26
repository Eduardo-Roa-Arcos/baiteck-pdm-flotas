#!/usr/bin/env python3
"""
BAITECK PDM - ANÁLISIS COMPLETO DE ACTIVO
Solicita una patente, busca el activo y muestra:
  1. Resumen ejecutivo (estado actual)
  2. Análisis estadístico (MTBF, costos, patrones)
  3. Historial detallado (OTs + repuestos + eventos)

Uso:
  uv run python analizar_activo.py
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import pandas as pd

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no está definido en .env")
    exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

# ============================================================================
# COLORES PARA TERMINAL
# ============================================================================

class Color:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_titulo(texto):
    print(f"\n{Color.HEADER}{Color.BOLD}{'='*80}{Color.ENDC}")
    print(f"{Color.HEADER}{Color.BOLD}{texto}{Color.ENDC}")
    print(f"{Color.HEADER}{Color.BOLD}{'='*80}{Color.ENDC}\n")

def print_subtitulo(texto):
    print(f"\n{Color.BOLD}{Color.OKBLUE}{texto}{Color.ENDC}")
    print(f"{Color.OKBLUE}{'-'*80}{Color.ENDC}\n")

def print_exito(texto):
    print(f"{Color.OKGREEN}✅ {texto}{Color.ENDC}")

def print_error(texto):
    print(f"{Color.FAIL}❌ {texto}{Color.ENDC}")

def print_alerta(texto):
    print(f"{Color.WARNING}⚠️  {texto}{Color.ENDC}")

def semaforo(prioridad):
    """Retorna código de color según prioridad"""
    if prioridad == "P1_critica":
        return f"{Color.FAIL}{prioridad}{Color.ENDC}"
    elif prioridad == "P2_alta":
        return f"{Color.WARNING}{prioridad}{Color.ENDC}"
    elif prioridad == "P3_media":
        return f"{Color.OKGREEN}{prioridad}{Color.ENDC}"
    else:
        return f"{Color.OKGREEN}{prioridad}{Color.ENDC}"

# ============================================================================
# FUNCIONES DE BÚSQUEDA
# ============================================================================

def buscar_activo(patente):
    """Busca activo por patente"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT activo_id, patente, marca, modelo, anio_fabricacion, tipo_vehiculo, motor_tipo, estado_actual, odometro_km
                FROM activos
                WHERE UPPER(patente) = UPPER(:patente)
            """),
            {"patente": patente}
        ).fetchone()
    
    return result

def obtener_scoring_actual(activo_id):
    """Obtiene scoring más reciente del activo"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 
                    fecha_scoring,
                    probabilidad_falla,
                    prioridad,
                    sistema_en_riesgo,
                    horizonte_dias
                FROM scoring_resultados
                WHERE activo_id = :activo_id
                ORDER BY fecha_scoring DESC, horizonte_dias ASC
                LIMIT 1
            """),
            {"activo_id": activo_id}
        ).fetchone()
    
    return result

def obtener_scoring_multi_horizonte(activo_id, fecha_scoring):
    """Obtiene probabilidades en 7, 30, 90 días"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT horizonte_dias, probabilidad_falla
                FROM scoring_resultados
                WHERE activo_id = :activo_id
                  AND fecha_scoring = :fecha
                ORDER BY horizonte_dias ASC
            """),
            {"activo_id": activo_id, "fecha": fecha_scoring}
        ).fetchall()
    
    return {row[0]: row[1] for row in result}

def obtener_ultima_ot(activo_id):
    """Obtiene la última OT del activo"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 
                    ot_id,
                    fecha_apertura,
                    fecha_cierre,
                    tipo_ot,
                    descripcion_falla,
                    costo_total_clp,
                    odometro_km,
                    horometro_h
                FROM ordenes_trabajo
                WHERE activo_id = :activo_id
                ORDER BY fecha_apertura DESC
                LIMIT 1
            """),
            {"activo_id": activo_id}
        ).fetchone()
    
    return result

def obtener_odometro_actual(activo_id):
    """Obtiene el odómetro más reciente del activo"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT COALESCE(MAX(odometro_km), 0)
                FROM ordenes_trabajo
                WHERE activo_id = :activo_id
                  AND odometro_km IS NOT NULL
            """),
            {"activo_id": activo_id}
        ).fetchone()
    
    return result[0] if result else 0

def obtener_analisis_estadistico(activo_id):
    """Obtiene análisis estadístico completo"""
    with engine.connect() as conn:
        # Total OTs
        ots = conn.execute(
            text("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN LOWER(tipo_ot) = 'preventiva' THEN 1 ELSE 0 END) as preventivas,
                    SUM(CASE WHEN LOWER(tipo_ot) = 'correctiva' THEN 1 ELSE 0 END) as correctivas,
                    COALESCE(SUM(costo_total_clp), 0) as costo_total,
                    COALESCE(MAX(fecha_apertura::date) - MIN(fecha_apertura::date), 0) as dias_periodo
                FROM ordenes_trabajo
                WHERE activo_id = :activo_id
            """),
            {"activo_id": activo_id}
        ).fetchone()
        
        # Repuestos más usados
        repuestos = conn.execute(
            text("""
                SELECT sku, descripcion_repuesto, SUM(cantidad) as total_qty
                FROM repuestos_consumidos
                WHERE ot_id IN (
                    SELECT ot_id FROM ordenes_trabajo WHERE activo_id = :activo_id
                )
                GROUP BY sku, descripcion_repuesto
                ORDER BY total_qty DESC
                LIMIT 10
            """),
            {"activo_id": activo_id}
        ).fetchall()
        
        # Sistemas más problemáticos
        sistemas = conn.execute(
            text("""
                SELECT 
                    tf.sistema,
                    COUNT(DISTINCT ofe.id_evento) as eventos,
                    COUNT(DISTINCT ot.ot_id) as ots
                FROM ot_falla_evento ofe
                JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
                LEFT JOIN ordenes_trabajo ot ON ofe.ot_id = ot.ot_id
                WHERE COALESCE(ofe.activo_id, ot.activo_id) = :activo_id
                GROUP BY tf.sistema
                ORDER BY eventos DESC
                LIMIT 5
            """),
            {"activo_id": activo_id}
        ).fetchall()
    
    return {
        "ots": ots,
        "repuestos": repuestos,
        "sistemas": sistemas
    }

def obtener_historial_ots(activo_id):
    """Obtiene todas las OTs ordenadas por fecha descendente"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 
                    ot_id,
                    fecha_apertura,
                    fecha_cierre,
                    tipo_ot,
                    descripcion_falla,
                    costo_total_clp,
                    odometro_km,
                    horometro_h,
                    taller_id,
                    responsable
                FROM ordenes_trabajo
                WHERE activo_id = :activo_id
                ORDER BY fecha_apertura DESC
            """),
            {"activo_id": activo_id}
        ).fetchall()
    
    return result

def obtener_repuestos_por_ot(ot_id):
    """Obtiene repuestos usados en una OT"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 
                    sku,
                    descripcion_repuesto,
                    cantidad,
                    costo_unitario_clp,
                    fue_compra_urgencia
                FROM repuestos_consumidos
                WHERE ot_id = :ot_id
            """),
            {"ot_id": ot_id}
        ).fetchall()
    
    return result

def obtener_eventos_por_ot(ot_id):
    """Obtiene eventos de falla asociados a una OT"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 
                    ofe.id_evento,
                    ofe.causa_probable,
                    ofe.accion_realizada,
                    tf.sistema,
                    tf.componente,
                    tf.descripcion_estandar,
                    ofe.es_causa_raiz
                FROM ot_falla_evento ofe
                LEFT JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
                WHERE ofe.ot_id = :ot_id
                ORDER BY ofe.id_evento
            """),
            {"ot_id": ot_id}
        ).fetchall()
    
    return result

# ============================================================================
# PRESENTACIÓN
# ============================================================================

def mostrar_resumen_ejecutivo(activo_info, scoring_actual, ultima_ot, odometro, scoring_multi):
    """Muestra resumen ejecutivo del activo"""
    
    activo_id, patente, marca, modelo, anio, tipo_vehiculo, motor_tipo, estado_actual, odo_activos = activo_info
    
    print_titulo(f"ACTIVO: {patente} ({activo_id})")
    
    print(f"{'Marca':<30} {Color.BOLD}{marca}{Color.ENDC}")
    print(f"{'Modelo':<30} {Color.BOLD}{modelo}{Color.ENDC}")
    print(f"{'Año Fabricación':<30} {Color.BOLD}{anio}{Color.ENDC}")
    print(f"{'Tipo Vehículo':<30} {tipo_vehiculo}")
    print(f"{'Motor':<30} {motor_tipo}")
    print(f"{'Estado':<30} {estado_actual}")
    
    print_subtitulo("ESTADO ACTUAL - SCORING")
    
    if scoring_actual:
        fecha_scoring, prob_falla, prioridad, sistema_riesgo, horizonte = scoring_actual
        print(f"{'Prioridad':<30} {semaforo(prioridad)}")
        print(f"{'Fecha Scoring':<30} {fecha_scoring}")
        print(f"{'Probabilidad Falla (30d)':<30} {Color.BOLD}{prob_falla*100:.1f}%{Color.ENDC}")
        print(f"{'Sistema en Riesgo':<30} {sistema_riesgo if sistema_riesgo else '(sin clasificar)'}")
        
        if scoring_multi:
            print(f"\n{'Probabilidades por horizonte:':<30}")
            for horizonte in [7, 30, 90]:
                if horizonte in scoring_multi:
                    prob = scoring_multi[horizonte]
                    print(f"  {horizonte} días: {prob*100:.1f}%")
    else:
        print_alerta("Sin scoring disponible")
    
    if ultima_ot:
        ot_id, fecha_ap, fecha_ci, tipo, desc, costo, odometro_ot, horometro = ultima_ot
        dias_desde = (datetime.now().date() - fecha_ap.date()).days if fecha_ap else 0
        print(f"\n{'Última OT':<30} {ot_id}")
        print(f"{'Tipo':<30} {tipo}")
        print(f"{'Fecha':<30} {fecha_ap.strftime('%Y-%m-%d') if fecha_ap else 'N/A'}")
        print(f"{'Días desde última OT':<30} {dias_desde}")
        print(f"{'Descripción':<30} {desc if desc else '(sin descripción)'}")
        if costo:
            print(f"{'Costo':<30} ${costo:,.0f} CLP")
    
    print(f"\n{'Km Actual':<30} {odometro:,.0f} km")
    print()

def mostrar_analisis_estadistico(analisis):
    """Muestra análisis estadístico"""
    
    print_subtitulo("ANÁLISIS ESTADÍSTICO")
    
    ots_data = analisis["ots"]
    if ots_data:
        total, preventivas, correctivas, costo_total, dias_periodo = ots_data
        
        print(f"{'Total OTs':<30} {Color.BOLD}{total}{Color.ENDC}")
        print(f"  Preventivas: {preventivas} | Correctivas: {correctivas}")
        print(f"{'Costo Total Acumulado':<30} ${costo_total:,.0f} CLP")
        
        if total > 1 and dias_periodo > 0:
            promedio_dias = dias_periodo / (total - 1)
            print(f"{'Promedio días entre OTs':<30} {promedio_dias:.1f} días")
            mtbf = dias_periodo / correctivas if correctivas > 0 else 0
            print(f"{'MTBF (dias/correctiva)':<30} {mtbf:.1f} días")
    
    # Sistemas
    sistemas = analisis["sistemas"]
    if sistemas:
        print(f"\n{'Sistemas más problemáticos:':<30}")
        for sistema, eventos, ots in sistemas:
            print(f"  {sistema:<25} {eventos} eventos | {ots} OTs")
    
    # Repuestos
    repuestos = analisis["repuestos"]
    if repuestos:
        print(f"\n{'Top 5 repuestos usados:':<30}")
        for sku, desc, qty in repuestos[:5]:
            print(f"  {sku:<20} {qty:.0f} unidades")
    
    print()

def mostrar_historial(historial_ots, activo_id):
    """Muestra historial detallado de OTs"""
    
    print_subtitulo("HISTORIAL DETALLADO (Ordenado por fecha descendente)")
    
    if not historial_ots:
        print_alerta("Sin órdenes de trabajo registradas")
        return
    
    for idx, ot in enumerate(historial_ots, 1):
        ot_id, fecha_ap, fecha_ci, tipo, desc, costo, odometro, horometro, taller, responsable = ot
        
        # Encabezado OT
        print(f"\n{Color.BOLD}[{idx}] OT: {ot_id}{Color.ENDC}")
        print(f"    Fecha: {fecha_ap.strftime('%Y-%m-%d %H:%M')}", end="")
        if fecha_ci:
            duracion = (fecha_ci - fecha_ap).total_seconds() / 3600
            print(f" → {fecha_ci.strftime('%Y-%m-%d %H:%M')} ({duracion:.1f} horas)")
        else:
            print(" (abierta)")
        
        print(f"    Tipo: {Color.OKBLUE}{tipo}{Color.ENDC}")
        print(f"    Descripción: {desc if desc else '(sin descripción)'}")
        
        if costo:
            print(f"    Costo: ${costo:,.0f} CLP")
        if odometro:
            print(f"    Odómetro: {odometro:,.0f} km", end="")
        if horometro:
            print(f" | Horómetro: {horometro:.1f} h")
        else:
            print()
        
        if taller or responsable:
            print(f"    Taller: {taller if taller else 'N/A'} | Responsable: {responsable if responsable else 'N/A'}")
        
        # Eventos de falla
        eventos = obtener_eventos_por_ot(ot_id)
        if eventos:
            print(f"\n    {Color.OKCYAN}Eventos de falla:{Color.ENDC}")
            for evento in eventos:
                id_ev, causa, accion, sistema, componente, descripcion, es_raiz = evento
                print(f"      • Sistema: {sistema} / Componente: {componente}")
                if descripcion:
                    print(f"        Descripción: {descripcion}")
                if causa:
                    print(f"        Causa probable: {causa}")
                if accion:
                    print(f"        Acción realizada: {accion}")
                if es_raiz:
                    print(f"        ⭐ Causa raíz identificada")
        
        # Repuestos
        repuestos = obtener_repuestos_por_ot(ot_id)
        if repuestos:
            print(f"\n    {Color.OKCYAN}Repuestos usados:{Color.ENDC}")
            for sku, desc_rep, qty, costo_unit, urgencia in repuestos:
                urgencia_txt = "⚡ URGENCIA" if urgencia else "Normal"
                print(f"      • {sku}: {qty:.0f} unidades {urgencia_txt}")
                if desc_rep:
                    print(f"        {desc_rep}")
                if costo_unit:
                    print(f"        Costo unitario: ${costo_unit:,.0f} CLP")
        
        print("-" * 80)

# ============================================================================
# PROGRAMA PRINCIPAL
# ============================================================================

def main():
    print_titulo("BAITECK PDM - ANÁLISIS COMPLETO DE ACTIVO")
    
    # Solicitar patente
    patente = input(f"{Color.BOLD}Ingrese la patente del activo: {Color.ENDC}").strip().upper()
    
    if not patente:
        print_error("Patente vacía")
        return
    
    # Buscar activo
    print(f"\n🔍 Buscando activo con patente {patente}...")
    activo_info = buscar_activo(patente)
    
    if not activo_info:
        print_error(f"Activo con patente '{patente}' no encontrado")
        return
    
    activo_id = activo_info[0]
    print_exito(f"Activo encontrado: {activo_info[2]} {activo_info[3]} ({activo_id})")
    
    # Obtener información
    print("\n⏳ Cargando información...")
    
    scoring_actual = obtener_scoring_actual(activo_id)
    ultima_ot = obtener_ultima_ot(activo_id)
    odometro = obtener_odometro_actual(activo_id)
    
    scoring_multi = {}
    if scoring_actual:
        scoring_multi = obtener_scoring_multi_horizonte(
            activo_id, 
            scoring_actual[0]
        )
    
    analisis = obtener_analisis_estadistico(activo_id)
    historial_ots = obtener_historial_ots(activo_id)
    
    print_exito("Información cargada")
    
    # Mostrar todo
    mostrar_resumen_ejecutivo(activo_info, scoring_actual, ultima_ot, odometro, scoring_multi)
    mostrar_analisis_estadistico(analisis)
    mostrar_historial(historial_ots, activo_id)
    
    print_titulo("FIN DEL ANÁLISIS")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Color.WARNING}Análisis cancelado por el usuario{Color.ENDC}")
    except Exception as e:
        print_error(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
