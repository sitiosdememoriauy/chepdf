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
   git clone https://github.com/sitiosdememoriauy/chepdf/
   ```

2. **Crea y activa un entorno virtual:**
   
   **En Windows:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

   **En Linux:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Instala las dependencias:**
   ```bash
   cd chepdf
   pip install -r requirements.txt
   ```

4. **Ejecuta la aplicación:**
   
   **En Windows:**
   ```bash
   python app.py
   ```
   
   **En Linux:**
   ```bash
   python3 app.py
   ```

## 📦 Compilación

Para distribuir el programa a usuarios finales de Windows o Linux sin que necesiten instalar Python, puedes compilarlo usando el empaquetador de Flet. Ejecuta el siguiente comando en la raíz del proyecto:

   **En Windows:**
   ```bash
   python compilar.py
   ```

   **En Linux:**
   ```bash
   python3 compilar.py
   ```

Esto generará una carpeta dist que contiene el ejecutable final y la carpeta de recursos. Puedes comprimir esa carpeta en un archivo .zip o .tar.gz para distribuirla.

## 📖 Guía de Uso Básica

1. Configuración Inicial: Ve a la pestaña 'Configuración' y selecciona el método para deducir el año histórico (por nombre, carpeta o metadatos).
2. Indexación: Haz clic en el botón de la carpeta en el menú lateral para añadir tu directorio de PDFs. El sistema escaneará y guardará el texto en la base de datos interna.
3. Filtros: Usa la barra lateral para definir un rango de años o seleccionar carpetas específicas.
4. Búsqueda: Ingresa tu término en la barra superior. Si hay un exceso de resultados, el sistema te pedirá afinar los filtros.
5. Lectura: Haz clic en cualquier resultado para abrir el PDF original en la página exacta.

## 🤝 Apoya el Proyecto

Che PDF es y siempre será una herramienta de software libre y gratuita. Tu aporte voluntario nos ayuda a mantener nuestra infraestructura, desarrollar nuevas herramientas y continuar con el trabajo de investigación.

Si la herramienta te resulta útil, considera hacer un aporte solidario:
💖 Donar a través de Ko-fi: https://ko-fi.com/sitiosdememoriauy

## 👨‍💻 Autores

* Rodrigo Barbano y Mariana Risso - Investigadores y desarrolladores.
Proyecto impulsado por sitiosdememoria.uy.

## 📄 Licencia

Este proyecto está bajo la Licencia GNU GPLv3. Eres libre de usar, estudiar, compartir y modificar este software para cualquier propósito, siempre y cuando las obras derivadas mantengan la misma licencia abierta.

## Historial de Versiones

### v1.2 (Abril 2026)
* **Motor de Búsqueda Dual:**  Opción configurable para alternar entre "Modo Precisión" (ranking algorítmico FTS5) y "Modo Velocidad" (extracción secuencial instantánea).
* **Exploración Continua:**  Nuevo sistema de paginación por scroll (algoritmo Límite + 1) en modo rápido, permitiendo cargar resultados infinitos sin saturar la memoria RAM.
* **Enrutamiento Inteligente en RAM:**  Creación del mapa maestro JSON con radar Min-Max, que filtra matemáticamente las bases de datos irrelevantes antes de tocar el disco duro.
* **Auto-Sincronización del Índice:**  Reconstrucción automática del mapa de carpetas leyendo directamente los metadatos de SQLite, blindando el sistema contra archivos borrados manualmente.
* **Prevención de Cuelgues FTS5:**  El "Modo Velocidad" evade el planificador interno de SQLite omitiendo consultas de conteo masivas, previniendo bloqueos con palabras muy comunes o comodines abiertos.
* **Refactorización Visual (Flet):**  Implementación de ruptura de caché por frames asíncronos para garantizar traducciones al vuelo instantáneas en todos los menús desplegables.

### v1.1 (Abril 2026)
* **Soporte Multilenguaje:** Interfaz disponible en Español e Inglés (configurable).
* **Limpieza inteligente:** Detección automática y eliminación de archivos "fantasma" (eliminados del disco) al re-indexar.
* **Optimización Extrema FTS5:** Búsquedas masivas instantáneas gracias al límite inyectado en el motor de conteo.
* **Consolidación Estructural:** Nueva arquitectura de base de datos única por carpeta raíz, previniendo bloqueos y reduciendo el uso del disco.
* **Panel Detallado:** Desglose exacto de cantidad de PDFs por subcarpeta en el panel izquierdo.

### v1.0 (Marzo 2026)
* Versión inicial del proyecto.
