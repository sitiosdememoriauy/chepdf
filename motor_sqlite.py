import os
import sys
import sqlite3
import re
import time
import glob
import hashlib
import fitz  # PyMuPDF

# --- OPTIMIZACIÓN DE CPU EN WINDOWS ---
if sys.platform == 'win32':
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
INDICES_DIR = os.path.join(BASE_DIR, "indices")
os.makedirs(INDICES_DIR, exist_ok=True)

MAX_DB_SIZE = 100 * 1024 * 1024 
detener_indexacion = False

def obtener_ruta_relativa(ruta_absoluta):
    try:
        return os.path.relpath(ruta_absoluta, BASE_DIR)
    except ValueError:
        return ruta_absoluta

def inicializar_db(db_path):
    conexion = sqlite3.connect(db_path)
    conexion.execute("PRAGMA journal_mode = WAL;")
    conexion.execute("PRAGMA synchronous = NORMAL;")
    
    cursor = conexion.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS info_db (clave TEXT PRIMARY KEY, valor TEXT)''')
    
    # --- TABLA RÁPIDA PARA LA INTERFAZ ---
    cursor.execute('''CREATE TABLE IF NOT EXISTS metadatos_pdf (ruta TEXT PRIMARY KEY, carpeta TEXT, anio TEXT, mtime REAL)''')
    # -------------------------------------------

    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS documentos USING fts5(
            ruta UNINDEXED, 
            pagina UNINDEXED, 
            anio UNINDEXED,
            mtime UNINDEXED,
            contenido, 
            tokenize='unicode61 remove_diacritics 1'
        )
    ''')
    conexion.commit()
    return conexion

def limpiar_texto_basico(texto):
    texto_limpio = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', ' ', texto)
    return re.sub(r'\s+', ' ', texto_limpio).strip()

def extraer_anio_multifuente(ruta_absoluta, doc, metodo):
    try:
        if metodo == "nombre_archivo":
            nombre = os.path.basename(ruta_absoluta)
            match = re.search(r'(18|19|20)\d{2}', nombre)
            if match: return match.group(0)
        elif metodo == "carpeta":
            carpeta = os.path.basename(os.path.dirname(ruta_absoluta))
            match = re.search(r'(18|19|20)\d{2}', carpeta)
            if match: return match.group(0)
        elif metodo == "metadatos":
            meta = doc.metadata
            if meta and 'creationDate' in meta:
                match = re.search(r'(18|19|20)\d{2}', meta['creationDate'])
                if match: return match.group(0)
    except Exception:
        pass
    return "Desconocido"

def obtener_rango_anios():
    archivos_db = glob.glob(os.path.join(INDICES_DIR, "*__part*.db"))
    min_absoluto, max_absoluto = None, None

    for db_path in archivos_db:
        try:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            # Buscamos min y max en la tabla rápida
            cursor.execute('''
                SELECT MIN(CAST(anio AS INTEGER)), MAX(CAST(anio AS INTEGER)) 
                FROM metadatos_pdf 
                WHERE anio != 'Desconocido' AND anio IS NOT NULL AND CAST(anio AS INTEGER) > 0
            ''')
            res = cursor.fetchone()
            conexion.close()
            # ... (el resto de la función sigue igual) ...

            if res and res[0] is not None and res[1] is not None:
                min_db, max_db = int(res[0]), int(res[1])
                if min_absoluto is None or min_db < min_absoluto:
                    min_absoluto = min_db
                if max_absoluto is None or max_db > max_absoluto:
                    max_absoluto = max_db
        except sqlite3.OperationalError:
            pass

    return min_absoluto, max_absoluto

def obtener_archivos_ya_indexados_de_carpeta(nombre_base_db):
    archivos_indexados = {}
    dbs_carpeta = glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db"))
    for db_path in dbs_carpeta:
        try:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            
            # Usamos la tabla rápida de metadatos
            cursor.execute("SELECT ruta, mtime FROM metadatos_pdf")
            for fila in cursor.fetchall():
                # Guardamos la fecha y EN QUÉ ARCHIVO EXACTO está guardado
                archivos_indexados[fila[0]] = (float(fila[1]) if fila[1] else 0.0, db_path)
                
            conexion.close()
        except sqlite3.OperationalError: pass
    return archivos_indexados

