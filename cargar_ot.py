#!/usr/bin/env python3
"""
BAITECK PDM - CARGAR ORDEN DE TRABAJO CON TIPO CONFIGURABLE
================================================================================
Mejoras sobre v1:
  • Usuario elige tipo de OT (predictiva, preventiva, correctiva, etc.)
  • Descripción automática según el tipo
  • Resto del flujo igual: 2 eventos, repuestos automáticos, transacción atómica

Uso:
  uv run python cargar_ot_v2.py
"""

import os
import sys
from datetime import datetime, timedelta
import random
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no está definido en .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

# ============================================================================
# CONSTANTES
# ============================================================================

HORA_APERTURA = "08:00:00"
HORA_CIERRE = "17:00:00"

# Tipos de OT disponibles con descripciones
TIPOS_OT_DISPONIBLES = {
    "1": {
        "tipo": "correctiva",
        "descripcion_template": "Servicio correctivo - {}",
        "icono": "🔧"
    },
    "2": {
        "tipo": "preventiva",
        "descripcion_template": "Mantención preventiva - {}",
        "icono": "📋"
    },
    "3": {
        "tipo": "predictiva",
        "descripcion_template": "Servicio predictivo - {}",
        "icono": "🔮"
    },
}

# ============================================================================
# MAPEO CON VARIANTES: Componente → [Variante1, Variante2, ...]
# Esto garantiza que dos eventos usen repuestos DIFERENTES aunque sean el mismo componente
# ============================================================================

