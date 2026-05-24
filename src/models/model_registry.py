# src/models/model_registry.py
"""
Módulo para registrar modelos entrenados en Supabase
"""

import json
from datetime import datetime
from src.db import engine
from sqlalchemy import text
import uuid


class ModelRegistry:
    """
    Registra modelos entrenados en la tabla modelos_registro de Supabase
    """
    
    def __init__(self):
        self.engine = engine
    
    def registrar_modelo(self, version: str, nombre_archivo: str, metricas: dict,
                        hiperparametros: dict, n_samples: int, n_features: int,
                        features: list, entrenado_por: str, notas: str = ""):
        """
        Registra un modelo en la BD
        
        Args:
            version: versión del modelo (ej: "v1.0_rf")
            nombre_archivo: nombre del archivo guardado
            metricas: dict con auc, precision, recall, f1
            hiperparametros: dict con parámetros del modelo
            n_samples: número de muestras de entrenamiento
            n_features: número de features
            features: lista de nombres de features
            entrenado_por: quién entrenó (ej: "sistema_rf")
            notas: notas adicionales
        
        Returns:
            modelo_id (UUID)
        """
        try:
            with self.engine.connect() as conn:
                # Generar ID único
                modelo_id = str(uuid.uuid4())
                
                # Preparar query
                query = text("""
                    INSERT INTO modelos_registro 
                    (modelo_id, version, nombre_archivo, fecha_entrenamiento, 
                     auc_score, precision, recall, f1_score, 
                     n_samples_train, n_features, features_utilizadas, 
                     hiperparametros, estado, es_activo, entrenado_por, notas, created_at)
                    VALUES 
                    (:modelo_id, :version, :nombre_archivo, NOW(),
                     :auc_score, :precision, :recall, :f1_score,
                     :n_samples, :n_features, :features,
                     :hiperparametros, :estado, :es_activo, :entrenado_por, :notas, NOW())
                """)
                
                # Ejecutar
                conn.execute(query, {
                    'modelo_id': modelo_id,
                    'version': version,
                    'nombre_archivo': nombre_archivo,
                    'auc_score': metricas.get('auc', 0.0),
                    'precision': metricas.get('precision', 0.0),
                    'recall': metricas.get('recall', 0.0),
                    'f1_score': metricas.get('f1', 0.0),
                    'n_samples': n_samples,
                    'n_features': n_features,
                    'features': ','.join([str(f) for f in features]),
                    'hiperparametros': json.dumps(hiperparametros),
                    'estado': 'entrenado',
                    'es_activo': False,  # No activar automáticamente
                    'entrenado_por': entrenado_por,
                    'notas': notas
                })
                
                conn.commit()
                
                print(f"   ✅ Modelo registrado con ID: {modelo_id}")
                return modelo_id
        
        except Exception as e:
            print(f"   ❌ Error al registrar: {e}")
            return None
    
    def activar_modelo(self, modelo_id: str):
        """
        Activa un modelo como el modelo productivo
        (desactiva otros)
        """
        try:
            with self.engine.connect() as conn:
                # Desactivar todos
                conn.execute(text("UPDATE modelos_registro SET es_activo = FALSE"))
                
                # Activar el especificado
                query = text("UPDATE modelos_registro SET es_activo = TRUE WHERE modelo_id = :modelo_id")
                conn.execute(query, {'modelo_id': modelo_id})
                
                conn.commit()
                print(f"   ✅ Modelo {modelo_id} activado")
        
        except Exception as e:
            print(f"   ❌ Error al activar: {e}")
    
    def obtener_modelo_activo(self):
        """
        Obtiene el modelo actualmente activo
        """
        try:
            query = "SELECT * FROM modelos_registro WHERE es_activo = TRUE ORDER BY fecha_entrenamiento DESC LIMIT 1"
            df = pd.read_sql(query, self.engine)
            
            if len(df) > 0:
                return df.iloc[0].to_dict()
            else:
                return None
        
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return None
    
    def listar_modelos(self):
        """
        Lista todos los modelos registrados
        """
        try:
            query = "SELECT modelo_id, version, fecha_entrenamiento, auc_score, es_activo FROM modelos_registro ORDER BY fecha_entrenamiento DESC"
            df = pd.read_sql(query, self.engine)
            return df
        
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return None