def obtener_carpetas_unicas():
    info_carpetas = {}
    archivos_db = glob.glob(os.path.join(INDICES_DIR, "*__part*.db"))
    
    for db_path in archivos_db:
        try:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            
            # Leemos agrupado directamente desde la tabla rápida
            cursor.execute("SELECT carpeta, COUNT(*) FROM metadatos_pdf GROUP BY carpeta")
            for carpeta, cantidad in cursor.fetchall():
                carpeta_limpia = carpeta if carpeta else "raiz"
                info_carpetas[carpeta_limpia] = info_carpetas.get(carpeta_limpia, 0) + cantidad
                
            conexion.close()
        except sqlite3.OperationalError: 
            pass
            
    return dict(sorted(info_carpetas.items()))

def borrar_indice():
    try:
        for f in glob.glob(os.path.join(INDICES_DIR, "*.db")): os.remove(f)
        return True
    except Exception as e: return str(e)

def borrar_indice_carpeta(ruta_carpeta):
    # Borra los registros de esa subcarpeta en las bases de datos existentes.
    try:
        archivos_db = glob.glob(os.path.join(INDICES_DIR, "*__part*.db"))
        for db_path in archivos_db:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            
            if ruta_carpeta == "raiz":
                cursor.execute("DELETE FROM documentos WHERE ruta NOT LIKE '%/%' AND ruta NOT LIKE '%\\%'")
            else:
                cursor.execute("DELETE FROM documentos WHERE ruta LIKE ? OR ruta LIKE ?", (f"{ruta_carpeta}/%", f"{ruta_carpeta}\\%"))
            
            conexion.commit()
            conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
            conexion.commit()
            
            # Si quedó vacía, borramos el archivo
            cursor.execute("SELECT COUNT(*) FROM documentos")
            if cursor.fetchone()[0] == 0:
                conexion.close()
                os.remove(db_path)
            else:
                conexion.close()
        return True
    except Exception as e: return str(e)

