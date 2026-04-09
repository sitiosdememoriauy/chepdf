import subprocess
import shutil
import os
import platform
import sys

print("Iniciando compilación de Che PDF usando Flet Pack...")

# --- Chequeo de dependencias en Linux ---
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

# 1. Ejecutamos flet pack
print("\nEmpaquetando motor asíncrono (Esto puede tardar un minuto)...")

ejecutable_flet = os.path.join(os.path.dirname(sys.executable), "flet.exe" if platform.system() == "Windows" else "flet")
if not os.path.exists(ejecutable_flet):
    ejecutable_flet = "flet"

comando_flet = [
    ejecutable_flet, "pack", "app.py",
    "--name", "Che PDF",
    "--icon", "_internal/assets/icono_che.ico"
]

try:
    subprocess.run(comando_flet, check=True)
except subprocess.CalledProcessError as e:
    print(f"\n❌ Error crítico al compilar con Flet Pack. Revisa la consola arriba. Código: {e.returncode}")
    exit(1)
except FileNotFoundError:
    print("\n❌ Error: No se pudo encontrar el comando 'flet'. Asegúrate de tenerlo instalado: pip install flet")
    exit(1)

print("\nEnsamblando la distribución final...")

# ==============================================================
# CREAR UNA CARPETA CONTENEDORA LIMPIA
# ==============================================================
nombre_exe = "Che PDF.exe" if platform.system() == "Windows" else "Che PDF"
ruta_exe_crudo = os.path.join('dist', nombre_exe)

# Creamos la carpeta donde vivirá todo el proyecto junto
ruta_dist = os.path.join('dist', 'Che_PDF')

# Limpiamos si ya existía de un intento anterior
if os.path.exists(ruta_dist):
    shutil.rmtree(ruta_dist)
os.makedirs(ruta_dist, exist_ok=True)

# 2. Movemos el ejecutable adentro de la nueva carpeta
if os.path.exists(ruta_exe_crudo):
    shutil.move(ruta_exe_crudo, os.path.join(ruta_dist, nombre_exe))
else:
    print(f"⚠️ No se encontró el archivo {ruta_exe_crudo}. Algo falló en la compilación de Flet.")

# 3. Copiamos la carpeta de idiomas a la raíz del ejecutable
ruta_locales_origen = 'locales'
ruta_locales_destino = os.path.join(ruta_dist, 'locales')

if os.path.exists(ruta_locales_origen):
    print(f" -> Copiando traducciones a {ruta_locales_destino}...")
    shutil.copytree(ruta_locales_origen, ruta_locales_destino, dirs_exist_ok=True)

# 4. Copiamos TODOS los archivos README dinámicamente
print(" -> Buscando archivos de documentación (README)...")
archivos_en_raiz = os.listdir('.')
for archivo in archivos_en_raiz:
    if archivo.lower().startswith('readme') and archivo.lower().endswith('.md'):
        print(f"    - Copiando {archivo}...")
        shutil.copy(archivo, ruta_dist)

# 5. Copiamos los recursos gráficos (imágenes y logos)
ruta_assets_origen = 'assets' if os.path.exists('assets') else os.path.join('_internal', 'assets')
ruta_assets_destino = os.path.join(ruta_dist, '_internal', 'assets')

if os.path.exists(ruta_assets_origen):
    print(f" -> Copiando recursos visuales a {ruta_assets_destino}...")
    shutil.copytree(ruta_assets_origen, ruta_assets_destino, dirs_exist_ok=True)
else:
    print("⚠️ No se encontró la carpeta original de assets. Las imágenes podrían faltar.")

print("\n=======================================================")
print("¡Éxito! El programa está listo y ensamblado.")
print("Puedes encontrar tu versión final: 'dist/Che_PDF'")
print("=======================================================\n")
