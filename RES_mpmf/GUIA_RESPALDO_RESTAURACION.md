# 🔐 RESPALDO Y RESTAURACIÓN DE BASE DE DATOS - BAITECK PDM-FLOTAS

## 📋 RESUMEN

Tienes **3 formas** de respaldar tu base de datos Supabase:

1. **Script Python** (RECOMENDADO) → Fácil, automatizable
2. **Comandos SQL** → Desde Supabase UI
3. **pg_dump** → Línea de comandos, más potente

---

## ✅ OPCIÓN 1: Script Python (RECOMENDADO)

### Respaldar toda la BD (archivos CSV)

```bash
uv run python respaldar_base_datos.py
```

**¿Qué hace?**
- Crea carpeta: `./backups/2024-06-14_02-00-00/`
- Exporta TODAS las tablas a CSV
- Genera `schema_completo.sql` (DDL)
- Genera `resumen_backup.txt` con estadísticas

**Resultado:**
```
./backups/2024-06-14_02-00-00/
├── schema_completo.sql        (definiciones)
├── activos.csv                (~1.2 MB, 500 filas)
├── ordenes_trabajo.csv        (~8.5 MB, 12,000 filas)
├── ot_falla_evento.csv        (~4.2 MB, 8,500 filas)
├── ...
└── resumen_backup.txt
```

### Respaldar solo 1 tabla

```bash
uv run python respaldar_base_datos.py --tabla activos
```

### Respaldar en JSON (mejor para Excel/Power BI)

```bash
uv run python respaldar_base_datos.py --formato json
```

### Comprimir respaldo

```bash
tar -czf backups/2024-06-14_backup.tar.gz backups/2024-06-14_02-00-00/
```

**Tiempo:** ~30-60 segundos para BD completa

---

## ♻️ RESTAURAR DESDE BACKUP

### Restaurar toda la BD

```bash
uv run python restaurar_base_datos.py --backup ./backups/2024-06-14_02-00-00
```

### Restaurar solo 1 tabla

```bash
uv run python restaurar_base_datos.py --backup ./backups/2024-06-14_02-00-00 --tabla activos
```

### Modo de prueba (sin escribir en BD)

```bash
uv run python restaurar_base_datos.py --backup ./backups/2024-06-14_02-00-00 --test
```

### Borrar tablas existentes antes de restaurar

```bash
uv run python restaurar_base_datos.py --backup ./backups/2024-06-14_02-00-00 --drop
```

**Orden de restauración automática (respeta Foreign Keys):**
1. activos
2. taxonomia_fallas
3. ordenes_trabajo
4. ot_falla_evento
5. disponibilidad_diaria
6. scoring_resultados
7. paneles
8. repuestos_maestro
9. repuestos_consumidos
10. feedback_taller

---

## 🖥️ OPCIÓN 2: Comandos SQL (Desde Supabase UI)

### 1. Listar todas las tablas y tamaños

Copia y pega en **Supabase > SQL Editor**:

```sql
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size('public.'||tablename)) AS tamaño
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size('public.'||tablename) DESC;
```

**Resultado:**
```
tablename                | tamaño
ordenes_trabajo          | 8.5 MB
ot_falla_evento          | 4.2 MB
disponibilidad_diaria    | 2.1 MB
...
```

### 2. Obtener el DDL (SQL de creación) de todas las tablas

```sql
-- Ver todas las columnas y tipos
SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

### 3. Descargar tabla como CSV desde Supabase UI

1. Ve a **Supabase > SQL Editor**
2. Ejecuta: `SELECT * FROM tabla_nombre`
3. Click en **Download as CSV** (esquina superior derecha)

### 4. Exportar todas las Foreign Keys

```sql
SELECT 
    constraint_name,
    table_name,
    column_name,
    referenced_table_name
FROM information_schema.key_column_usage
WHERE referenced_table_name IS NOT NULL
ORDER BY table_name;
```

Ver archivo `RESPALDO_SQL_COMANDOS.sql` para más comandos.

---

## ⚙️ OPCIÓN 3: pg_dump (Línea de comandos)

### Respaldar toda la BD

```bash
# En tu terminal local:
pg_dump -h aws-1-us-east-1.pooler.supabase.com \
        -U postgres \
        -d baiteck_db \
        -F custom \
        -f backup_completo.dump
```

**Parámetros:**
- `-h`: Host de Supabase
- `-U`: Usuario (postgres)
- `-d`: Nombre de la BD
- `-F custom`: Formato comprimido (más eficiente)
- `-f`: Archivo de salida

### Comprimir

```bash
gzip backup_completo.dump
```

### Restaurar

```bash
# En servidor destino:
pg_restore -h localhost \
           -U postgres \
           -d nombre_db_nuevo \
           backup_completo.dump
```

---

## 📊 COMPARATIVA DE MÉTODOS

| Método | Velocidad | Tamaño | Legibilidad | Automatización | Recomendado |
|--------|-----------|--------|-------------|----------------|-------------|
| **Python (CSV)** | Medio | Grande | ✅ Alta | ✅ Sí | ✅ SÍ |
| **Python (JSON)** | Medio | Grande | ✅ Alta | ✅ Sí | ✅ SÍ |
| **SQL UI Supabase** | Lento | Grande | ✅ Alta | ❌ No | Para ad-hoc |
| **pg_dump** | Rápido | Pequeño | ❌ Baja | ✅ Sí | Devops |

---

## 🔄 AUTOMATIZAR RESPALDOS DIARIOS

### Con cron (cada noche a las 3:00 AM)

```bash
crontab -e
```

Agregar:

```cron
# Respaldo diario - BAITECK PDM-FLOTAS
0 3 * * * cd ~/baiteck-pdm-flotas && uv run python respaldar_base_datos.py >> /tmp/respaldo.log 2>&1

