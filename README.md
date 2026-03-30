*Read this in [English](README-en.md).*

# 📄 Che PDF

**Che PDF** es un motor de indexación y búsqueda documental avanzado y de alto rendimiento. Está diseñado específicamente para procesar, analizar y buscar texto dentro de repositorios masivos de archivos históricos en formato PDF (probado en volúmenes de hasta 4TB).

Esta aplicación fue desarrollada por **sitiosdememoria.uy** con el objetivo de facilitar el análisis y la investigación de grandes volúmenes documentales. Cuenta con una licencia de software libre que permite su uso, estudio, difusión y modificación, como parte del compromiso del proyecto con las luchas por memoria, verdad y justicia.

## ✨ Características Principales

* **Búsqueda Ultrarrápida (FTS5):** Utiliza SQLite FTS5 para realizar búsquedas instantáneas sobre millones de palabras, soportando sintaxis avanzada (frases exactas, AND, OR, NOT).
* **Gestión de Metadatos Históricos:** Extrae automáticamente el año de los documentos mediante tres métodos configurables: nombre del archivo, nombre de la carpeta contenedora o metadatos internos del PDF.
* **Filtros Dinámicos:** Permite acotar las búsquedas por rangos de años precisos y por carpetas específicas mediante una interfaz intuitiva.
* **Lectura Directa:** Al hacer clic en un resultado, el PDF se abre en el navegador web del sistema operativo exactamente en la página de la coincidencia y con el término de búsqueda resaltado.
* **Límites de Seguridad:** Integra un freno de emergencia configurable (por defecto 10.000 resultados) para evitar colapsos de memoria al buscar términos demasiado comunes en archivos masivos.
* **Interfaz Gráfica (GUI) Amigable:** Construida en Python con Flet (Flutter), ofreciendo un entorno oscuro, moderno y fácil de usar para usuarios sin conocimientos técnicos.

## 🛠️ Requisitos del Sistema y Tecnologías

El código fuente está escrito en **Python 3**. Las dependencias principales son:
* `flet==0.28.3` (Nota: Se utiliza esta versión específica y estable de la arquitectura original para garantizar la compatibilidad de hardware y evitar *bugs* de parpadeo de pantalla presentes en versiones posteriores).
* `PyMuPDF` (fitz) para el procesamiento de documentos.
* `sqlite3` (nativo en Python).

## 🚀 Instalación y Ejecución desde el Código Fuente

Si deseas ejecutar el programa desde su código fuente o contribuir a su desarrollo:

1. **Clona el repositorio:**
   ```bash
   git clone https://github.com/sitiosdememoriauy/chepdf.git
   cd che-pdf
   ```

2. **Crea y activa un entorno virtual:**
   ```bash
   python -m venv .venv
   ```

**En Windows:**
   ```bash
   .venv\Scripts\activate
   ```

**En Linux/Mac:**
   ```bash
   source .venv/bin/activate
   ```

3. **Instala las dependencias:**
   ```bash
   pip install flet==0.28.3 PyMuPDF
   ```

4. **Ejecuta la aplicación:**
   ```bash
   python app.py
   ```

## 📦 Compilación (Crear un Ejecutable .exe)

Para distribuir el programa a usuarios finales de Windows sin que necesiten instalar Python, puedes compilarlo usando el empaquetador de Flet. Ejecuta el siguiente comando en la raíz del proyecto:
flet pack app.py --name "Che PDF" --icon "_internal/assets/icono_che.ico" --add-data "_internal/assets;_internal/assets"

Esto generará una carpeta dist que contiene el ejecutable final y la carpeta de recursos. Puedes comprimir esa carpeta en un archivo .zip para distribuirla.

## 📖 Guía de Uso Básica

1. Configuración Inicial: Ve a la pestaña 'Configuración' y selecciona el método para deducir el año histórico (por nombre, carpeta o metadatos).
2. Indexación: Haz clic en el botón de la carpeta en el menú lateral para añadir tu directorio de PDFs. El sistema escaneará y guardará el texto en la base de datos interna.
3. Filtros: Usa la barra lateral para definir un rango de años o seleccionar carpetas específicas.
4. Búsqueda: Ingresa tu término en la barra superior. Si hay un exceso de resultados, el sistema te pedirá afinar los filtros.
5. Lectura: Haz clic en cualquier resultado para abrir el PDF original en la página exacta.

## 🤝 <img src="http://sitiosdememoria.uy/sites/default/files/inline-images/Flag_of_Uruguay.svg" height="20"> Apoya el Proyecto

Che PDF es y siempre será una herramienta de software libre y gratuita. Tu aporte voluntario nos ayuda a mantener nuestra infraestructura, desarrollar nuevas herramientas y continuar con el trabajo de investigación.

Si la herramienta te resulta útil, considera hacer un aporte solidario:
💖 Donar a través de Ko-fi: https://ko-fi.com/sitiosdememoriauy

## 👨‍💻 Autores

* Rodrigo Barbano y Mariana Risso - Investigadores y desarrolladores.
Proyecto impulsado por sitiosdememoria.uy.

## 📄 Licencia

Este proyecto está bajo la Licencia GNU GPLv3. Eres libre de usar, estudiar, compartir y modificar este software para cualquier propósito, siempre y cuando las obras derivadas mantengan la misma licencia abierta.