REPUESTOS_POR_COMPONENTE_VARIANTES = {
    # REFRIGERACIÓN - VARIANTES
    "radiador": [
        # Variante 1
        [
            {"sku": "RADIADOR-AGUA", "descripcion": "Radiador de agua", "cantidad": 1, "urgencia": True},
            {"sku": "TERMOSTATO", "descripcion": "Termostato", "cantidad": 1, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "REFRIGERANTE", "descripcion": "Refrigerante motor", "cantidad": 5, "urgencia": False},
            {"sku": "JUNTA-RADIADOR", "descripcion": "Junta radiador", "cantidad": 2, "urgencia": False}
        ]
    ],
    "bomba_agua": [
        # Variante 1
        [
            {"sku": "BOMBA-AGUA", "descripcion": "Bomba de agua", "cantidad": 1, "urgencia": True},
            {"sku": "CORREA-BOMBA", "descripcion": "Correa bomba de agua", "cantidad": 1, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "SELLO-BOMBA", "descripcion": "Sello de bomba", "cantidad": 2, "urgencia": False},
            {"sku": "RODAMIENTO-BOMBA", "descripcion": "Rodamiento bomba", "cantidad": 1, "urgencia": True}
        ]
    ],
    "ventilador": [
        # Variante 1
        [
            {"sku": "VENTILADOR-MOTOR", "descripcion": "Ventilador de refrigeración", "cantidad": 1, "urgencia": False},
            {"sku": "REFRIGERANTE", "descripcion": "Refrigerante motor", "cantidad": 3, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "CLUTCH-VENTILADOR", "descripcion": "Clutch del ventilador", "cantidad": 1, "urgencia": True},
            {"sku": "MANGUERA-VENTILADOR", "descripcion": "Manguera ventilador", "cantidad": 1, "urgencia": False}
        ]
    ],
    
    # FRENOS - VARIANTES
    "pastillas": [
        # Variante 1
        [
            {"sku": "FRENO-PASTILLA-001", "descripcion": "Pastillas de freno delanteras", "cantidad": 4, "urgencia": True},
            {"sku": "FRENO-PASTILLA-SPRAY", "descripcion": "Spray antirruido frenos", "cantidad": 1, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "FRENO-LIQUIDO", "descripcion": "Líquido de frenos DOT 4", "cantidad": 2, "urgencia": False},
            {"sku": "CILINDRO-RUEDA", "descripcion": "Cilindro de rueda freno", "cantidad": 2, "urgencia": True}
        ]
    ],
    "discos": [
        # Variante 1
        [
            {"sku": "FRENO-DISCO-001", "descripcion": "Disco de freno", "cantidad": 2, "urgencia": True},
            {"sku": "TORNILLO-DISCO", "descripcion": "Tornillo de fijación disco", "cantidad": 4, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "FRENO-PASTILLA-001", "descripcion": "Pastillas de freno", "cantidad": 4, "urgencia": True},
            {"sku": "ADAPTADOR-DISCO", "descripcion": "Adaptador disco freno", "cantidad": 1, "urgencia": False}
        ]
    ],
    
    # SUSPENSIÓN - VARIANTES
    "amortiguador_delantero": [
        # Variante 1
        [
            {"sku": "SUSPENSION-AMORTIGUADOR", "descripcion": "Amortiguador delantero", "cantidad": 2, "urgencia": True},
            {"sku": "SELLO-AMORTIGUADOR", "descripcion": "Sello de amortiguador", "cantidad": 2, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "BUJE-AMORTIGUADOR", "descripcion": "Buje de amortiguador", "cantidad": 2, "urgencia": False},
            {"sku": "ACEITE-AMORTIGUADOR", "descripcion": "Aceite amortiguador", "cantidad": 1, "urgencia": False}
        ]
    ],
    "muelle": [
        # Variante 1
        [
            {"sku": "SUSPENSION-ESPIRAL", "descripcion": "Muelle de suspensión", "cantidad": 1, "urgencia": False},
            {"sku": "AISLANTE-MUELLE", "descripcion": "Aislante de muelle", "cantidad": 1, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "GOMA-MUELLE", "descripcion": "Goma de muelle", "cantidad": 2, "urgencia": False},
            {"sku": "RESORTE-MUELLE", "descripcion": "Resorte complementario", "cantidad": 1, "urgencia": False}
        ]
    ],
    
    # MOTOR COMBUSTIÓN - VARIANTES
    "bloque": [
        # Variante 1
        [
            {"sku": "ACEITE-MOTOR", "descripcion": "Aceite mineral SAE 40", "cantidad": 5, "urgencia": False},
            {"sku": "FILTRO-ACEITE", "descripcion": "Filtro de aceite", "cantidad": 1, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "JUNTA-BLOQUE", "descripcion": "Junta de bloque motor", "cantidad": 2, "urgencia": True},
            {"sku": "PERNO-BLOQUE", "descripcion": "Perno de bloque", "cantidad": 8, "urgencia": False}
        ]
    ],
    "pistones": [
        # Variante 1
        [
            {"sku": "ANILLO-PISTON", "descripcion": "Aros de pistón", "cantidad": 4, "urgencia": True},
            {"sku": "ACEITE-MOTOR", "descripcion": "Aceite mineral SAE 40", "cantidad": 5, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "PISTON-COMPLETO", "descripcion": "Pistón completo", "cantidad": 2, "urgencia": True},
            {"sku": "PASADOR-PISTON", "descripcion": "Pasador de pistón", "cantidad": 4, "urgencia": False}
        ]
    ],
    
    # TRANSMISIÓN - VARIANTES
    "caja_cambios": [
        # Variante 1
        [
            {"sku": "ACEITE-TRANSMISION", "descripcion": "Aceite de transmisión ATF", "cantidad": 3, "urgencia": False},
            {"sku": "FILTRO-TRANSMISION", "descripcion": "Filtro de transmisión", "cantidad": 1, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "JUNTA-TRANSMISION", "descripcion": "Junta de transmisión", "cantidad": 3, "urgencia": True},
            {"sku": "ACEITE-TRANSMISION", "descripcion": "Aceite de transmisión ATF", "cantidad": 2, "urgencia": False}
        ]
    ],
    "embrague": [
        # Variante 1
        [
            {"sku": "DISCO-EMBRAGUE", "descripcion": "Disco de embrague", "cantidad": 1, "urgencia": True},
            {"sku": "COJINETE-EMBRAGUE", "descripcion": "Cojinete de embrague", "cantidad": 1, "urgencia": False}
        ],
        # Variante 2
        [
            {"sku": "PRESION-EMBRAGUE", "descripcion": "Plato de presión", "cantidad": 1, "urgencia": True},
            {"sku": "VOLANTE-MOTOR", "descripcion": "Volante motor ranurado", "cantidad": 1, "urgencia": False}
        ]
    ],
}

