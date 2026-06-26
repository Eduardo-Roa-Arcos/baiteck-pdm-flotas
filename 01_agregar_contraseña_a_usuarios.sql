-- ==============================================================================
-- SCRIPT: Agregar campo contraseña_hash a tabla usuarios
-- ==============================================================================
-- Descripción: Agrega soporte para autenticación con contraseña hasheada (bcrypt)
-- Autor: BAITECK — junio 2026
-- ==============================================================================

ALTER TABLE usuarios
ADD COLUMN contraseña_hash VARCHAR(255);

-- Agregar constraint para garantizar que existe al menos una contraseña en usuarios activos
-- (Opcional, pero recomendado para integridad)
ALTER TABLE usuarios
ADD CONSTRAINT usuarios_activos_require_password
CHECK (
    estado != 'activo' OR contraseña_hash IS NOT NULL
);

-- Comentario descriptivo
COMMENT ON COLUMN usuarios.contraseña_hash IS 'Hash bcrypt de la contraseña del usuario. Usar bcrypt con rounds=12.';

-- Confirmar
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'usuarios' 
ORDER BY ordinal_position;
