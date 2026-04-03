import PyInstaller.__main__
import shutil
import os
import platform

print("Iniciando compilación de Che PDF...")

# --- NUEVO: Chequeo de dependencias en Linux ---
if platform.system() == "Linux":
    ruta_mpv1 = "/usr/lib/x86_64-linux-gnu/libmpv.so.1"
    ruta_mpv2 = "/usr/lib/x86_64-linux-gnu/libmpv.so.2"
    
    if not os.path.exists(ruta_mpv1):
        print("\n" + "="*60)
        print("⚠️  ADVERTENCIA DE DEPENDENCIA EN LINUX ⚠️")
        print("Flet requiere 'libmpv.so.1', pero no se encontró en tu sistema.")
        
        if os.path.exists(ruta_mpv2):
            print("Se detectó 'libmpv.so.2'. Para solucionar este error, abre otra terminal y ejecuta:")
            print("sudo ln -s /usr/lib/x86_64-linux-gnu/libmpv.so.2 /usr/lib/x86_64-linux-gnu/libmpv.so.1")
        else:
            print("Asegúrate de instalar 'libmpv' usando el gestor de paquetes de tu distribución.")
            print("Ejemplo (Ubuntu/Debian): sudo apt install libmpv-dev")
        print("="*60 + "\n")
# ----------------------------------------------

# 1. Ejecutamos PyInstaller desde adentro de Python
PyInstaller.__main__.run([
    'app.py',
    '--noconfirm',
    '--windowed',
    '--onedir',
    '--name=Che PDF',
    '--icon=_internal/assets/icono_che.ico'
])

print("\nEnsamblando la distribución final...")

# 2. Definimos dónde quedó el programa compilado
ruta_dist = os.path.join('dist', 'Che PDF')

# 3. Copiamos la carpeta de idiomas a la raíz del ejecutable
ruta_locales_origen = 'locales'
ruta_locales_destino = os.path.join(ruta_dist, 'locales')

if os.path.exists(ruta_locales_origen):
    print(f"Copiando traducciones a {ruta_locales_destino}...")
    shutil.copytree(ruta_locales_origen, ruta_locales_destino, dirs_exist_ok=True)

# 4. Copiamos TODOS los archivos README dinámicamente
print("Buscando archivos de documentación (README)...")
archivos_en_raiz = os.listdir('.')

for archivo in archivos_en_raiz:
    # Convertimos a minúsculas para atrapar README.md, readme-en.md, Readme.md, etc.
    if archivo.lower().startswith('readme') and archivo.lower().endswith('.md'):
        print(f" -> Copiando {archivo}...")
        shutil.copy(archivo, ruta_dist)

# 5. Copiamos los recursos gráficos (imágenes y logos)
# Detectamos automáticamente dónde tienes guardada tu carpeta de imágenes original
ruta_assets_origen = 'assets' if os.path.exists('assets') else os.path.join('_internal', 'assets')
ruta_assets_destino = os.path.join(ruta_dist, '_internal', 'assets')

if os.path.exists(ruta_assets_origen):
    print(f"Copiando recursos visuales a {ruta_assets_destino}...")
    shutil.copytree(ruta_assets_origen, ruta_assets_destino, dirs_exist_ok=True)
else:
    print("⚠️ No se encontró la carpeta original de assets. Las imágenes podrían faltar.")

print("\n¡Éxito! El programa está listo y ensamblado en la carpeta 'dist/Che PDF'.")