# Fallback por sistema (sin variantes)
REPUESTOS_POR_SISTEMA_FALLBACK = {
    "refrigeracion": [
        {"sku": "REFRIGERANTE", "descripcion": "Refrigerante motor", "cantidad": 5, "urgencia": False},
        {"sku": "BOMBA-AGUA", "descripcion": "Bomba de agua", "cantidad": 1, "urgencia": True}
    ],
    "frenos_servicio": [
        {"sku": "FRENO-PASTILLA-001", "descripcion": "Pastillas de freno", "cantidad": 4, "urgencia": True},
        {"sku": "FRENO-LIQUIDO", "descripcion": "Líquido de frenos DOT 4", "cantidad": 2, "urgencia": False}
    ],
    "suspension": [
        {"sku": "SUSPENSION-AMORTIGUADOR", "descripcion": "Amortiguador", "cantidad": 2, "urgencia": True},
        {"sku": "SUSPENSION-ESPIRAL", "descripcion": "Muelle de suspensión", "cantidad": 1, "urgencia": False}
    ],
    "transmision": [
        {"sku": "ACEITE-TRANSMISION", "descripcion": "Aceite de transmisión ATF", "cantidad": 3, "urgencia": False},
        {"sku": "FILTRO-TRANSMISION", "descripcion": "Filtro de transmisión", "cantidad": 1, "urgencia": False}
    ],
    "motor_combustion": [
        {"sku": "FILTRO-AIRE", "descripcion": "Filtro de aire motor", "cantidad": 1, "urgencia": False},
        {"sku": "ACEITE-MOTOR", "descripcion": "Aceite mineral SAE 40", "cantidad": 5, "urgencia": False}
    ],
    "electricidad": [
        {"sku": "BATERIA-VEHICULO", "descripcion": "Batería 12V", "cantidad": 1, "urgencia": True},
        {"sku": "ALTERNADOR", "descripcion": "Alternador", "cantidad": 1, "urgencia": False}
    ],
}

# ============================================================================
# UTILIDADES
# ============================================================================

def log_paso(numero, mensaje):
    """Log de paso con formato"""
    print(f"\n{numero} {mensaje}")

def log_exito(mensaje):
    """Log de éxito"""
    print(f"   ✅ {mensaje}")

def log_error(mensaje):
    """Log de error"""
    print(f"   ❌ ERROR: {mensaje}")
    sys.exit(1)

def log_alerta(mensaje):
    """Log de alerta"""
    print(f"   ⚠️  {mensaje}")

def mostrar_menu_tipos_ot():
    """Muestra menú para seleccionar tipo de OT"""
    print("\n   Seleccione tipo de OT:")
    for key, config in TIPOS_OT_DISPONIBLES.items():
        print(f"      {key}. {config['icono']} {config['tipo'].upper()}")
    
    seleccion = input("\n   Ingrese opción (1-3): ").strip()
    
    if seleccion not in TIPOS_OT_DISPONIBLES:
        log_error("Opción inválida")
    
    return TIPOS_OT_DISPONIBLES[seleccion]

# ============================================================================
# DATOS SINTÉTICOS Y FUNCIONES AUXILIARES
# ============================================================================

import random

NOMBRES_RESPONSABLES = [
    "Juan Pérez", "Carlos Rodríguez", "Miguel González", "Roberto López",
    "Francisco García", "Antonio Martínez", "Jorge Fernández", "Luis Sánchez",
    "Diego Ramirez", "Andrés Morales", "Javier Ruiz", "Oscar Gutierrez"
]

OBSERVACIONES_POR_SISTEMA = {
    "refrigeracion": [
        "Sistema de refrigeración verificado y optimizado",
        "Radiador limpiado y sellado preventivamente",
        "Bomba de agua reemplazada por desgaste",
        "Mantenimiento preventivo de circuito de enfriamiento",
        "Revisión de termostato y lubricación de componentes"
    ],
    "frenos_servicio": [
        "Sistema de frenado revisado y ajustado",
        "Pastillas reemplazadas con especificación OEM",
        "Cilindro maestro inspeccionado y sellado",
        "Líneas de freno purgadas y presionadas",
        "Discos rotados y calibrados para máximo rendimiento"
    ],
    "suspension": [
        "Alineación de suspension completada",
        "Amortiguadores reemplazados por fatiga de material",
        "Muelles inspeccionados y ajustados",
        "Barras estabilizadoras lubricadas",
        "Inspección de seguridad de suspension completada"
    ],
    "transmision": [
        "Aceite de transmisión cambiado",
        "Embrague inspeccionado y ajustado",
        "Caja de cambios revisada y lubricada",
        "Filtro de transmisión reemplazado",
        "Sistema de selección verificado"
    ],
    "motor_combustion": [
        "Aceite y filtro de motor reemplazados",
        "Bujías inspeccionadas y reemplazadas",
        "Filtro de aire limpiado",
        "Correas de motor inspeccionadas",
        "Bloque de motor revisado por fugas"
    ],
    "electricidad": [
        "Batería testeada y cargada",
        "Sistema eléctrico diagnosticado",
        "Alternador verificado",
        "Cableado inspeccionado",
        "Fusibles y relés reemplazados según necesidad"
    ],
}

