import pandas as pd
import joblib
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

class Predictor:
    def __init__(self):
        self.model = None
        self.pipeline = None
        self.feature_cols = None
        self.model_metadata = None
        success = self.load_active_model()
        if not success:
            raise RuntimeError("No se pudo cargar el modelo")
    
    def load_active_model(self) -> bool:
        conn = None
        try:
            database_url = os.getenv("DATABASE_URL")
            if not database_url:
                raise ValueError("DATABASE_URL no en .env")
            
            conn = psycopg2.connect(database_url)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            query = "SELECT modelo_id, version, nombre_archivo FROM modelos_registro ORDER BY fecha_creacion DESC LIMIT 1"
            cursor.execute(query)
            result = cursor.fetchone()
            cursor.close()
            
            if not result:
                print("No hay modelo registrado")
                return False
            
            self.model_metadata = dict(result)
            model_path = f"models/{result['nombre_archivo']}"
            
            if not os.path.exists(model_path):
                print(f"No existe: {model_path}")
                return False
            
            artifact = joblib.load(model_path)
            print(f"Tipo de artifact: {type(artifact)}")
            
            if isinstance(artifact, dict):
                self.model = artifact.get("model")
                self.pipeline = artifact.get("pipeline")
                self.feature_cols = artifact.get("feature_cols")
            else:
                self.model = artifact
                self.pipeline = None
                self.feature_cols = None
            
            if self.model is None:
                print("Modelo es None")
                return False
            
            if self.feature_cols is None:
                print("feature_cols es None, usando default")
                self.feature_cols = ['edad_dias', 'ot_30d', 'ot_90d', 'ot_180d', 'corr_30d', 'corr_90d', 'corr_180d']
            
            print(f"✅ Modelo: {result['version']}")
            return True
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if conn:
                conn.close()
    
    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if self.model is None:
            raise ValueError("Modelo no cargado")
        
        missing_cols = set(self.feature_cols) - set(X.columns)
        if missing_cols:
            print(f"Aviso: faltan columnas {missing_cols}, usando las disponibles")
        
        X_ordered = X[self.feature_cols].copy()
        
        if self.pipeline is not None:
            X_processed = self.pipeline.transform(X_ordered)
        else:
            X_processed = X_ordered
        
        y_pred = self.model.predict(X_processed)
        
        try:
            y_pred_proba = self.model.predict_proba(X_processed)[:, 1]
        except:
            y_pred_proba = y_pred.astype(float)
        
        return pd.DataFrame({
            'activo_id': X['activo_id'],
            'probabilidades': y_pred_proba,
            'predicciones': y_pred,
            'modelo_id': self.model_metadata['modelo_id'],
            'version': self.model_metadata['version']
        })