def indexar_documentos(carpeta_pdfs, metodo_anio="nombre_archivo", callback_progreso=None):
    global detener_indexacion
    detener_indexacion = False 
    archivo_errores = os.path.join(BASE_DIR, "errores_indexacion.txt")
    
    ruta_raiz_relativa = obtener_ruta_relativa(os.path.abspath(carpeta_pdfs))

    # =====================================================================
    # 1. PREPARACIÓN (Calcular a qué DBs apuntamos)
    # =====================================================================
    hash_ruta = hashlib.md5(ruta_raiz_relativa.encode('utf-8')).hexdigest()[:8]
    nombre_base_db = f"{os.path.basename(ruta_raiz_relativa.rstrip(os.sep)) or 'raiz'}_{hash_ruta}"
    
    # Abrimos las bases de datos de esta carpeta específica, ignorando el resto
    archivos_db_objetivo = glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db"))

    # =====================================================================
    # 2. FASE DE LIMPIEZA DE FANTASMAS (usando los metadatos)
    # =====================================================================
    for db_path in archivos_db_objetivo:
        if detener_indexacion: break
        try:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            
            # Buscamos directo en metadatos_pdf
            cursor.execute("SELECT ruta FROM metadatos_pdf")
            rutas_db = cursor.fetchall()
            
            rutas_a_borrar = []
            for (ruta_relativa,) in rutas_db:
                if not os.path.exists(os.path.join(BASE_DIR, ruta_relativa)):
                    rutas_a_borrar.append((ruta_relativa,))
            
            if rutas_a_borrar:
                cursor.executemany("DELETE FROM documentos WHERE ruta = ?", rutas_a_borrar)
                cursor.executemany("DELETE FROM metadatos_pdf WHERE ruta = ?", rutas_a_borrar)
                conexion.commit()
                # Solo optimizamos la base de datos si efectivamente borramos algo
                conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
                conexion.commit()
            
            cursor.execute("SELECT COUNT(*) FROM metadatos_pdf")
            if cursor.fetchone()[0] == 0:
                conexion.close()
                os.remove(db_path)
                continue
                
            conexion.close()
        except sqlite3.OperationalError:
            pass

    # =====================================================================
    # 3. INICIALIZACIÓN PARA ARCHIVOS NUEVOS
    # =====================================================================
    archivos_ya_indexados = obtener_archivos_ya_indexados_de_carpeta(nombre_base_db)
    
    part_num = 1
    if archivos_db_objetivo:
        partes = [int(re.search(r'__part(\d+)\.db$', db).group(1)) for db in archivos_db_objetivo if re.search(r'__part(\d+)\.db$', db)]
        if partes: part_num = max(partes)
        
    current_db_path = os.path.join(INDICES_DIR, f"{nombre_base_db}__part{part_num}.db")
    conexion = inicializar_db(current_db_path)
    cursor = conexion.cursor()
    conexion.execute("INSERT OR IGNORE INTO info_db (clave, valor) VALUES ('ruta_carpeta', ?)", (ruta_raiz_relativa,))
    conexion.commit()

    # =====================================================================
    # 4. BUCLE PRINCIPAL DE INDEXACIÓN
    # =====================================================================
    total_pdfs = sum(1 for raiz, _, archivos in os.walk(carpeta_pdfs) for a in archivos if a.lower().endswith('.pdf'))
    archivos_procesados, lote_size = 0, 50 
    archivos_nuevos_en_lote = 0
    
    ruta_carpeta_actual_en_proceso = ""
    archivos_en_subcarpeta_actual = 0
    
    for raiz, _, archivos in os.walk(carpeta_pdfs):
        if detener_indexacion: break 
        pdfs_en_raiz = [a for a in archivos if a.lower().endswith('.pdf')]
        if not pdfs_en_raiz: continue
        
        ruta_carpeta_relativa = obtener_ruta_relativa(os.path.abspath(raiz))
        
        if ruta_carpeta_relativa != ruta_carpeta_actual_en_proceso:
            if ruta_carpeta_actual_en_proceso != "":
                if callback_progreso:
                    callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_actual_en_proceso, None, carpeta_terminada=True, total_carpeta=archivos_en_subcarpeta_actual)
            ruta_carpeta_actual_en_proceso = ruta_carpeta_relativa
            archivos_en_subcarpeta_actual = 0 
        
        for archivo in pdfs_en_raiz:
            if detener_indexacion: break 
                
            archivos_procesados += 1
            archivos_en_subcarpeta_actual += 1 
            ruta_absoluta = os.path.abspath(os.path.join(raiz, archivo))
            ruta_pdf_relativa = obtener_ruta_relativa(ruta_absoluta) 
            
            try:
                mtime_actual = os.path.getmtime(ruta_absoluta)
            except OSError:
                mtime_actual = 0.0

            es_modificado = False
            if ruta_pdf_relativa in archivos_ya_indexados:
                # Recuperamos la fecha Y en qué DB exacta está guardado el archivo
                mtime_guardado, db_donde_esta = archivos_ya_indexados[ruta_pdf_relativa]
                
                if mtime_actual <= mtime_guardado:
                    if callback_progreso: 
                        callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_actual_en_proceso, None)
                    continue 
                else:
                    es_modificado = True
                    # Borramos el archivo SOLO en la DB específica donde está
                    try:
                        conn_del = sqlite3.connect(db_donde_esta)
                        conn_del.execute("DELETE FROM documentos WHERE ruta = ?", (ruta_pdf_relativa,))
                        conn_del.execute("DELETE FROM metadatos_pdf WHERE ruta = ?", (ruta_pdf_relativa,))
                        conn_del.commit()
                        conn_del.close()
                    except: pass
                
            try:
                doc = fitz.open(ruta_absoluta)
                if doc.needs_pass: raise Exception("Protegido con contraseña.")
                
                anio_doc = extraer_anio_multifuente(ruta_absoluta, doc, metodo_anio)
                anio_para_ui = None if es_modificado else anio_doc

                if callback_progreso: 
                    callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_relativa, anio_para_ui)
                
                cursor.execute(
                    "INSERT OR REPLACE INTO metadatos_pdf (ruta, carpeta, anio, mtime) VALUES (?, ?, ?, ?)",
                    (ruta_pdf_relativa, ruta_carpeta_relativa, anio_doc, mtime_actual)
                )
                
                for num_pag, pagina in enumerate(doc):
                    texto = pagina.get_text("text")
                    if texto.strip():
                        texto_procesado = limpiar_texto_basico(texto)
                        if len(texto_procesado) > 5:
                            cursor.execute(
                                "INSERT INTO documentos (ruta, pagina, anio, mtime, contenido) VALUES (?, ?, ?, ?, ?)",
                                (ruta_pdf_relativa, str(num_pag + 1), anio_doc, mtime_actual, texto_procesado)
                            )
                doc.close()
                archivos_nuevos_en_lote += 1
                time.sleep(0.05)
                
                if archivos_nuevos_en_lote % lote_size == 0:
                    conexion.commit()
                    if os.path.getsize(current_db_path) >= MAX_DB_SIZE:
                        conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
                        conexion.commit()
                        conexion.close()
                        
                        part_num += 1
                        current_db_path = os.path.join(INDICES_DIR, f"{nombre_base_db}__part{part_num}.db")
                        conexion = inicializar_db(current_db_path)
                        cursor = conexion.cursor()
                        conexion.execute("INSERT OR IGNORE INTO info_db (clave, valor) VALUES ('ruta_carpeta', ?)", (ruta_raiz_relativa,))
                        conexion.commit()
                        archivos_nuevos_en_lote = 0
                    
            except Exception as e_doc:
                with open(archivo_errores, "a", encoding="utf-8") as f:
                    f.write(f"Archivo: {ruta_absoluta} | Error: {e_doc}\n")
                    
    if conexion:
        conexion.commit()
        conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
        conexion.commit()
        
        if ruta_carpeta_actual_en_proceso != "":
            if callback_progreso:
                callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_actual_en_proceso, None, carpeta_terminada=True, total_carpeta=archivos_en_subcarpeta_actual)
            
        conexion.close()