# Mantener solo últimos 7 días de respaldos
0 4 * * * find ~/baiteck-pdm-flotas/backups -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null
```

### Con script maestro

Crea `respaldos_nightly.sh`:

```bash
#!/bin/bash

set -e

cd ~/baiteck-pdm-flotas

echo "🔐 Iniciando respaldo de BD..."
uv run python respaldar_base_datos.py

echo "📦 Comprimiendo..."
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
tar -czf backups/${TIMESTAMP}.tar.gz backups/${TIMESTAMP}/

echo "☁️ Copiando a S3 (opcional)..."
# aws s3 cp backups/${TIMESTAMP}.tar.gz s3://mi-bucket-backups/

echo "✅ Respaldo completado"
```

Luego en cron:

```cron
0 3 * * * /home/usuario/baiteck-pdm-flotas/respaldos_nightly.sh
```

---

## 🚨 CHECKLIST DE BACKUP

Antes de ir a producción, verifica:

- [ ] **Respaldo manual funciona** → `uv run python respaldar_base_datos.py`
- [ ] **Restauración funciona** → `uv run python restaurar_base_datos.py --backup ./backups/...`
- [ ] **Tamaño de respaldos** → ¿Son razonables? (~20-50 MB?)
- [ ] **Cron configurado** → ¿Respaldos automáticos cada noche?
- [ ] **Verificación de integridad** → ¿COUNT(*) coincide tras restaurar?
- [ ] **Almacenamiento** → ¿Dónde guardar? (Local SSD, Cloud, Externa)
- [ ] **Retención** → ¿Cuántos días guardar? (sugerencia: 30 días)
- [ ] **Prueba de restauración** → ¿Probaste restaurar a un servidor test?
- [ ] **Documentación** → ¿Están estos scripts en tu repo?
- [ ] **Alertas** → ¿Notificación si falla un respaldo?

---

## 🔐 SEGURIDAD

### Buenas prácticas:

1. **Encriptación en tránsito** → Usa SSH/TLS para pg_dump
2. **Encriptación en reposo** → Si guardas en cloud (S3, GCS), activa encryption
3. **Acceso limitado** → Respaldos solo accesibles a admins
4. **Múltiples copias** → Guarda en local + cloud
5. **Pruebas periódicas** → Restaura a test cada mes
6. **Versionamiento** → Guarda con timestamps (YYYY-MM-DD_HH-MM-SS)
7. **Documentación** → Mantén un registro de respaldos

### Ejemplo: Guardar en S3 (AWS)

```bash
# Después de comprimir
aws s3 cp backups/2024-06-14_backup.tar.gz \
    s3://mi-bucket-privado/baiteck-backups/ \
    --sse AES256  # Encriptación
```

---

## 📞 TROUBLESHOOTING

### Error: "DATABASE_URL no configurada"
**Solución:** Crear `.env` con tu conexión a Supabase
```
DATABASE_URL=postgresql://user:pass@aws-1-us-east-1.pooler.supabase.com:5432/baiteck
```

### Error: "Tabla no existe al restaurar"
**Solución:** Restaurar primero el schema
```bash
psql -f backups/2024-06-14/schema_completo.sql
```

### Datos inconsistentes tras restaurar
**Solución:** Verificar Foreign Keys
```sql
-- Ejecutar en BD restaurada
SELECT COUNT(*) FROM ordenes_trabajo WHERE activo_id NOT IN (SELECT activo_id FROM activos);
```

### Respaldo muy lento (>5 minutos)
**Solución:** Respaldar solo últimos 30 días
```bash
# En respaldar_base_datos.py, modificar:
WHERE fecha_scoring >= CURRENT_DATE - INTERVAL 30 days
```

---

## 📚 REFERENCIAS

- **pg_dump docs:** https://www.postgresql.org/docs/current/app-pgdump.html
- **Supabase Backup:** https://supabase.com/docs/guides/database/backups
- **Best Practices:** https://wiki.postgresql.org/wiki/Backup_and_Restore

---

## 🎯 RECOMENDACIÓN PARA PRODUCCIÓN

**Script nightly completo (`nightly_complete.sh`):**

```bash
#!/bin/bash
set -e

# 1. Respaldo de BD
cd ~/baiteck-pdm-flotas
uv run python respaldar_base_datos.py

# 2. Comprimir
TIMESTAMP=$(date +%Y-%d-%m_%H-%M-%S)
tar -czf backups/${TIMESTAMP}.tar.gz backups/${TIMESTAMP}/

# 3. Copiar a cloud (AWS S3)
aws s3 cp backups/${TIMESTAMP}.tar.gz s3://backups-baiteck/

# 4. Limpiar locales viejos (>30 días)
find backups/ -type d -mtime +30 -exec rm -rf {} \;

# 5. Ejecutar pipeline de actualización
uv run python ejecutar_nightly.py

echo "✅ Ciclo completo nocturno terminado"
```

En cron:
```cron
0 2 * * * /home/usuario/baiteck-pdm-flotas/nightly_complete.sh >> /var/log/baiteck_nightly.log 2>&1
```

---

**¿Preguntas? Revisa los scripts Python directamente — están bien comentados.**
