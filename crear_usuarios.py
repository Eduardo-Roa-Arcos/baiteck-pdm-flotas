#!/usr/bin/env python3
"""
CREAR USUARIOS — Script para insertar usuarios en tabla usuarios con contraseña hasheada
========================================================================================

Uso:
  uv run python crear_usuarios.py

Este script te permite:
  1. Crear un nuevo usuario interactivamente
  2. O cargar múltiples usuarios desde un CSV
  3. Las contraseñas se hashean automáticamente con bcrypt (rounds=12)

Autor: BAITECK — junio 2026
"""

import os
from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import csv
from uuid import uuid4
from datetime import datetime
import sys


DATABASE_URL = os.getenv("DATABASE_URL")


def get_db_connection():
    """Retorna conexión a Supabase PostgreSQL."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        print(f"❌ Error al conectar a Supabase: {e}")
        return None


def hash_contraseña(contraseña: str) -> str:
    """Genera hash bcrypt de una contraseña."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(contraseña.encode('utf-8'), salt).decode('utf-8')


def verificar_email_existe(email: str) -> bool:
    """Verifica si un email ya existe en la tabla usuarios."""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM usuarios WHERE email = %s", (email,))
        existe = cursor.fetchone() is not None
        cursor.close()
        return existe
    except psycopg2.Error as e:
        print(f"❌ Error al verificar email: {e}")
        return False
    finally:
        if conn:
            conn.close()


