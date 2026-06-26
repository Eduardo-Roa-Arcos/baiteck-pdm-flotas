#!/bin/bash
# ============================================================================
# EJECUTAR PIPELINE DIARIO
# ============================================================================
# Ejecución: Todos los días a las 2:00 AM
# 
# Flujo:
# 1. crear_disponibilidad_diaria_INCREMENTAL.py
# 2. ejecutar_scoring.py (PRIMERO: genera scoring del día con ajuste h7→h30)
# 3. calcular_paneles.py (usa scoring nuevo para Vista 1, 2 y 3)
# 4. 03_demanda_p1p2.py (usa scoring nuevo para repuestos críticos)
# 5. actualizar_repuestos_diario.py
# 6. generar_plan_repuestos_financiero.py
#
# Logs: ~/.baiteck/logs/pipeline-diario-YYYY-MM-DD.log

set -e

# Configuración
PROJECT_DIR="/Users/eduardoroa/baiteck-pdm-flotas"
LOGS_DIR="${HOME}/.baiteck/logs"
LOG_FILE="${LOGS_DIR}/pipeline-diario-$(date +%Y-%m-%d).log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
UV_BIN="/Users/eduardoroa/.local/bin/uv"

# Crear directorio de logs si no existe
mkdir -p "$LOGS_DIR"

# Función para loguear
log() {
    echo "[${TIMESTAMP}] $1" | tee -a "$LOG_FILE"
}

# Función para ejecutar script Python
ejecutar_script() {
    local script=$1
    local descripcion=$2
    
    log ""
    log "=========================================================================="
    log "▶️  $descripcion"
    log "=========================================================================="
    
    cd "$PROJECT_DIR"
    
    if $UV_BIN run python "$script" >> "$LOG_FILE" 2>&1; then
        log "✅ $descripcion completado"
    else
        log "❌ ERROR en $descripcion"
        log "Abortando pipeline"
        exit 1
    fi
}

# Inicio
log "🚀 INICIO PIPELINE DIARIO"
log "Proyecto: $PROJECT_DIR"

# Ejecutar scripts en orden
ejecutar_script "crear_disponibilidad_diaria_INCREMENTAL.py" "Disponibilidad diaria"
ejecutar_script "ejecutar_scoring.py" "Ejecutar scoring"
ejecutar_script "calcular_paneles.py" "Calcular paneles"
ejecutar_script "03_demanda_p1p2.py" "Calcular demanda P1/P2"
ejecutar_script "actualizar_repuestos_diario.py" "Actualizar repuestos"
ejecutar_script "generar_plan_repuestos_financiero.py" "Generar plan repuestos"

# Final
log ""
log "=========================================================================="
log "✅ PIPELINE COMPLETADO EXITOSAMENTE"
log "=========================================================================="
log "Log guardado en: $LOG_FILE"
