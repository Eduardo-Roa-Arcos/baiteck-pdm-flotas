"""
Pipeline que REUTILIZA build_features.py para generar panel temporal.
Envuelve construir_features() para múltiples fechas y guarda resultados.
"""

import pandas as pd
from datetime import datetime, timedelta
from src.db import engine
from src.features.build_features import construir_features, generar_reporte_features
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class FeaturePipeline:
    """
    Pipeline que genera panel temporal de features usando construir_features().
    
    Uso:
        pipeline = FeaturePipeline()
        features = pipeline.ejecutar()
    """
    
    def __init__(self):
        self.features = None
        logger.info("\n" + "="*70)
        logger.info("🔄 INICIANDO PIPELINE DE FEATURES")
        logger.info("="*70)
    
    def generar_fechas_corte(self, dias_hacia_atras=180, paso=30):
        """Genera lista de fechas de corte"""
        hoy = pd.Timestamp.now().normalize()
        fechas = []
        
        for d in range(0, dias_hacia_atras, paso):
            fechas.append((hoy - timedelta(days=d)).strftime("%Y-%m-%d"))
        
        return fechas
    
    def generar_panel(self, dias_hacia_atras=180, paso=30, horizonte_dias=30):
        """
        Genera panel temporal llamando construir_features() para cada fecha.
        Reutiliza totalmente tu función existente.
        """
        print("\n🔨 Calculando features para múltiples fechas...")
        
        fechas = self.generar_fechas_corte(dias_hacia_atras, paso)
        paneles = []
        
        for i, fecha in enumerate(fechas, 1):
            try:
                print(f"   [{i}/{len(fechas)}] Procesando {fecha}...", end=" ")
                df = construir_features(fecha, horizonte_dias=horizonte_dias)
                paneles.append(df)
                print(f"✅ ({len(df)} activos)")
            except Exception as e:
                print(f"❌ Error: {str(e)[:50]}")
        
        if not paneles:
            print("❌ No se generaron features")
            return None
        
        self.features = pd.concat(paneles, ignore_index=True)
        print(f"\n   ✅ Total: {len(self.features)} filas")
        
        return self.features
    
    def guardar_en_bd(self):
        """Guarda features en tabla de BD"""
        if self.features is None:
            logger.info("❌ No hay features para guardar")
            return self
        
        logger.info("\n💾 Guardando en BD...")
        
        from sqlalchemy import text
        
        # Limpiar tabla
        try:
            with engine.connect() as conn:
                conn.execute(text("TRUNCATE TABLE features_activo_fecha"))
                conn.commit()
        except Exception as e:
            logger.info(f"   ⚠️ No se limpió tabla: {e}")
        
        # Insertar
        self.features.to_sql(
            'features_activo_fecha',
            engine,
            if_exists='append',
            index=False,
            method='multi',
            chunksize=1000
        )
        
        logger.info(f"   ✅ Guardados {len(self.features)} registros")
        
        return self
    def exportar_parquet(self, output_path='data/processed/panel_entrenamiento.parquet'):
        """
        Exporta features como parquet usando los nombres CORTOS de columnas
        que esperan los entrenadores (train_rf.py, train_xgboost.py) y el
        pipeline de scoring (ejecutar_scoring.py).
    
        Nota: la tabla features_activo_fecha de Supabase recibe los nombres
        LARGOS sin cambios. El rename solo afecta el parquet de salida.
        """
        if self.features is None:
            logger.info("❌ No hay features para exportar")
            return self
    
        logger.info(f"\n📦 Exportando a {output_path}...")
    
        # Renombrar a formato corto para alinear con scoring y predictor
        mapeo_columnas = {
            'count_ot_30d': 'ot_30d',
            'count_ot_90d': 'ot_90d',
            'count_ot_180d': 'ot_180d',
            'count_correctivas_30d': 'corr_30d',
            'count_correctivas_90d': 'corr_90d',
            'count_correctivas_180d': 'corr_180d',
        }
        features_export = self.features.rename(columns=mapeo_columnas)
    
        features_export.to_parquet(output_path, index=False)
        logger.info(f"   ✅ Exportados con nombres cortos: {list(mapeo_columnas.values())}")
    
        return self
    
    def exportar_parquet(self, output_path='data/processed/features.parquet'):
        """Exporta features como parquet"""
        if self.features is None:
            logger.info("❌ No hay features para exportar")
            return self
        
        logger.info(f"\n📦 Exportando a {output_path}...")
        
        self.features.to_parquet(output_path, index=False)
        logger.info(f"   ✅ Exportados")
        
        return self
    
    def validar(self):
        """Validación básica"""
        if self.features is None:
            logger.info("❌ No hay features")
            return self
        
        logger.info("\n✅ VALIDACIÓN:")
        logger.info(f"   • Total features: {len(self.features)} filas")
        logger.info(f"   • Columnas: {len(self.features.columns)}")
        logger.info(f"   • Target distribution:")
        for target, count in self.features['target'].value_counts().items():
            pct = 100 * count / len(self.features)
            logger.info(f"     - {target}: {count} ({pct:.1f}%)")
        
        return self
    
    def ejecutar(self, dias_hacia_atras=180, paso=30):
        """Ejecuta pipeline completo"""
        self.generar_panel(dias_hacia_atras, paso)
        self.guardar_en_bd()
        self.exportar_parquet()
        self.validar()
        
        logger.info("\n" + "="*70)
        logger.info("✅ PIPELINE DE FEATURES COMPLETADO")
        logger.info("="*70 + "\n")
        
        return self.features


if __name__ == "__main__":
    pipeline = FeaturePipeline()
    features = pipeline.ejecutar(dias_hacia_atras=180, paso=30)