def buscar_texto(consulta_str, carpetas_permitidas=None, limite=50, offset=0, anio_min=None, anio_max=None, incluir_desconocidos=True, limite_maximo=10000):
    if not carpetas_permitidas: return {"total": 0, "resultados": []}

    archivos_db_objetivo = glob.glob(os.path.join(INDICES_DIR, "*__part*.db"))
    if not archivos_db_objetivo: return {"error": "No hay índices disponibles."}

    # =========================================================
    # CONSTRUIR FILTRO DE SUBCARPETAS PARA SQL
    # =========================================================
    condicion_carpetas_sql = ""
    params_carpetas = []
    clausulas = []
    
    for c in carpetas_permitidas:
        if c == "raiz":
            clausulas.append("ruta NOT LIKE '%/%' AND ruta NOT LIKE '%\\%'")
        else:
            clausulas.append("ruta LIKE ? OR ruta LIKE ?")
            params_carpetas.extend([f"{c}/%", f"{c}\\%"])
    
    if clausulas:
        condicion_carpetas_sql = " AND (" + " OR ".join(clausulas) + ")"

    total_hits = 0
    hits_por_db = []

    for db_path in archivos_db_objetivo:
        try:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            
            limite_restante_conteo = limite_maximo - total_hits + 1
            
            query_base = f"SELECT count(*) FROM (SELECT 1 FROM documentos WHERE contenido MATCH ?"
            params = [consulta_str]

            if anio_min is not None and anio_max is not None:
                if incluir_desconocidos:
                    query_base += " AND ( (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ?) OR anio = 'Desconocido' )"
                else:
                    query_base += " AND (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ? AND anio != 'Desconocido')"
                params.extend([anio_min, anio_max])
            
            query_base += condicion_carpetas_sql
            params.extend(params_carpetas)

            query_base += f" LIMIT {limite_restante_conteo})"

            cursor.execute(query_base, params)
            count = cursor.fetchone()[0]
            
            if count > 0:
                hits_por_db.append({"db": db_path, "count": count})
                total_hits += count
                
            conexion.close()
            
            if total_hits > limite_maximo:
                return {"excede_limite": True, "total": f"+{limite_maximo}", "limite_maximo": limite_maximo}

        except sqlite3.OperationalError as e:
            return {"error": f"Error FTS5: {e}"}

    if total_hits == 0: return {"total": 0, "resultados": []}

    resultados = []
    offset_restante, limite_restante = offset, limite

    for db_info in hits_por_db:
        if limite_restante <= 0: break 
        if offset_restante >= db_info["count"]:
            offset_restante -= db_info["count"]
            continue

        conexion = sqlite3.connect(db_info["db"])
        cursor = conexion.cursor()
        
        query_search = '''
            SELECT ruta, pagina, snippet(documentos, 4, '<b>', '</b>', '...', 60), anio 
            FROM documentos 
            WHERE contenido MATCH ? 
        '''
        params_search = [consulta_str]
        
        if anio_min is not None and anio_max is not None:
            if incluir_desconocidos:
                query_search += " AND ( (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ?) OR anio = 'Desconocido' )"
            else:
                query_search += " AND (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ? AND anio != 'Desconocido')"
            params_search.extend([anio_min, anio_max])
            
        query_search += condicion_carpetas_sql
        params_search.extend(params_carpetas)
            
        query_search += " ORDER BY rank LIMIT ? OFFSET ?"
        params_search.extend([limite_restante, offset_restante])
        
        cursor.execute(query_search, params_search)
        filas = cursor.fetchall()
        conexion.close()

        for r in filas:
            resultados.append({"ruta": r[0], "pagina": r[1], "extracto": r[2], "anio": r[3]})

        limite_restante -= len(filas)
        offset_restante = 0 

    return {"total": total_hits, "resultados": resultados}
