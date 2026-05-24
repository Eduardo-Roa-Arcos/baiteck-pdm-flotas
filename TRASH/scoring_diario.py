# scoring_diario.py (VERSIÓN CORREGIDA)

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from datetime import datetime
import uuid
from typing import Optional

from predictor import Predictor

load_dotenv()

class ScoringDiario:
    """Pipeline scoring diario"""

    def __init__(self):
        self.predictor = Predictor()
        self.conn = None

    def conectar_db(self) -> bool:
        """Conecta a Supabase usando el connection string correcto"""
        try:
            # IMPORTANTE: usar el mismo formato que main.py usa
            database_url = os.getenv("DATABASE_URL")

            if not database_url:
                raise ValueError("❌ DATABASE_URL no está en .env")

            # Conexión directa usando DATABASE_URL
            self.conn = psycopg2.connect(database_url)

            print("✅ Conectado a Supabase")
            return True
        except Exception as e:
            print(f"❌ Error conexión: {e}")
            raise

    def generar_features_scoring(self, fecha_scoring: str, horizonte_dias: int = 30) -> pd.DataFrame:
        """Genera features para scoring"""
        try:
            print(f"   🔧 Generando features para {fecha_scoring}...")

            # Importar aquí para evitar circular imports
            from main import construir_features

            # Usar construir_features existente
            df_panel = construir_features(fecha_corte_str=fecha_scoring, horizonte_dias=horizonte_dias)

            # Columnas que necesitamos (sin target)
            feature_cols = [
                'activo_id', 'fecha_corte', 'horizonte_dias',
                'edad_dias', 'ot_30d', 'ot_90d', 'ot_180d', 
                'corr_30d', 'corr_90d', 'corr_180d'
            ]

            df_features = df_panel[feature_cols].copy()

            print(f"   ✅ {len(df_features)} registros generados")

            return df_features

        except Exception as e:
            print(f"❌ Error features: {e}")
            raise

    def registrar_predicciones(self, predicciones: dict, df_features: pd.DataFrame, 
                               fecha_scoring: str, horizonte_dias: int) -> int:
        """Escribe predicciones en Supabase"""
        cursor = None
        count = 0
        try:
            cursor = self.conn.cursor()

            def asignar_prioridad(p: float) -> str:
                if p >= 0.85:
                    return "P1_critica"
                elif p >= 0.65:
                    return "P2_alta"
                elif p >= 0.40:
                    return "P3_media"
                else:
                    return "P4_baja"

            insert_query = """
                INSERT INTO scoring_resultados 
                (scoring_id, activo_id, fecha_scoring, horizonte_dias, 
                 probabilidad_falla, prediccion, prioridad, modelo_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """

            for idx, row in df_features.iterrows():
                try:
                    scoring_id = str(uuid.uuid4())
                    prob = float(predicciones['probabilidades'][idx])
                    pred = int(predicciones['predicciones'][idx])

                    cursor.execute(insert_query, (
                        scoring_id,
                        row['activo_id'],
                        fecha_scoring,
                        horizonte_dias,
                        prob,
                        pred,
                        asignar_prioridad(prob),
                        predicciones['modelo_version']
                    ))
                    count += 1
                except Exception as e:
                    print(f"⚠️  Error {row['activo_id']}: {e}")
                    continue

            self.conn.commit()
            print(f"   ✅ {count} predicciones registradas")

            return count

        except Exception as e:
            if self.conn:
                self.conn.rollback()
            print(f"❌ Error registro: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def ejecutar(self, fecha_scoring: Optional[str] = None, horizonte_dias: int = 30) -> bool:
        """Ejecuta pipeline completo"""
        try:
            if fecha_scoring is None:
                fecha_scoring = datetime.now().strftime("%Y-%m-%d")

            print(f"\n{'='*70}")
            print(f"🚀 SCORING DIARIO - {fecha_scoring}")
            print(f"{'='*70}\n")

            print("1️⃣  Conectando...")
            self.conectar_db()

            print("\n2️⃣  Cargando modelo...")
            self.predictor.load_active_model()

            print("\n3️⃣  Generando features...")
            df_features = self.generar_features_scoring(fecha_scoring, horizonte_dias)

            print("\n4️⃣  Prediciendo...")
            predicciones = self.predictor.predict(df_features)

            print("\n5️⃣  Registrando...")
            self.registrar_predicciones(predicciones, df_features, fecha_scoring, horizonte_dias)

            print(f"\n✅ Scoring completado\n")
            return True

        except Exception as e:
            print(f"\n❌ Error: {e}\n")
            return False
        finally:
            if self.conn:
                self.conn.close()

def ejecutar_scoring_diario(fecha_scoring: Optional[str] = None, horizonte_dias: int = 30) -> bool:
    """Entry point para scoring diario"""
    scoring = ScoringDiario()
    return scoring.ejecutar(fecha_scoring, horizonte_dias)