def obtener_horometro_estimado(ultima_ot):
    """Estima horómetro basándose en última OT (incremento lógico en horas)"""
    horometro_base = 100
    if ultima_ot:
        ot_id, fecha, costo, odo, tipo, horometro_ant = ultima_ot
        if horometro_ant and float(horometro_ant) > 0:
            incremento = random.randint(40, 100)
            horometro_base = float(horometro_ant) + incremento
    return round(horometro_base, 1)

def obtener_taller_anterior(activo_id):
    """Obtiene el último taller usado por la unidad, o 'taller_01' por defecto"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT taller_id
                    FROM ordenes_trabajo
                    WHERE activo_id = :activo_id
                    AND taller_id IS NOT NULL
                    ORDER BY fecha_apertura DESC
                    LIMIT 1
                """),
                {"activo_id": activo_id}
            ).fetchone()
        if result and result[0]:
            return result[0]
    except Exception:
        pass
    return "taller_01"

def obtener_responsable_aleatorio():
    """Retorna un nombre sintético aleatorio para responsable"""
    return random.choice(NOMBRES_RESPONSABLES)

def obtener_observaciones(sistema_en_riesgo):
    """Retorna observaciones sintéticas relacionadas al sistema"""
    observaciones_sistema = OBSERVACIONES_POR_SISTEMA.get(sistema_en_riesgo, [])
    if observaciones_sistema:
        return random.choice(observaciones_sistema)
    return f"Servicio técnico realizado en sistema {sistema_en_riesgo}"

# ============================================================================
# FUNCIONES DE BÚSQUEDA Y VALIDACIÓN
# ============================================================================

def buscar_activo(patente):
    """Busca activo por patente"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT activo_id, patente, marca, modelo, anio_fabricacion, tipo_vehiculo
                    FROM activos
                    WHERE UPPER(patente) = UPPER(:patente)
                    AND estado_actual = 'Activo'
                """),
                {"patente": patente}
            ).fetchone()
        return result
    except Exception as e:
        log_error(f"Error buscando activo: {str(e)}")

