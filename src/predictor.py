# src/models/predictor.py
"""
Módulo de inferencia pura - carga modelo y realiza predicciones
Separación de responsabilidades: solo predicción, sin orquestación
"""
import pandas as pd
import joblib
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from typing import Dict, Any

load_dotenv()

class Predictor:
    """Predictor - módulo de inferencia pura"""

    def __init__(self, engine=None):
        """
        Args:
            engine: SQLAlchemy engine (usa conexión directa si es None)
        """
        self.model = None
        self.pipeline = None
        self.feature_cols = None
        self.model_metadata = None
        self.engine = engine

    def load_active_model(self) -> bool:
        """
        Carga el modelo activo (es_activo=TRUE) desde modelos_registro

        Returns:
            bool: True si se cargó exitosamente

        Raises:
            ValueError: Si no hay modelo activo o modelo no existe en disco
        """
        conn = None
        try:
            # Conectar a Supabase
            conn = psycopg2.connect(
                host=os.getenv("SUPABASE_HOST"),
                database=os.getenv("SUPABASE_DATABASE"),
                user=os.getenv("SUPABASE_USER"),
                password=os.getenv("SUPABASE_PASSWORD"),
                port=5432,
                sslmode="require"
            )
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Obtener modelo activo más reciente
            query = """
                SELECT 
                    modelo_id,
                    version,
                    nombre_archivo,
                    hiperparametros,
                    auc_score,
                    precision,
                    recall,
                    f1_score
                FROM modelos_registro
                WHERE es_activo = TRUE
                ORDER BY fecha_creacion DESC
                LIMIT 1
            """
            cursor.execute(query)
            result = cursor.fetchone()
            cursor.close()

            if not result:
                raise ValueError("❌ No hay modelo activo disponible en modelos_registro")

            self.model_metadata = dict(result)

            # Cargar archivo del modelo desde disco
            model_path = f"models/{self.model_metadata['nombre_archivo']}"
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"❌ Modelo no encontrado en {model_path}")

            artifact = joblib.load(model_path)
            self.pipeline = artifact.get("pipeline")
            self.model = artifact.get("model")
            self.feature_cols = artifact.get("feature_cols")

            if not all([self.pipeline, self.model, self.feature_cols]):
                raise ValueError("❌ Artifact de modelo incompleto (falta pipeline, model o feature_cols)")

            print(f"✅ Modelo cargado: {self.model_metadata['version']}")
            print(f"   AUC: {self.model_metadata['auc_score']:.4f}")
            print(f"   Features esperadas: {len(self.feature_cols)}")

            return True

        except Exception as e:
            print(f"❌ Error cargando modelo: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def predict(self, X: pd.DataFrame) -> Dict[str, Any]:
        """
        Realiza predicciones en batch

        Args:
            X (pd.DataFrame): Features con columnas en self.feature_cols

        Returns:
            Dict con:
                - probabilidades: array de P(falla) [0,1]
                - predicciones: array de 0/1
                - modelo_id: ID del modelo
                - modelo_version: versión del modelo
        """
        if self.model is None or self.pipeline is None:
            raise ValueError("❌ Modelo no cargado. Llama load_active_model() primero")

        try:
            # Validar que X tiene las columnas correctas
            missing_cols = set(self.feature_cols) - set(X.columns)
            if missing_cols:
                raise ValueError(f"❌ Faltan columnas: {missing_cols}")

            # Asegurar orden de columnas
            X_ordered = X[self.feature_cols].copy()

            # Aplicar pipeline de preprocesamiento (imputación, escalado)
            X_processed = self.pipeline.transform(X_ordered)

            # Predicción
            y_pred = self.model.predict(X_processed)
            try:
                y_pred_proba = self.model.predict_proba(X_processed)[:, 1]
            except IndexError:
                # Si test set tiene solo una clase, use predicciones como probabilidades
                y_pred_proba = y_pred.astype(float)

            return {
                'probabilidades': y_pred_proba,
                'predicciones': y_pred,
                'modelo_id': self.model_metadata['modelo_id'],
                'modelo_version': self.model_metadata['version']
            }

        except Exception as e:
            print(f"❌ Error en predicción: {e}")
            raise
