# src/pipelines/scoring_diario.py
"""
Pipeline de scoring batch diario
Orquesta: generación de features → predicción → registro en Supabase
"""
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid
from typing import Optional
import numpy as np

# Importar desde src.db
from src.db import construir_features, engine
from src.models.predictor import Predictor

load_dotenv()

class ScoringDiario:
    """Pipeline de scoring batch diario"""

    def __init__(self):
        """Inicializa predictor y conexión a BD"""
        self.predictor = Predictor(engine=engine)
        self.conn = None

    def conectar_db(self) -> bool:
        """
        Establece conexión a Supabase

        Returns:
            bool: True si conexión es exitosa
        """
        try:
            self.conn = psycopg2.connect(
                host=os.getenv("SUPABASE_HOST"),
                database=os.getenv("SUPABASE_DATABASE"),
                user=os.getenv("SUPABASE_USER"),
                password=os.getenv("SUPABASE_PASSWORD"),
                port=5432,
                sslmode="require"
            )
            print("✅ Conectado a Supabase")
            return True
        except Exception as e:
            print(f"❌ Error de conexión a Supabase: {e}")
            raise

    def obtener_activos(self) -> list:
        """
        Obtiene lista de activos vigentes de la BD

        Returns:
            list: IDs de activos
        """
        cursor = None
        try:
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            query = """
                SELECT DISTINCT activo_id
                FROM activos
                WHERE activo_id IS NOT NULL
                ORDER BY activo_id
            """
            cursor.execute(query)
            activos = [row['activo_id'] for row in cursor.fetchall()]
            print(f"   ℹ️  {len(activos)} activos para procesar")
            return activos
        except Exception as e:
            print(f"❌ Error obteniendo activos: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def generar_features_scoring(self, fecha_scoring: str, horizonte_dias: int = 30) -> pd.DataFrame:
        """
        Genera features para scoring usando construir_features()

        Args:
            fecha_scoring (str): Fecha en formato YYYY-MM-DD
            horizonte_dias (int): Horizonte de predicción

        Returns:
            pd.DataFrame: Features listos para predicción (sin target)
        """
        try:
            print(f"   🔧 Generando features para {fecha_scoring}...")

            # Usar la función construir_features existente
            # Esta retorna el panel COMPLETO incluyendo target
            df_panel = construir_features(fecha_corte_str=fecha_scoring, horizonte_dias=horizonte_dias)

            # Para scoring, quitamos el target (es para entrenamiento)
            # Mantenemos: activo_id, fecha_corte, horizonte_dias, edad_dias, ot_*d, corr_*d
            feature_cols = [
                'activo_id', 'fecha_corte', 'horizonte_dias',
                'edad_dias', 'ot_30d', 'ot_90d', 'ot_180d', 
                'corr_30d', 'corr_90d', 'corr_180d'
            ]

            df_features = df_panel[feature_cols].copy()

            print(f"   ✅ {len(df_features)} registros con features generados")

            return df_features

        except Exception as e:
            print(f"❌ Error generando features: {e}")
            raise

    def registrar_predicciones(self, 
                               predicciones: dict, 
                               df_features: pd.DataFrame, 
                               fecha_scoring: str, 
                               horizonte_dias: int) -> int:
        """
        Escribe predicciones en scoring_resultados

        Args:
            predicciones (dict): Resultado de predictor.predict()
            df_features (pd.DataFrame): DataFrame con activo_id y features
            fecha_scoring (str): Fecha del scoring (YYYY-MM-DD)
            horizonte_dias (int): Horizonte de predicción

        Returns:
            int: Número de registros insertados
        """
        cursor = None
        registros_insertados = 0
        try:
            cursor = self.conn.cursor()

            # Función auxiliar para mapear probabilidad a prioridad
            def asignar_prioridad(p: float) -> str:
                """Clasificar riesgo por probabilidad"""
                if p >= 0.85:
                    return "P1_critica"
                elif p >= 0.65:
                    return "P2_alta"
                elif p >= 0.40:
                    return "P3_media"
                else:
                    return "P4_baja"

            # Preparar registros para insertar
            insert_query = """
                INSERT INTO scoring_resultados 
                (scoring_id, activo_id, fecha_scoring, horizonte_dias, 
                 probabilidad_falla, prediccion, prioridad, modelo_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """

            for idx, row in df_features.iterrows():
                try:
                    scoring_id = str(uuid.uuid4())
                    activo_id = row['activo_id']
                    prob = float(predicciones['probabilidades'][idx])
                    pred = int(predicciones['predicciones'][idx])
                    prioridad = asignar_prioridad(prob)

                    cursor.execute(insert_query, (
                        scoring_id,
                        activo_id,
                        fecha_scoring,
                        horizonte_dias,
                        prob,
                        pred,
                        prioridad,
                        predicciones['modelo_version']
                    ))
                    registros_insertados += 1

                except Exception as e:
                    print(f"⚠️  Error insertando {activo_id}: {e}")
                    continue

            self.conn.commit()
            print(f"   ✅ {registros_insertados} predicciones registradas en Supabase")

            # Mostrar resumen de prioridades
            if registros_insertados > 0:
                print("\n   📊 Resumen de prioridades:")
                for idx, row in df_features.iterrows():
                    prob = predicciones['probabilidades'][idx]
                    prioridad = asignar_prioridad(prob)
                    print(f"      {row['activo_id']}: {prioridad} (prob={prob:.2%})")

            return registros_insertados

        except Exception as e:
            if self.conn:
                self.conn.rollback()
            print(f"❌ Error registrando predicciones: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def ejecutar(self, fecha_scoring: Optional[str] = None, horizonte_dias: int = 30) -> bool:
        """
        Ejecuta el pipeline completo de scoring diario

        Args:
            fecha_scoring (str): Fecha en formato YYYY-MM-DD (default: hoy)
            horizonte_dias (int): Días a futuro para predicción (default: 30)

        Returns:
            bool: True si ejecutó exitosamente
        """
        try:
            # Usar fecha actual si no se especifica
            if fecha_scoring is None:
                fecha_scoring = datetime.now().strftime("%Y-%m-%d")

            print(f"\n{'='*70}")
            print(f"🚀 SCORING DIARIO")
            print(f"   Fecha: {fecha_scoring}")
            print(f"   Horizonte: {horizonte_dias} días")
            print(f"{'='*70}")

            # Paso 1: Conectar a Supabase
            print("\n1️⃣  Conectando a Supabase...")
            self.conectar_db()

            # Paso 2: Cargar modelo activo
            print("\n2️⃣  Cargando modelo activo...")
            self.predictor.load_active_model()

            # Paso 3: Generar features
            print("\n3️⃣  Generando features...")
            df_features = self.generar_features_scoring(fecha_scoring, horizonte_dias)

            # Paso 4: Predecir
            print("\n4️⃣  Realizando predicciones...")
            print(f"   🤖 Procesando {len(df_features)} activos...")
            predicciones = self.predictor.predict(df_features)

            # Paso 5: Registrar resultados
            print("\n5️⃣  Registrando resultados...")
            count = self.registrar_predicciones(predicciones, df_features, fecha_scoring, horizonte_dias)

            print(f"\n{'='*70}")
            print(f"✅ Scoring diario completado exitosamente")
            print(f"   {count} predicciones registradas")
            print(f"{'='*70}\n")

            return True

        except Exception as e:
            print(f"\n❌ Error en scoring diario: {e}")
            return False
        finally:
            if self.conn:
                self.conn.close()


# Entry point
def ejecutar_scoring_diario(fecha_scoring: Optional[str] = None, horizonte_dias: int = 30) -> bool:
    """
    Función para ejecutar desde main.py o cron job

    Args:
        fecha_scoring (str): Fecha en formato YYYY-MM-DD (default: hoy)
        horizonte_dias (int): Días para predicción (default: 30)

    Returns:
        bool: True si fue exitoso

    Ejemplo:
        uv run python -c "from main import ejecutar_scoring_diario; ejecutar_scoring_diario('2024-05-15')"
    """
    scoring = ScoringDiario()
    return scoring.ejecutar(fecha_scoring, horizonte_dias)
