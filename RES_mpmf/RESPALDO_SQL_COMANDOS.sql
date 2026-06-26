-- ============================================================================
-- 🔐 RESPALDAR BASE DE DATOS COMPLETA - COMANDOS SQL
-- ============================================================================
-- Ejecuta estos comandos en Supabase SQL Editor para obtener el schema
-- de todas las tablas y verificar integridad de datos.
-- ============================================================================

-- ============================================================================
-- 1. LISTAR TODAS LAS TABLAS Y SUS TAMAÑOS
-- ============================================================================

SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS tamaño
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- ============================================================================
-- 2. OBTENER ESTRUCTURA COMPLETA DE CADA TABLA
-- ============================================================================

SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_name, ordinal_position;

-- ============================================================================
-- 3. OBTENER TODAS LAS CONSTRAINTS (PK, FK, UNIQUE, CHECK)
-- ============================================================================

SELECT 
    table_name,
    constraint_name,
    constraint_type
FROM information_schema.table_constraints
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_name, constraint_name;

-- ============================================================================
-- 4. OBTENER RELACIONES FOREIGN KEY
-- ============================================================================

SELECT 
    constraint_name,
    table_name,
    column_name,
    referenced_table_name,
    referenced_column_name
FROM information_schema.key_column_usage
WHERE referenced_table_name IS NOT NULL
  AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_name, constraint_name;

-- ============================================================================
-- 5. VERIFICAR INTEGRIDAD DE DATOS - CONTAR FILAS POR TABLA
-- ============================================================================

SELECT 
    schemaname,
    tablename,
    n_live_tup AS filas
FROM pg_stat_user_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n_live_tup DESC;

-- ============================================================================
-- 6. RESUMEN RÁPIDO - TABLA CON TODAS LAS TABLAS
-- ============================================================================

WITH tabla_info AS (
    SELECT 
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS tamaño,
        (SELECT COUNT(*) FROM information_schema.columns c 
         WHERE c.table_name = t.tablename AND c.table_schema = t.schemaname) AS columnas,
        (SELECT n_live_tup FROM pg_stat_user_tables st 
         WHERE st.relname = t.tablename) AS filas
    FROM pg_tables t
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
)
SELECT * FROM tabla_info ORDER BY schemaname, tablename;

-- ============================================================================
-- 7. EXPORTAR DEFINICIONES DE TODAS LAS TABLAS (DDL)
-- ============================================================================
-- Ejecuta esto para obtener el SQL de creación de todas las tablas

SELECT 
    tablename,
    'CREATE TABLE ' || tablename || ' AS SELECT * FROM ' || tablename || ';' AS ddl_simple
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY tablename;

-- ============================================================================
-- 8. VERIFICAR SECUENCIAS (para SERIAL/AUTO INCREMENT)
-- ============================================================================

SELECT 
    sequence_name,
    start_value,
    minimum_value,
    maximum_value,
    increment,
    cycle
FROM information_schema.sequences
WHERE sequence_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY sequence_name;

-- ============================================================================
-- 9. VERIFICAR ÍNDICES
-- ============================================================================

SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY tablename, indexname;

-- ============================================================================
-- 10. VERIFICAR VISTAS (si existen)
-- ============================================================================

SELECT 
    table_schema,
    table_name,
    view_definition
FROM information_schema.views
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_name;

-- ============================================================================
-- INSTRUCCIONES PARA RESPALDAR MANUALMENTE
-- ============================================================================

