#!/bin/bash
# ============================================================================
# CALCULAR CONSUMO HISTÓRICO (SEMANAL)
# ============================================================================
# Ejecución: Domingos a las 11:00 PM
# 
# Flujo:
# 1. calcular_consumo_historico.py
#
# Nota: 03_demanda_p1p2.py se ejecuta en el script diario después del scoring,
#       así se recalcula con datos más actualizados.
#
# Logs: ~/.baiteck/logs/consumo-historico-YYYY-MM-DD.log

set -e

# Configuración
PROJECT_DIR="/Users/eduardoroa/baiteck-pdm-flotas"
LOGS_DIR="${HOME}/.baiteck/logs"
LOG_FILE="${LOGS_DIR}/consumo-historico-$(date +%Y-%m-%d).log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
UV_BIN="/Users/eduardoroa/.local/bin/uv"

# Crear directorio de logs si no existe
mkdir -p "$LOGS_DIR"

# Función para loguear
log() {
    echo "[${TIMESTAMP}] $1" | tee -a "$LOG_FILE"
}

# Inicio
log "🚀 CÁLCULO CONSUMO HISTÓRICO (SEMANAL)"
log "Proyecto: $PROJECT_DIR"

cd "$PROJECT_DIR"

log ""
log "=========================================================================="
log "▶️  Calculando consumo histórico (últimos 180 días)..."
log "=========================================================================="

if $UV_BIN run python calcular_consumo_historico.py >> "$LOG_FILE" 2>&1; then
    log "✅ Consumo histórico actualizado"
else
    log "❌ ERROR AL CALCULAR CONSUMO HISTÓRICO"
    log "=========================================================================="
    exit 1
fi

log ""
log "=========================================================================="
log "✅ CÁLCULO SEMANAL COMPLETADO"
log "=========================================================================="
log "Log guardado en: $LOG_FILE"
