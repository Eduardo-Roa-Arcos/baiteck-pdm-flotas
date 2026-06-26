"""
Pipeline que REUTILIZA build_features.py para generar panel temporal de features.

Flujo:
    1. Genera múltiples fechas de corte (cada 30 días hacia atrás)
    2. Para cada fecha, ejecuta construir_features()
    3. Concatena todos los paneles
    4. Guarda en BD (features_activo_fecha)
    5. Exporta como parquet con nombres CORTOS para entrenadores/scoring
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class FeaturePipeline:
    """
    Pipeline que genera panel temporal de features usando construir_features().
    
    Flujo:
        pipeline = FeaturePipeline()
        features = pipeline.ejecutar(dias_hacia_atras=180, paso=30)
    
    El resultado se guarda en:
        - BD: tabla features_activo_fecha (nombres LARGOS)
        - Parquet: data/processed/panel_entrenamiento.parquet (nombres CORTOS)
    """
    
    def __init__(self, verbose=True):
        self.features = None
        self.verbose = verbose
        if self.verbose:
            logger.info("\n" + "="*70)
            logger.info("🔄 INICIANDO PIPELINE DE FEATURES")
            logger.info("="*70)
    
    def _log(self, mensaje, end="\n"):
        """
        Log condicional que soporta 'end' como print().
        
        Args:
            mensaje: Texto a loguear
            end: Carácter final (default: '\n' para nueva línea)
        """
        if self.verbose:
            if end == "\n":
                logger.info(mensaje)
            else:
                # Para end != '\n', usar print directamente
                print(mensaje, end=end, flush=True)
    
    def generar_fechas_corte(self, dias_hacia_atras=180, paso=30):
        """
        Genera lista de fechas de corte hacia atrás desde hoy.
        
        Args:
            dias_hacia_atras: Cuántos días atrás ir
            paso: Cada cuántos días generar una fecha
        
        Returns:
            list: Fechas en formato YYYY-MM-DD (más antigua primero)
        """
        hoy = pd.Timestamp.now().normalize()
        fechas = []
        
        for d in range(0, dias_hacia_atras, paso):
            fechas.append((hoy - timedelta(days=d)).strftime("%Y-%m-%d"))
        
        fechas.reverse()  # Más antigua primero
        return fechas
    
    def generar_panel(self, dias_hacia_atras=180, paso=30, horizontes=(7, 30, 90)):
        """
        Genera panel temporal llamando construir_features() para cada
        fecha de corte × horizonte.

        IMPORTANTE: train_xgboost.py filtra el panel por horizonte_dias
        (7/30/90) y entrena un modelo por horizonte. Por eso el panel DEBE
        contener los tres horizontes; con uno solo, los otros dos modelos
        no tienen datos de entrenamiento.

        Args:
            dias_hacia_atras: Período retrospectivo (días)
            paso: Granularidad de fechas de corte (días)
            horizontes: Iterable de horizontes predictivos para el target

        Returns:
            pd.DataFrame o None si hay error
        """
        self._log("\n🔨 Calculando features para múltiples fechas y horizontes...")
        
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))

            from src.features.build_features import construir_features
        except ImportError as e:
            self._log(f"❌ ERROR: No se puede importar construir_features: {str(e)}")
            self._log("   Verifica que src/features/build_features.py exista y sea accesible")
            raise
        
        fechas = self.generar_fechas_corte(dias_hacia_atras, paso)
        horizontes = list(horizontes)
        paneles = []
        total = len(fechas) * len(horizontes)
        
        self._log(f"   Procesando {len(fechas)} fechas × {len(horizontes)} horizontes "
                  f"= {total} cortes:\n")
        
        i = 0
        for horizonte in horizontes:
            for fecha in fechas:
                i += 1
                try:
                    self._log(f"   [{i:3}/{total}] {fecha} h{horizonte}...", end=" ")
                    df = construir_features(fecha, horizonte_dias=horizonte)
                    
                    if df is not None and len(df) > 0:
                        paneles.append(df)
                        self._log(f"✅ ({len(df):,} activos)")
                    else:
                        self._log(f"⚠️ (sin datos)")
                        
                except Exception as e:
                    self._log(f"❌ Error: {str(e)[:50]}")
        
        if not paneles:
            self._log("\n❌ No se generaron features en ninguna fecha")
            return None
        
        self.features = pd.concat(paneles, ignore_index=True)
        self._log(f"\n   ✅ Panel generado: {len(self.features):,} filas totales "
                  f"(horizontes: {sorted(self.features['horizonte_dias'].unique())})\n")
        
        return self.features
    
    def guardar_en_bd(self):
        """
        Guarda features en tabla de BD (features_activo_fecha).
        Usa nombres LARGOS de columnas (sin renombrar).
        """
        if self.features is None:
            self._log("❌ No hay features para guardar")
            return self
        
        try:
            from src.db import engine
            from sqlalchemy import text
        except ImportError as e:
            self._log(f"❌ ERROR: No se puede importar engine: {str(e)}")
            raise
        
        self._log("💾 Guardando en BD...")
        
        try:
            # Limpiar tabla
            with engine.connect() as conn:
                conn.execute(text("TRUNCATE TABLE features_activo_fecha"))
                conn.commit()
                self._log("   ℹ️ Tabla truncada")
        except Exception as e:
            self._log(f"   ⚠️ No se limpió tabla: {str(e)[:60]}")
        
        try:
            # Insertar datos
            self.features.to_sql(
                'features_activo_fecha',
                engine,
                if_exists='append',
                index=False,
                method='multi',
                chunksize=1000
            )
            self._log(f"   ✅ Guardados {len(self.features):,} registros en BD")
        except Exception as e:
            self._log(f"   ❌ Error al guardar: {str(e)[:80]}")
            raise
        
        return self
    
    def exportar_parquet(self, output_path='data/processed/panel_entrenamiento.parquet'):
        """
        Exporta features como parquet con nombres CORTOS de columnas.
        
        Mapeo de nombres:
            Largo (BD) → Corto (Parquet/Scoring)
            count_ot_30d → ot_30d
            count_ot_90d → ot_90d
            count_ot_180d → ot_180d
            count_correctivas_30d → corr_30d
            count_correctivas_90d → corr_90d
            count_correctivas_180d → corr_180d
        
        Args:
            output_path: Ruta de salida (default: data/processed/panel_entrenamiento.parquet)
        """
        if self.features is None:
            self._log("❌ No hay features para exportar")
            return self
        
        # Crear directorio si no existe
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        self._log(f"\n📦 Exportando a {output_path}...")
        
        # Mapeo de nombres largos a cortos
        mapeo_columnas = {
            'count_ot_30d': 'ot_30d',
            'count_ot_90d': 'ot_90d',
            'count_ot_180d': 'ot_180d',
            'count_correctivas_30d': 'corr_30d',
            'count_correctivas_90d': 'corr_90d',
            'count_correctivas_180d': 'corr_180d',
        }
        
        # Solo renombrar columnas que existen
        mapeo_aplicable = {k: v for k, v in mapeo_columnas.items() if k in self.features.columns}
        
        if mapeo_aplicable:
            features_export = self.features.rename(columns=mapeo_aplicable)
            self._log(f"   ℹ️ Renombradas {len(mapeo_aplicable)} columnas a formato corto")
        else:
            features_export = self.features
            self._log(f"   ℹ️ Sin cambios en nombres de columnas")
        
        try:
            features_export.to_parquet(output_path, index=False)
            self._log(f"   ✅ Exportados {len(features_export):,} registros")
            if mapeo_aplicable:
                self._log(f"   ℹ️ Nombres cortos: {list(mapeo_aplicable.values())}")
        except Exception as e:
            self._log(f"   ❌ Error al exportar: {str(e)[:80]}")
            raise
        
        return self
    
    def validar(self):
        """
        Validación básica del panel generado.
        """
        if self.features is None:
            self._log("❌ No hay features")
            return self
        
        self._log("\n✅ VALIDACIÓN:")
        self._log(f"   • Total filas: {len(self.features):,}")
        self._log(f"   • Total columnas: {len(self.features.columns)}")
        
        # Mostrar distribución de target si existe
        if 'target' in self.features.columns:
            self._log(f"   • Distribución de target:")
            try:
                for target, count in self.features['target'].value_counts().items():
                    pct = 100 * count / len(self.features)
                    self._log(f"     - {target}: {count:,} ({pct:.1f}%)")
            except Exception as e:
                self._log(f"     ⚠️ Error al mostrar distribución: {str(e)[:60]}")
        
        # Info de columnas
        numeric_cols = self.features.select_dtypes(include=['number']).columns.tolist()
        self._log(f"   • Columnas numéricas: {len(numeric_cols)}")
        
        return self
    
    def ejecutar(self, dias_hacia_atras=180, paso=30, horizontes=(7, 30, 90)):
        """
        Ejecuta pipeline COMPLETO:
            1. Generar panel temporal (todas las fechas × todos los horizontes)
            2. Guardar en BD
            3. Exportar parquet
            4. Validar
        
        Args:
            dias_hacia_atras: Período retrospectivo
            paso: Granularidad de fechas
            horizontes: Horizontes predictivos (default: 7, 30, 90 — los
                        mismos que entrena train_xgboost.py)
        
        Returns:
            pd.DataFrame con features generadas, o None si hay error
        """
        try:
            self.generar_panel(dias_hacia_atras, paso, horizontes)
            self.guardar_en_bd()
            self.exportar_parquet()
            self.validar()
            
            self._log("\n" + "="*70)
            self._log("✅ PIPELINE DE FEATURES COMPLETADO")
            self._log("="*70 + "\n")
            
            return self.features
            
        except Exception as e:
            self._log(f"\n❌ Pipeline FALLIDO: {str(e)}")
            raise


if __name__ == "__main__":
    pipeline = FeaturePipeline(verbose=True)
    features = pipeline.ejecutar(dias_hacia_atras=180, paso=30)