/*

OPCIÓN 1: Usar pg_dump desde línea de comandos (RECOMENDADO)
============================================================

Este comando hace un respaldo completo de toda la BD:

    pg_dump -h aws-1-us-east-1.pooler.supabase.com \
            -U postgres \
            -d nombre_db \
            -F c \
            -f backup_completo.dump

Luego comprime:
    gzip backup_completo.dump

Para restaurar:
    gunzip backup_completo.dump.gz
    pg_restore -h localhost \
               -U postgres \
               -d nombre_db_nuevo \
               backup_completo.dump


OPCIÓN 2: Usar Python (script respaldar_base_datos.py)
======================================================

    uv run python respaldar_base_datos.py

Esto crea una carpeta ./backups/YYYY-MM-DD_HH-MM-SS/ con:
    - schema_completo.sql      (DDL de todas las tablas)
    - tabla_1.csv
    - tabla_2.csv
    - ...
    - resumen_backup.txt


OPCIÓN 3: Exportar a CSV desde Supabase UI
==========================================

En Supabase > SQL Editor > Descargar resultados como CSV

Pero esto es manual. Mejor usar Option 2.


OPCIÓN 4: Usar mysqldump (si migras a MySQL)
============================================

pg_dump -h host | pg2mysql | mysql -h nueva_host


CONSIDERACIONES IMPORTANTES:
============================

1. RESPALDO INCREMENTAL
   Si quieres solo los cambios desde último respaldo:
   
   SELECT * FROM tabla WHERE fecha_modificacion > '2024-06-14 02:00:00'

2. FOREIGN KEYS
   Al restaurar, desactiva FK primero:
   
   SET session_replication_role = 'replica';
   -- Restaura datos
   SET session_replication_role = 'origin';

3. VERIFICAR INTEGRIDAD POST-RESPALDO
   
   -- En BD respaldada (original):
   SELECT COUNT(*) FROM tabla_1;
   SELECT COUNT(*) FROM tabla_2;
   ...
   
   -- Luego compara en BD restaurada

4. COMPRESIÓN
   Los respaldos CSV se pueden comprimir:
   
   tar -czf backups/YYYY-MM-DD_HH-MM-SS.tar.gz backups/YYYY-MM-DD_HH-MM-SS/

5. ALMACENAMIENTO
   Guarda backups en:
   - Local SSD (rápido)
   - Cloud Storage (S3, GCS, Azure)
   - External hard drive (offline)

*/

-- ============================================================================
-- COMANDOS ÚTILES DE MANTENIMIENTO
-- ============================================================================

-- Actualizar estadísticas (para optimizar queries)
ANALYZE;

-- Vacío de espacio no usado (libera espacio)
VACUUM;

-- Vacío + análisis
VACUUM ANALYZE;

-- Ver tamaño total de la BD
SELECT pg_size_pretty(pg_database_size(current_database()));

-- Ver si hay bloqueos activos
SELECT * FROM pg_locks WHERE NOT granted;

-- Ver conexiones activas
SELECT datname, usename, state, count(*) 
FROM pg_stat_activity 
GROUP BY datname, usename, state;

-- ============================================================================
-- VERIFICACIÓN POST-RESPALDO
-- ============================================================================

-- 1. Verificar que todas las tablas existen
SELECT COUNT(*) as total_tablas FROM pg_tables 
WHERE schemaname NOT IN ('pg_catalog', 'information_schema');

-- 2. Verificar que no hay filas nulas/inconsistentes
-- (personalizar según tus tablas)

SELECT 'activos' as tabla, COUNT(*) as filas FROM activos
UNION ALL
SELECT 'ordenes_trabajo', COUNT(*) FROM ordenes_trabajo
UNION ALL
SELECT 'ot_falla_evento', COUNT(*) FROM ot_falla_evento
UNION ALL
SELECT 'taxonomia_fallas', COUNT(*) FROM taxonomia_fallas
UNION ALL
SELECT 'scoring_resultados', COUNT(*) FROM scoring_resultados
UNION ALL
SELECT 'disponibilidad_diaria', COUNT(*) FROM disponibilidad_diaria
UNION ALL
SELECT 'paneles', COUNT(*) FROM paneles
UNION ALL
SELECT 'repuestos_maestro', COUNT(*) FROM repuestos_maestro
UNION ALL
SELECT 'repuestos_consumidos', COUNT(*) FROM repuestos_consumidos
UNION ALL
SELECT 'feedback_taller', COUNT(*) FROM feedback_taller
ORDER BY tabla;

-- 3. Verificar integridad de ForeignKeys
SELECT 
    ot.ot_id,
    ot.activo_id,
    a.activo_id as activo_existe
FROM ordenes_trabajo ot
LEFT JOIN activos a ON ot.activo_id = a.activo_id
WHERE a.activo_id IS NULL
LIMIT 10;

-- ============================================================================
-- FIN
-- ============================================================================
