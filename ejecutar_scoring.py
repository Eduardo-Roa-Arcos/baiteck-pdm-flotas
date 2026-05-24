#!/usr/bin/env python3
"""
BAITECK - Pipeline de Scoring Diario
Sistema de mantenimiento predictivo para flotas
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

# ============================================================
# CONFIGURACIÓN INICIAL
# ============================================================

PROJECT_ROOT = Path(__file__).parent
MODELS_DIR = PROJECT_ROOT / "models"
LOGS_DIR = PROJECT_ROOT / "logs"

# Crear directorios
MODELS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Configurar logging ANTES de cualquier otra cosa
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOGS_DIR / 'scoring_diario.log'), mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# CLASE 1: ModeloFinder
# ============================================================

class ModeloFinder:
    """Auto-detecta el modelo XGBoost más reciente."""
    
    def __init__(self, modelos_dir: Path):
        self.modelos_dir = modelos_dir
        self.logger = logging.getLogger(__name__)
    
    def encontrar_todos_xgboost(self) -> list:
        """Busca todos los archivos de modelo XGBoost."""
        patrones = ['modelo_xgb*.joblib', 'xgboost*.joblib', 'modelo_*.joblib']
        archivos = []
        
        for patron in patrones:
            archivos.extend(self.modelos_dir.glob(patron))
        
        archivos = list(set(archivos))
        archivos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        return archivos
    
    def validar_modelo(self, ruta: Path) -> bool:
        """Valida si el modelo se puede cargar."""
        try:
            joblib.load(ruta)
            return True
        except Exception as e:
            self.logger.warning(f"Modelo inválido {ruta}: {e}")
            return False
    
    def obtener_modelo_reciente(self, modelo_personalizado: Optional[str] = None) -> Path:
        """Obtiene la ruta del modelo más reciente válido."""
        if modelo_personalizado:
            ruta = Path(modelo_personalizado)
            if ruta.exists() and self.validar_modelo(ruta):
                self.logger.info(f"✓ Usando modelo personalizado: {ruta.name}")
                return ruta
            else:
                raise FileNotFoundError(f"Modelo personalizado no válido: {modelo_personalizado}")
        
        modelos = self.encontrar_todos_xgboost()
        self.logger.info(f"Encontrados {len(modelos)} modelos XGBoost")
        
        for modelo in modelos:
            if self.validar_modelo(modelo):
                self.logger.info(f"✓ Modelo seleccionado: {modelo.name}")
                return modelo
        
        raise FileNotFoundError("No se encontró ningún modelo XGBoost válido")

# ============================================================
# CLASE 2: FleetPredictor
# ============================================================

class FleetPredictor:
    """Carga modelo y realiza predicciones."""
    
    def __init__(self, ruta_modelo: Path):
        self.ruta_modelo = ruta_modelo
        self.logger = logging.getLogger(__name__)
        self.artefacto = joblib.load(ruta_modelo)
        
        if isinstance(self.artefacto, dict):
            self.pipeline = self.artefacto.get('pipeline')
            self.feature_cols = self.artefacto.get('feature_cols', [])
            self.umbral = self.artefacto.get('umbral', 0.5)
        else:
            self.pipeline = self.artefacto
            self.feature_cols = []
            self.umbral = 0.5
        
        # Obtener el orden exacto de features del modelo
        if hasattr(self.pipeline, 'feature_names_in_'):
            self.feature_names_in = list(self.pipeline.feature_names_in_)
        else:
            self.feature_names_in = self.feature_cols
        
        self.logger.info(f"Modelo cargado: {len(self.feature_names_in)} features")
    
    def predecir(self, X: pd.DataFrame) -> pd.DataFrame:
        """Realiza predicciones."""
        self.logger.info(f"Realizando predicciones para {len(X)} activos")
        
        # Reordenar exactamente como espera el modelo
        X_modelo = X[self.feature_names_in].copy()
        
        # Convertir a float
        for col in X_modelo.columns:
            X_modelo[col] = pd.to_numeric(X_modelo[col], errors='coerce').fillna(-1).astype(float)
        
        self.logger.debug(f"Columnas para predicción (reordenadas): {list(X_modelo.columns)}")
        
        probs = self.pipeline.predict_proba(X_modelo)[:, 1]
        prioridades = self._asignar_prioridades(probs)
        
        resultado = pd.DataFrame({
            'probabilidad_falla': probs,
            'prediccion': (probs >= self.umbral).astype(int),
            'prioridad': prioridades
        })
        
        return resultado
    
    def _asignar_prioridades(self, probs: np.ndarray) -> list:
        """Asigna prioridades según probabilidad."""
        prioridades = []
        for p in probs:
            if p >= 0.85:
                prioridades.append('P1_critica')
            elif p >= 0.60:
                prioridades.append('P2_alta')
            elif p >= 0.30:
                prioridades.append('P3_media')
            else:
                prioridades.append('P4_baja')
        return prioridades

# ============================================================
# CLASE 3: FeatureGeneratorScoringDiario
# ============================================================

class FeatureGeneratorScoringDiario:
    """Genera features con barrera temporal."""
    
    def __init__(self, engine):
        self.engine = engine
        self.logger = logging.getLogger(__name__)
    
    def generar_features_fecha(self, fecha_corte: str, horizonte_dias: int = 30) -> pd.DataFrame:
        """
        Genera features para una fecha de corte específica.
        
        Features esperados por el modelo:
        ['edad_dias', 'ot_30d', 'corr_30d', 'ot_90d', 'corr_90d', 'ot_180d', 'corr_180d']
        """
        self.logger.info(f"Generando features para fecha de corte: {fecha_corte}")
        
        try:
            activos = pd.read_sql("SELECT * FROM activos", self.engine)
            ots = pd.read_sql("SELECT * FROM ordenes_trabajo ORDER BY activo_id, fecha_apertura", self.engine)
            
            self.logger.info(f"Cargados {len(activos)} activos y {len(ots)} OTs")
            
            # ========== NORMALIZAR FECHAS - REMOVER TODOS LOS TIMEZONES ==========
            fecha = pd.Timestamp(fecha_corte)
            
            # Activos
            activos["fecha_alta_flota"] = pd.to_datetime(activos["fecha_alta_flota"], errors="coerce")
            if activos["fecha_alta_flota"].dt.tz is not None:
                activos["fecha_alta_flota"] = activos["fecha_alta_flota"].dt.tz_localize(None)
            
            # OTs
            ots["fecha_apertura"] = pd.to_datetime(ots["fecha_apertura"], errors="coerce")
            if ots["fecha_apertura"].dt.tz is not None:
                ots["fecha_apertura"] = ots["fecha_apertura"].dt.tz_localize(None)
            
            # ========== FIN NORMALIZACIÓN ==========
            
            ots_pasado = ots[ots["fecha_apertura"] < fecha].copy()
            self.logger.info(f"OTs para análisis: {len(ots_pasado)}")
            
            # Inicializar features
            features = activos[['activo_id']].copy()
            
            # ========== GENERAR FEATURES EXACTOS QUE ESPERA EL MODELO ==========
            
            # 1. edad_dias
            features['edad_dias'] = (fecha - activos['fecha_alta_flota']).dt.days
            
            # Ventanas de tiempo
            hace_30d = fecha - timedelta(days=30)
            hace_90d = fecha - timedelta(days=90)
            hace_180d = fecha - timedelta(days=180)
            
            # 2, 3. ot_30d, corr_30d
            features['ot_30d'] = 0
            features['corr_30d'] = 0
            
            # 4, 5. ot_90d, corr_90d
            features['ot_90d'] = 0
            features['corr_90d'] = 0
            
            # 6, 7. ot_180d, corr_180d
            features['ot_180d'] = 0
            features['corr_180d'] = 0
            
            # Llenar los conteos
            for activo_id in features['activo_id']:
                ots_activo = ots_pasado[ots_pasado['activo_id'] == activo_id]
                
                # OTs totales
                ots_30d = ots_activo[ots_activo['fecha_apertura'] >= hace_30d]
                ots_90d = ots_activo[ots_activo['fecha_apertura'] >= hace_90d]
                ots_180d = ots_activo[ots_activo['fecha_apertura'] >= hace_180d]
                
                features.loc[features['activo_id'] == activo_id, 'ot_30d'] = len(ots_30d)
                features.loc[features['activo_id'] == activo_id, 'ot_90d'] = len(ots_90d)
                features.loc[features['activo_id'] == activo_id, 'ot_180d'] = len(ots_180d)
                
                # OTs correctivas
                ots_corr_30d = ots_30d[ots_30d['tipo_ot'] == 'correctiva']
                ots_corr_90d = ots_90d[ots_90d['tipo_ot'] == 'correctiva']
                ots_corr_180d = ots_180d[ots_180d['tipo_ot'] == 'correctiva']
                
                features.loc[features['activo_id'] == activo_id, 'corr_30d'] = len(ots_corr_30d)
                features.loc[features['activo_id'] == activo_id, 'corr_90d'] = len(ots_corr_90d)
                features.loc[features['activo_id'] == activo_id, 'corr_180d'] = len(ots_corr_180d)
            
            # Llenar NaN con -1
            features = features.fillna(-1)
            
            self.logger.info(f"Features generados: {features.shape}")
            self.logger.debug(f"Columnas: {list(features.columns)}")
            
            return features
            
        except Exception as e:
            self.logger.error(f"Error generando features: {e}", exc_info=True)
            raise

# ============================================================
# CLASE 4: ScoringResultadosPersistor
# ============================================================

class ScoringResultadosPersistor:
    """Persiste resultados en Supabase."""
    
    def __init__(self, engine):
        self.engine = engine
        self.logger = logging.getLogger(__name__)
    
    def guardar_predicciones(self, features: pd.DataFrame, predicciones: pd.DataFrame, 
                            fecha_scoring: str, modelo_version: str, horizonte_dias: int = 30) -> bool:
        """Guarda predicciones en tabla scoring_resultados."""
        
        try:
            datos = pd.concat([features[['activo_id']], predicciones], axis=1)
            datos['fecha_scoring'] = pd.Timestamp(fecha_scoring)
            datos['horizonte_dias'] = horizonte_dias
            datos['modelo_version'] = modelo_version
            datos['created_at'] = datetime.now()
            
            with self.engine.connect() as conn:
                # Primero: borrar registros anteriores de la misma fecha
                delete_query = text("""
                    DELETE FROM scoring_resultados 
                    WHERE fecha_scoring = :fecha_scoring 
                    AND horizonte_dias = :horizonte_dias
                """)
                conn.execute(delete_query, {
                    'fecha_scoring': pd.Timestamp(fecha_scoring),
                    'horizonte_dias': horizonte_dias
                })
                self.logger.info(f"Registros previos borrados para {fecha_scoring}")
                
                # Luego: insertar nuevos registros
                for _, row in datos.iterrows():
                    query = text("""
                        INSERT INTO scoring_resultados 
                        (activo_id, fecha_scoring, horizonte_dias, probabilidad_falla, 
                         prediccion, prioridad, modelo_version, created_at)
                        VALUES (:activo_id, :fecha_scoring, :horizonte_dias, :probabilidad_falla,
                                :prediccion, :prioridad, :modelo_version, :created_at)
                    """)
                    conn.execute(query, {
                        'activo_id': str(row['activo_id']),
                        'fecha_scoring': row['fecha_scoring'],
                        'horizonte_dias': int(row['horizonte_dias']),
                        'probabilidad_falla': float(row['probabilidad_falla']),
                        'prediccion': int(row['prediccion']),
                        'prioridad': row['prioridad'],
                        'modelo_version': modelo_version,
                        'created_at': row['created_at']
                    })
                conn.commit()
            
            self.logger.info(f"✓ {len(datos)} predicciones guardadas")
            return True
            
        except Exception as e:
            self.logger.error(f"Error guardando predicciones: {e}", exc_info=True)
            return False
    
    def verificar_predicciones(self, fecha_scoring: str) -> pd.DataFrame:
        """Verifica predicciones guardadas."""
        try:
            query = text("""
                SELECT activo_id, probabilidad_falla, prioridad 
                FROM scoring_resultados 
                WHERE fecha_scoring = :fecha_scoring
                ORDER BY probabilidad_falla DESC
                LIMIT 10
            """)
            resultados = pd.read_sql(query, self.engine, params={'fecha_scoring': fecha_scoring})
            
            self.logger.info("Top 10 activos en riesgo:")
            for _, row in resultados.iterrows():
                self.logger.info(f"  Activo {row['activo_id']}: {row['prioridad']} ({row['probabilidad_falla']:.2%})")
            
            return resultados
            
        except Exception as e:
            self.logger.error(f"Error verificando predicciones: {e}", exc_info=True)
            return pd.DataFrame()

# ============================================================
# CLASE 5: ScoringDiarioPipeline
# ============================================================

class ScoringDiarioPipeline:
    """Orquestador principal."""
    
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.logger = logging.getLogger(__name__)
    
    def ejecutar(self, fecha_scoring: Optional[str] = None, 
                modelo_personalizado: Optional[str] = None,
                horizonte_dias: int = 30) -> bool:
        """Ejecuta el pipeline completo."""
        
        if not fecha_scoring:
            fecha_scoring = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        self.logger.info("="*70)
        self.logger.info("BAITECK - SCORING BATCH DIARIO")
        self.logger.info("="*70)
        self.logger.info(f"Fecha de scoring: {fecha_scoring}")
        
        try:
            self.logger.info("[1] Detectando modelo XGBoost...")
            finder = ModeloFinder(MODELS_DIR)
            ruta_modelo = finder.obtener_modelo_reciente(modelo_personalizado)
            modelo_version = ruta_modelo.stem
            
            self.logger.info("[2] Generando features...")
            feature_gen = FeatureGeneratorScoringDiario(self.engine)
            features = feature_gen.generar_features_fecha(fecha_scoring, horizonte_dias)
            
            self.logger.info("[3] Cargando predictor...")
            predictor = FleetPredictor(ruta_modelo)
            
            self.logger.info("[4] Realizando predicciones...")
            predicciones = predictor.predecir(features)
            
            self.logger.info("[5] Guardando resultados...")
            persistor = ScoringResultadosPersistor(self.engine)
            exito = persistor.guardar_predicciones(
                features, predicciones, fecha_scoring, modelo_version, horizonte_dias
            )
            
            if exito:
                self.logger.info("[6] Verificando resultados...")
                persistor.verificar_predicciones(fecha_scoring)
                self.logger.info("="*70)
                self.logger.info("✓ Pipeline completado exitosamente")
                self.logger.info("="*70)
                return True
            else:
                return False
        
        except Exception as e:
            self.logger.error(f"✗ Error en pipeline: {e}", exc_info=True)
            return False

# ============================================================
# MAIN
# ============================================================


if __name__ == "__main__":
    import argparse
    import os
    from dotenv import load_dotenv
    from pathlib import Path
    
    # Cargar variables desde .env.local o .env (lo que exista)
    proyecto_root = Path(__file__).parent
    env_local = proyecto_root / ".env.local"
    env_default = proyecto_root / ".env"
    
    if env_local.exists():
        load_dotenv(dotenv_path=env_local, override=True)
        print(f"✓ Variables cargadas desde {env_local.name}")
    elif env_default.exists():
        load_dotenv(dotenv_path=env_default, override=True)
        print(f"✓ Variables cargadas desde {env_default.name}")
    else:
        logger.error(f"No se encontró ni .env.local ni .env en {proyecto_root}")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description="BAITECK - Scoring Diario")
    parser.add_argument('--fecha', type=str, help='Fecha (YYYY-MM-DD), default: ayer')
    parser.add_argument('--modelo', type=str, help='Ruta a modelo custom')
    parser.add_argument('--log-level', default='INFO', help='Nivel de logging')
    
    args = parser.parse_args()
    logging.getLogger().setLevel(args.log_level.upper())
    
    db_url = os.getenv('DATABASE_URL', '')
    
    if not db_url:
        logger.error("DATABASE_URL no configurada")
        sys.exit(1)
    
    pipeline = ScoringDiarioPipeline(db_url)
    exito = pipeline.ejecutar(args.fecha, args.modelo)
    
    sys.exit(0 if exito else 1)