def obtener_ultima_ot(activo_id):
    """Obtiene la última OT del activo completa con horómetro"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT 
                        ot_id,
                        fecha_apertura,
                        costo_total_clp,
                        odometro_km,
                        tipo_ot,
                        horometro_h
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

def obtener_scoring_actual(activo_id):
    """Obtiene scoring más reciente"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT 
                        fecha_scoring,
                        prioridad,
                        sistema_en_riesgo
                    FROM scoring_resultados
                    WHERE activo_id = :activo_id
                    ORDER BY fecha_scoring DESC
                    LIMIT 1
                """),
                {"activo_id": activo_id}
            ).fetchone()
        return result
    except Exception as e:
        log_error(f"Error obteniendo scoring: {str(e)}")

def obtener_taxonomias_por_sistema(sistema):
    """Obtiene 2 taxonomías para un sistema"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT taxonomia_id, componente, descripcion_estandar
                    FROM taxonomia_fallas
                    WHERE LOWER(sistema) = LOWER(:sistema)
                    AND activo = TRUE
                    LIMIT 2
                """),
                {"sistema": sistema}
            ).fetchall()
        return result
    except Exception as e:
        log_error(f"Error obteniendo taxonomías: {str(e)}")

def generar_ot_id(anio_actual):
    """Genera siguiente OT_ID"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT COALESCE(
                        MAX(CAST(SPLIT_PART(ot_id, '-', 3) AS INTEGER)), 
                        0
                    ) + 1 as proxima_secuencia
                    FROM ordenes_trabajo
                    WHERE ot_id LIKE :patron
                """),
                {"patron": f"OT-{anio_actual}-%"}
            ).fetchone()
        
        proxima_secuencia = result[0]
        return f"OT-{anio_actual}-{proxima_secuencia}"
    except Exception as e:
        log_error(f"Error generando OT_ID: {str(e)}")

def estimar_costo_odometro(ultima_ot):
    """Estima costo y odómetro"""
    costo = 300000
    odometro = 100
    
    if ultima_ot:
        ot_id, fecha, costo_ant, odo_ant, tipo, horometro = ultima_ot
        if costo_ant:
            costo = float(costo_ant) * 1.15
        if odo_ant:
            odometro = float(odo_ant) + 150
    
    return costo, odometro

# ============================================================================
# PROGRAMA PRINCIPAL
# ============================================================================

def main():
    print("=" * 80)
    print("📋 BAITECK PDM - CARGAR OT CON TIPO CONFIGURABLE")
    print("=" * 80)
    
    # PASO 1: Solicitar patente
    log_paso("1️⃣", "SOLICITAR PATENTE")
    patente = input("   Ingrese patente del activo: ").strip().upper()
    
    if not patente:
        log_error("Patente no puede estar vacía")
    
    # PASO 2: Buscar activo
    log_paso("2️⃣", f"BUSCAR ACTIVO '{patente}'")
    activo_info = buscar_activo(patente)
    
    if not activo_info:
        log_error(f"Activo '{patente}' no encontrado o no está activo")
    
    activo_id, patente_bd, marca, modelo, anio, tipo = activo_info
    log_exito(f"{marca} {modelo} ({activo_id})")
    
    # PASO 3: Seleccionar tipo de OT
    log_paso("3️⃣", "SELECCIONAR TIPO DE OT")
    tipo_ot_config = mostrar_menu_tipos_ot()
    tipo_ot = tipo_ot_config["tipo"]
    log_exito(f"Tipo seleccionado: {tipo_ot_config['icono']} {tipo_ot.upper()}")
    
    # PASO 4: Obtener última OT
    log_paso("4️⃣", "OBTENER ÚLTIMA OT")
    ultima_ot = obtener_ultima_ot(activo_id)
    
    if ultima_ot:
        ot_id_ant, fecha_ant, costo_ant, odo_ant, tipo_ant, horo_ant = ultima_ot
        log_exito(f"Encontrada: {ot_id_ant} ({tipo_ant})")
    else:
        log_alerta("No hay OT previa (usará valores por defecto)")
        ultima_ot = None
    
    # PASO 5: Obtener scoring
    log_paso("5️⃣", "OBTENER SCORING Y SISTEMA EN RIESGO")
    scoring = obtener_scoring_actual(activo_id)
    
    if not scoring:
        log_error(f"No hay scoring para {activo_id} (ejecutar ejecutar_scoring.py primero)")
    
    fecha_scoring, prioridad, sistema_en_riesgo = scoring
    
    if not sistema_en_riesgo or sistema_en_riesgo == "sin_historial_ot":
        log_alerta("No hay sistema en riesgo, usando 'motor_combustion' por defecto")
        sistema_en_riesgo = "motor_combustion"
    
    log_exito(f"Sistema: {sistema_en_riesgo} (Prioridad: {prioridad})")
    
    # PASO 6: Obtener taxonomías
    log_paso("6️⃣", f"BUSCAR TAXONOMÍAS PARA '{sistema_en_riesgo}'")
    taxonomias = obtener_taxonomias_por_sistema(sistema_en_riesgo)
    
    if len(taxonomias) < 2:
        log_alerta(f"Solo {len(taxonomias)} taxonomía(s), buscando alternativa")
        taxonomias = obtener_taxonomias_por_sistema("motor_combustion")
        if not taxonomias:
            log_error("No hay taxonomías disponibles")
    
    log_exito(f"Encontradas {len(taxonomias)} taxonomías")
    for idx, (tax_id, componente, desc) in enumerate(taxonomias[:2], 1):
        print(f"      {idx}. {componente}: {desc}")
    
    # PASO 7: Estimar datos
    log_paso("7️⃣", "ESTIMAR COSTO, ODÓMETRO, HORÓMETRO Y DATOS OPERACIONALES")
    costo_ot, odometro_ot = estimar_costo_odometro(ultima_ot)
    horometro_ot = obtener_horometro_estimado(ultima_ot)
    taller_ot = obtener_taller_anterior(activo_id)
    responsable_ot = obtener_responsable_aleatorio()
    observaciones_ot = obtener_observaciones(sistema_en_riesgo)
    
    log_exito(f"Costo: ${costo_ot:,.0f} CLP | Km: {odometro_ot:,.0f} | Horas: {horometro_ot}")
    log_exito(f"Taller: {taller_ot} | Responsable: {responsable_ot}")
    
    # PASO 8: Generar OT_ID
    log_paso("8️⃣", "GENERAR OT_ID")
    anio_actual = datetime.now().year
    ot_id_nuevo = generar_ot_id(anio_actual)
    log_exito(f"Nueva OT: {ot_id_nuevo}")
    
    # PASO 9: CREAR EN BD (TRANSACCIÓN)
    log_paso("9️⃣", "CREAR OT, EVENTOS Y REPUESTOS (TRANSACCIÓN ATÓMICA)")
    
    dias_atras = 5
    duracion_dias = random.randint(2, 4)
    dt_apertura = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=dias_atras)
    dt_cierre = min(dt_apertura + timedelta(days=duracion_dias), datetime.now().replace(hour=23, minute=0, second=0, microsecond=0))
    fecha_apertura = dt_apertura.strftime("%Y-%m-%d %H:%M:%S")
    fecha_cierre = dt_cierre.strftime("%Y-%m-%d %H:%M:%S")    
    descripcion_ot = tipo_ot_config["descripcion_template"].format(sistema_en_riesgo)
        
    try:
        with engine.begin() as conn:
            
            # Crear OT
            print("   Paso 1/4: Crear OT...")
            conn.execute(
                text("""
                    INSERT INTO ordenes_trabajo 
                    (ot_id, activo_id, fecha_apertura, fecha_cierre, tipo_ot, descripcion_falla, 
                     costo_total_clp, odometro_km, horometro_h, taller_id, responsable, observaciones)
                    VALUES (:ot_id, :activo_id, :fecha_ap, :fecha_ci, :tipo, :descripcion, 
                            :costo, :odometro, :horometro, :taller_id, :responsable, :observaciones)
                """),
                {
                    "ot_id": ot_id_nuevo,
                    "activo_id": activo_id,
                    "fecha_ap": fecha_apertura,
                    "fecha_ci": fecha_cierre,
                    "tipo": tipo_ot,
                    "descripcion": descripcion_ot,
                    "costo": costo_ot,
                    "odometro": odometro_ot,
                    "horometro": horometro_ot,
                    "taller_id": taller_ot,
                    "responsable": responsable_ot,
                    "observaciones": observaciones_ot
                }
            )
            log_exito(f"OT creada: {ot_id_nuevo}")
            
            # Crear 2 eventos
            ids_evento = []
            for idx, (taxonomia_id, componente, desc) in enumerate(taxonomias[:2], 1):
                print(f"   Paso 2/4: Crear evento {idx}/2...")
                
                result = conn.execute(
                    text("""
                        INSERT INTO ot_falla_evento 
                        (ot_id, activo_id, taxonomia_id, tipo_mantenimiento)
                        VALUES (:ot_id, :activo_id, :taxonomia_id, :tipo_mto)
                        RETURNING id_evento
                    """),
                    {
                        "ot_id": ot_id_nuevo,
                        "activo_id": activo_id,
                        "taxonomia_id": taxonomia_id,
                        "tipo_mto": tipo_ot  # ✅ CORRECTO - Usar tipo_ot seleccionado, no sistema_en_riesgo
                    }
                )
                
                id_evento = result.fetchone()[0]
                ids_evento.append(id_evento)
                log_exito(f"Evento {idx} creado (ID: {id_evento})")
            
            # Crear repuestos para cada evento (DIFERENTES por variante)
            print(f"   Paso 3/4: Crear repuestos...")
            
            total_repuestos = 0
            for id_evento_idx, (taxonomia_id, componente, desc) in enumerate(taxonomias[:2], 1):
                
                # Buscar repuestos con VARIANTES para este componente
                componente_lower = componente.lower()
                
                if componente_lower in REPUESTOS_POR_COMPONENTE_VARIANTES:
                    # Usar variante diferente para cada evento (evento 1 → variante 0, evento 2 → variante 1)
                    variantes = REPUESTOS_POR_COMPONENTE_VARIANTES[componente_lower]
                    variante_idx = min(id_evento_idx - 1, len(variantes) - 1)  # Protege si hay menos variantes
                    repuestos_evento = variantes[variante_idx]
                    print(f"      Evento {id_evento_idx} ({componente}): Variante {variante_idx + 1} - {len(repuestos_evento)} repuestos")
                else:
                    # Fallback al sistema si no hay componente específico
                    repuestos_evento = REPUESTOS_POR_SISTEMA_FALLBACK.get(sistema_en_riesgo, [])
                    print(f"      Evento {id_evento_idx}: Usando fallback sistema - {len(repuestos_evento)} repuestos")
                
                # Insertar repuestos de este evento
                for repuesto in repuestos_evento:
                    conn.execute(
                        text("""
                            INSERT INTO repuestos_consumidos 
                            (ot_id, id_evento, sku, descripcion_repuesto, cantidad, fue_compra_urgencia)
                            VALUES (:ot_id, :id_evento, :sku, :descripcion, :cantidad, :urgencia)
                        """),
                        {
                            "ot_id": ot_id_nuevo,
                            "id_evento": ids_evento[id_evento_idx - 1],
                            "sku": repuesto["sku"],
                            "descripcion": repuesto["descripcion"],
                            "cantidad": repuesto["cantidad"],
                            "urgencia": repuesto["urgencia"]
                        }
                    )
                    total_repuestos += 1
            
            log_exito(f"Repuestos creados: {total_repuestos} (DIFERENTES por evento con variantes)")
            
            print(f"   Paso 4/4: Confirmar transacción...")
    
    except Exception as e:
        log_error(f"Error en transacción: {str(e)}\n🔄 Se revierte automáticamente")
    
    # PASO 10: Verificación
    log_paso("🔟", "VERIFICACIÓN FINAL")
    
    try:
        with engine.connect() as conn:
            ot_existe = conn.execute(
                text("SELECT COUNT(*) FROM ordenes_trabajo WHERE ot_id = :ot_id"),
                {"ot_id": ot_id_nuevo}
            ).fetchone()[0]
            
            eventos_count = conn.execute(
                text("SELECT COUNT(*) FROM ot_falla_evento WHERE ot_id = :ot_id"),
                {"ot_id": ot_id_nuevo}
            ).fetchone()[0]
            
            repuestos_count = conn.execute(
                text("SELECT COUNT(*) FROM repuestos_consumidos WHERE ot_id = :ot_id"),
                {"ot_id": ot_id_nuevo}
            ).fetchone()[0]
        
        if ot_existe and eventos_count == 2 and repuestos_count > 0:
            log_exito("Verificación exitosa")
        else:
            log_alerta(f"OT={ot_existe}, Eventos={eventos_count}, Repuestos={repuestos_count}")
    
    except Exception as e:
        log_error(f"Error en verificación: {str(e)}")
    
    # RESUMEN FINAL
    print("\n" + "=" * 80)
    print("✅ ORDEN DE TRABAJO CREADA EXITOSAMENTE")
    print("=" * 80)
    print(f"\n📊 RESUMEN:")
    print(f"   Patente:         {patente_bd} ({marca} {modelo})")
    print(f"   Activo ID:       {activo_id}")
    print(f"   OT_ID:           {ot_id_nuevo}")
    print(f"   Tipo OT:         {tipo_ot_config['icono']} {tipo_ot.upper()}")
    print(f"   Sistema:         {sistema_en_riesgo}")
    print(f"   Eventos:         2")
    print(f"   Repuestos:       {total_repuestos}")
    print(f"   Costo:           ${costo_ot:,.0f} CLP")
    print(f"   Descripción:     {descripcion_ot}")
    print("\n" + "=" * 80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelado por el usuario")
        sys.exit(0)
    except Exception as e:
        log_error(f"Error inesperado: {str(e)}")