def crear_usuario_individual():
    """Interfaz interactiva para crear un usuario."""
    print("\n" + "="*70)
    print("📝 CREAR USUARIO INDIVIDUAL")
    print("="*70)
    
    nombre = input("Nombre completo: ").strip()
    email = input("Email: ").strip().lower()
    rol = input("Rol (admin/supervisor/operador/viewer) [opcional]: ").strip() or None
    
    # Validar email
    if "@" not in email:
        print("❌ Email inválido.")
        return False
    
    # Verificar si existe
    if verificar_email_existe(email):
        print(f"❌ El email {email} ya existe en la base de datos.")
        return False
    
    # Solicitar contraseña
    while True:
        contraseña = input("Contraseña (mín. 8 caracteres): ").strip()
        if len(contraseña) < 8:
            print("❌ La contraseña debe tener al menos 8 caracteres.")
            continue
        confirmar = input("Confirmar contraseña: ").strip()
        if contraseña != confirmar:
            print("❌ Las contraseñas no coinciden.")
            continue
        break
    
    # Hashear contraseña
    contraseña_hash = hash_contraseña(contraseña)
    
    # Insertar en BD
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        usuario_id = str(uuid4())
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO usuarios (usuario_id, nombre, email, rol, estado, contraseña_hash, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (usuario_id, nombre, email, rol, 'activo', contraseña_hash)
        )
        conn.commit()
        cursor.close()
        
        print("\n✅ Usuario creado exitosamente:")
        print(f"   ID: {usuario_id}")
        print(f"   Nombre: {nombre}")
        print(f"   Email: {email}")
        print(f"   Rol: {rol or 'N/A'}")
        print(f"   Estado: activo")
        
        return True
    
    except psycopg2.Error as e:
        print(f"❌ Error al insertar usuario: {e}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def crear_usuarios_desde_csv(archivo_csv: str):
    """
    Carga múltiples usuarios desde un archivo CSV.
    
    Formato esperado:
    nombre,email,rol,contraseña
    Juan Pérez,juan@empresa.com,supervisor,contraseña123
    Maria García,maria@empresa.com,operador,contraseña456
    """
    print("\n" + "="*70)
    print(f"📂 CREAR USUARIOS DESDE CSV: {archivo_csv}")
    print("="*70)
    
    if not os.path.exists(archivo_csv):
        print(f"❌ Archivo no encontrado: {archivo_csv}")
        return False
    
    usuarios_validos = []
    usuarios_invalidos = []
    
    try:
        with open(archivo_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=2):
                nombre = row.get('nombre', '').strip()
                email = row.get('email', '').strip().lower()
                rol = row.get('rol', '').strip() or None
                contraseña = row.get('contraseña', '').strip()
                
                # Validaciones
                errores = []
                if not nombre:
                    errores.append("nombre vacío")
                if not email or "@" not in email:
                    errores.append("email inválido")
                if len(contraseña) < 8:
                    errores.append("contraseña < 8 caracteres")
                if verificar_email_existe(email):
                    errores.append("email ya existe")
                
                if errores:
                    usuarios_invalidos.append((idx, nombre or email, ", ".join(errores)))
                else:
                    contraseña_hash = hash_contraseña(contraseña)
                    usuarios_validos.append((nombre, email, rol, contraseña_hash))
    
    except Exception as e:
        print(f"❌ Error al leer CSV: {e}")
        return False
    
    # Mostrar resumen
    print(f"\n📊 Resumen:")
    print(f"   ✅ Usuarios válidos: {len(usuarios_validos)}")
    print(f"   ❌ Usuarios inválidos: {len(usuarios_invalidos)}")
    
    if usuarios_invalidos:
        print("\n⚠️  Usuarios con errores:")
        for idx, usuario, errores in usuarios_invalidos:
            print(f"   Línea {idx} ({usuario}): {errores}")
    
    if not usuarios_validos:
        print("❌ No hay usuarios válidos para insertar.")
        return False
    
    # Confirmar antes de insertar
    confirmacion = input(f"\n¿Insertar {len(usuarios_validos)} usuarios? (s/n): ").strip().lower()
    if confirmacion != 's':
        print("❌ Operación cancelada.")
        return False
    
    # Insertar
    conn = get_db_connection()
    if not conn:
        return False
    
    insertados = 0
    try:
        cursor = conn.cursor()
        for nombre, email, rol, contraseña_hash in usuarios_validos:
            usuario_id = str(uuid4())
            cursor.execute(
                """
                INSERT INTO usuarios (usuario_id, nombre, email, rol, estado, contraseña_hash, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                """,
                (usuario_id, nombre, email, rol, 'activo', contraseña_hash)
            )
            insertados += 1
        
        conn.commit()
        cursor.close()
        print(f"\n✅ {insertados} usuarios creados exitosamente.")
        return True
    
    except psycopg2.Error as e:
        print(f"❌ Error al insertar usuarios: {e}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def listar_usuarios():
    """Lista todos los usuarios en la tabla."""
    print("\n" + "="*70)
    print("📋 USUARIOS EN LA BASE DE DATOS")
    print("="*70)
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT usuario_id, nombre, email, rol, estado, 
                   created_at, updated_at
            FROM usuarios
            ORDER BY created_at DESC
            """
        )
        usuarios = cursor.fetchall()
        cursor.close()
        
        if not usuarios:
            print("(No hay usuarios en la base de datos)")
            return
        
        print(f"\nTotal: {len(usuarios)} usuarios\n")
        for usuario in usuarios:
            print(f"👤 {usuario['nombre']} ({usuario['email']})")
            print(f"   ID: {usuario['usuario_id']}")
            print(f"   Rol: {usuario['rol'] or 'N/A'}")
            print(f"   Estado: {usuario['estado']}")
            print(f"   Creado: {usuario['created_at']}")
            print()
    
    except psycopg2.Error as e:
        print(f"❌ Error al listar usuarios: {e}")
    finally:
        if conn:
            conn.close()


def menu_principal():
    """Menú interactivo principal."""
    while True:
        print("\n" + "="*70)
        print("🔐 GESTIÓN DE USUARIOS — BAITECK")
        print("="*70)
        print("1. Crear usuario individual")
        print("2. Crear usuarios desde CSV")
        print("3. Listar usuarios existentes")
        print("4. Salir")
        print("="*70)
        
        opcion = input("Selecciona una opción (1-4): ").strip()
        
        if opcion == "1":
            crear_usuario_individual()
        elif opcion == "2":
            archivo = input("Ruta del archivo CSV: ").strip()
            crear_usuarios_desde_csv(archivo)
        elif opcion == "3":
            listar_usuarios()
        elif opcion == "4":
            print("👋 Hasta luego!")
            break
        else:
            print("❌ Opción inválida.")


if __name__ == "__main__":
    # Verificar que DATABASE_URL esté configurada
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL no está configurada en .env")
        sys.exit(1)
    
    # Verificar conexión
    conn = get_db_connection()
    if not conn:
        print("❌ No se pudo conectar a Supabase.")
        sys.exit(1)
    conn.close()
    
    print("\n✅ Conexión a Supabase verificada.")
    
    menu_principal()
