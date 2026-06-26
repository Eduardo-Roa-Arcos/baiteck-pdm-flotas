#!/usr/bin/env python3
"""
🌙 PIPELINE NIGHTLY - ORQUESTADOR MAESTRO
==========================================

Ejecuta el flujo completo nocturno en orden:
  1. Actualizar disponibilidad con nuevas OT
  2. Ejecutar scoring (modelo predictivo)
  3. Calcular métricas del dashboard
  4. Generar plan de repuestos (opcional)

USO:
  uv run python ejecutar_nightly.py                    # Ejecuta los 4 pasos
  uv run python ejecutar_nightly.py --sin-repuestos    # Omite plan de repuestos
  uv run python ejecutar_nightly.py --solo-scoring     # Solo scoring (debug)

Este script:
- Ejecuta pasos secuencialmente
- Para si alguno falla (no continúa con datos inconsistentes)
- Registra timestamps y tiempos de ejecución
- Genera resumen final

Salida de logs: nightly_pipeline.log
"""

import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

PROJECT_ROOT = Path(__file__).parent
LOG_FILE = PROJECT_ROOT / "nightly_pipeline.log"

# Pasos del pipeline (script, descripción, ejecutar_por_defecto)
PIPELINE_STEPS = [
    ("crear_disponibilidad_diaria_INCREMENTAL.py", "⚡ Actualizar disponibilidad", True),
    ("ejecutar_scoring.py", "🎯 Ejecutar scoring (predicciones)", True),
    ("calcular_paneles.py", "📊 Calcular métricas dashboard", True),
    ("generar_plan_repuestos_financiero.py", "💰 Generar plan de repuestos", True),
]

# ============================================================================
# FUNCIONES
# ============================================================================

def log_message(msg: str, level: str = "INFO"):
    """Escribe mensaje en log y stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {level}: {msg}"
    print(formatted)
    with open(LOG_FILE, "a") as f:
        f.write(formatted + "\n")


def execute_step(script_path: str, description: str) -> tuple[bool, float]:
    """
    Ejecuta un paso del pipeline.
    Retorna (success, tiempo_segundos).
    """
    log_message(f"\n{'='*70}")
    log_message(description)
    log_message(f"{'='*70}")
    log_message(f"Ejecutando: {script_path}")
    
    start_time = time.time()
    
    try:
        # Ejecutar con uv run python
        result = subprocess.run(
            ["uv", "run", "python", str(script_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300  # 5 minutos máx por paso
        )
        
        elapsed = time.time() - start_time
        
        # Registrar stdout + stderr en log
        if result.stdout:
            log_message(f"\nSTDOUT:\n{result.stdout}")
        if result.stderr:
            log_message(f"\nSTDERR:\n{result.stderr}")
        
        if result.returncode == 0:
            log_message(f"✅ {description} - EXITOSO ({elapsed:.2f}s)", "SUCCESS")
            return True, elapsed
        else:
            log_message(f"❌ {description} - FALLÓ (código {result.returncode})", "ERROR")
            return False, elapsed
            
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        log_message(f"❌ {description} - TIMEOUT (>5 min)", "ERROR")
        return False, elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        log_message(f"❌ {description} - ERROR: {e}", "ERROR")
        return False, elapsed


def parse_arguments() -> dict:
    """Parsea argumentos de línea de comandos."""
    args = {
        "skip_repuestos": "--sin-repuestos" in sys.argv,
        "solo_scoring": "--solo-scoring" in sys.argv,
        "help": "--help" in sys.argv or "-h" in sys.argv,
    }
    
    if args["help"]:
        print("""
🌙 PIPELINE NIGHTLY - BAITECK PDM-FLOTAS
=========================================

USO:
  uv run python ejecutar_nightly.py                    # Ejecuta los 4 pasos
  uv run python ejecutar_nightly.py --sin-repuestos    # Omite plan de repuestos
  uv run python ejecutar_nightly.py --solo-scoring     # Solo scoring (debug)
  uv run python ejecutar_nightly.py --help             # Este mensaje

OPCIONES:
  --sin-repuestos     Omite paso 4 (generar plan de repuestos)
  --solo-scoring      Ejecuta solo pasos 1-2 (disponibilidad + scoring)
  --help, -h          Muestra esta ayuda
        """)
        sys.exit(0)
    
    return args


# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_arguments()
    
    # Banner inicial
    print("\n" + "="*70)
    print("🌙 PIPELINE NIGHTLY - BAITECK PDM-FLOTAS")
    print("="*70)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    log_message("="*70)
    log_message("🌙 PIPELINE NIGHTLY INICIADO")
    log_message("="*70)
    
    # Determinar pasos a ejecutar
    if args["solo_scoring"]:
        pasos = PIPELINE_STEPS[:2]  # Solo disponibilidad + scoring
        log_message("Modo: SOLO SCORING (pasos 1-2)")
    elif args["skip_repuestos"]:
        pasos = PIPELINE_STEPS[:3]  # Omite repuestos
        log_message("Modo: SIN PLAN DE REPUESTOS (pasos 1-3)")
    else:
        pasos = PIPELINE_STEPS
        log_message("Modo: PIPELINE COMPLETO (pasos 1-4)")
    
    # Ejecutar pasos
    resultados = []
    tiempo_total_inicio = time.time()
    
    for script, descripcion, _ in pasos:
        success, elapsed = execute_step(script, descripcion)
        resultados.append((descripcion, success, elapsed))
        
        if not success:
            log_message(f"\n⚠️ PIPELINE DETENIDO - Fallo en: {descripcion}", "WARNING")
            print(f"\n❌ PIPELINE FALLÓ")
            print(f"   Paso fallido: {descripcion}")
            print(f"   Revisa logs en: {LOG_FILE}")
            return 1
    
    tiempo_total = time.time() - tiempo_total_inicio
    
    # Resumen final
    log_message(f"\n{'='*70}")
    log_message("📊 RESUMEN FINAL")
    log_message(f"{'='*70}")
    
    for descripcion, success, elapsed in resultados:
        estado = "✅ EXITOSO" if success else "❌ FALLÓ"
        log_message(f"{estado:12} {descripcion:40} ({elapsed:6.2f}s)")
    
    log_message(f"\n⏱️ Tiempo total: {tiempo_total:.2f} segundos")
    log_message(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_message("="*70)
    log_message("✅ PIPELINE NIGHTLY COMPLETADO EXITOSAMENTE\n")
    
    # Banner final
    print(f"\n{'='*70}")
    print("✅ PIPELINE NIGHTLY COMPLETADO")
    print("="*70)
    print(f"\n📊 Resumen:")
    for descripcion, success, elapsed in resultados:
        emoji = "✅" if success else "❌"
        print(f"  {emoji} {descripcion} ({elapsed:.2f}s)")
    print(f"\n⏱️ Tiempo total: {tiempo_total:.2f} segundos")
    print(f"\n📋 Logs guardados en: {LOG_FILE}")
    print(f"\n🎉 El dashboard está actualizado con:")
    print(f"   • Disponibilidad actualizada (últimas OT)")
    print(f"   • Predicciones frescas (P1/P2/P3/P4)")
    print(f"   • Métricas y tendencias del dashboard")
    if not args["skip_repuestos"]:
        print(f"   • Plan de repuestos priorizado")
    print(f"\n{'='*70}\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
