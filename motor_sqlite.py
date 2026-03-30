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
    conexion.execute("PRAGMA cache_size = -64000;")
    conexion.execute("PRAGMA temp_store = MEMORY;")
    
    cursor = conexion.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS info_db (clave TEXT PRIMARY KEY, valor TEXT)''')

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
    min_absoluto = None
    max_absoluto = None

    for db_path in archivos_db:
        try:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            cursor.execute('''
                SELECT MIN(CAST(anio AS INTEGER)), MAX(CAST(anio AS INTEGER)) 
                FROM documentos 
                WHERE anio != 'Desconocido' AND anio IS NOT NULL AND CAST(anio AS INTEGER) > 0
            ''')
            res = cursor.fetchone()
            conexion.close()

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
            # Obtenemos la fecha de modificación más reciente guardada para cada PDF
            cursor.execute("SELECT ruta, MAX(mtime) FROM documentos GROUP BY ruta")
            for fila in cursor.fetchall():
                archivos_indexados[fila[0]] = float(fila[1]) if fila[1] else 0.0
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
            try:
                cursor.execute("SELECT valor FROM info_db WHERE clave = 'ruta_carpeta'")
                ruta_carpeta = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                ruta_carpeta = os.path.basename(db_path).split("__part")[0]
            cursor.execute("SELECT COUNT(DISTINCT ruta) FROM documentos")
            info_carpetas[ruta_carpeta] = info_carpetas.get(ruta_carpeta, 0) + cursor.fetchone()[0]
            conexion.close()
        except sqlite3.OperationalError: pass
    return dict(sorted(info_carpetas.items()))

def borrar_indice():
    try:
        for f in glob.glob(os.path.join(INDICES_DIR, "*.db")): os.remove(f)
        return True
    except Exception as e: return str(e)

def borrar_indice_carpeta(ruta_carpeta):
    try:
        hash_ruta = hashlib.md5(ruta_carpeta.encode('utf-8')).hexdigest()[:8]
        nombre_carpeta_limpio = os.path.basename(ruta_carpeta.rstrip(os.sep)) or "raiz"
        nombre_base_db = f"{nombre_carpeta_limpio}_{hash_ruta}"
        
        archivos_db = glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db"))
        if not archivos_db: archivos_db = glob.glob(os.path.join(INDICES_DIR, f"{ruta_carpeta}__part*.db"))
        if not archivos_db: return f"No se encontraron índices para '{ruta_carpeta}'."
            
        for f in archivos_db: os.remove(f)
        return True
    except Exception as e: return str(e)

def indexar_documentos(carpeta_pdfs, metodo_anio="nombre_archivo", callback_progreso=None):
    global detener_indexacion
    detener_indexacion = False 
    archivo_errores = os.path.join(BASE_DIR, "errores_indexacion.txt")
    total_pdfs = sum(1 for raiz, _, archivos in os.walk(carpeta_pdfs) for a in archivos if a.lower().endswith('.pdf'))
    
    archivos_procesados, lote_size = 0, 50 
    conexion, cursor = None, None
    current_db_path, ruta_carpeta_actual_en_proceso = "", ""
    archivos_nuevos_en_lote = 0
    archivos_ya_indexados = {}
    
    for raiz, _, archivos in os.walk(carpeta_pdfs):
        if detener_indexacion: break 
        pdfs_en_raiz = [a for a in archivos if a.lower().endswith('.pdf')]
        if not pdfs_en_raiz: continue
            
        ruta_carpeta_relativa = obtener_ruta_relativa(os.path.abspath(raiz))
            
        if ruta_carpeta_relativa != ruta_carpeta_actual_en_proceso:
            if conexion:
                conexion.commit()
                conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
                conexion.commit()
                conexion.close()
            
            ruta_carpeta_actual_en_proceso = ruta_carpeta_relativa
            hash_ruta = hashlib.md5(ruta_carpeta_relativa.encode('utf-8')).hexdigest()[:8]
            nombre_base_db = f"{os.path.basename(ruta_carpeta_relativa.rstrip(os.sep)) or 'raiz'}_{hash_ruta}"
            
            archivos_ya_indexados = obtener_archivos_ya_indexados_de_carpeta(nombre_base_db)
            dbs_existentes = glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db"))
            part_num = 1
            if dbs_existentes:
                partes = [int(re.search(r'__part(\d+)\.db$', db).group(1)) for db in dbs_existentes if re.search(r'__part(\d+)\.db$', db)]
                if partes: part_num = max(partes)
                
            current_db_path = os.path.join(INDICES_DIR, f"{nombre_base_db}__part{part_num}.db")
            conexion = inicializar_db(current_db_path)
            cursor = conexion.cursor()
            conexion.execute("INSERT OR IGNORE INTO info_db (clave, valor) VALUES ('ruta_carpeta', ?)", (ruta_carpeta_relativa,))
            conexion.commit()
            archivos_nuevos_en_lote = 0
        
        for archivo in pdfs_en_raiz:
            if detener_indexacion: break 
                
            archivos_procesados += 1
            ruta_absoluta = os.path.abspath(os.path.join(raiz, archivo))
            ruta_pdf_relativa = obtener_ruta_relativa(ruta_absoluta) 
            
            # --- LÓGICA DE MEMORIA CON FECHAS ---
            try:
                mtime_actual = os.path.getmtime(ruta_absoluta)
            except OSError:
                mtime_actual = 0.0

            es_modificado = False

            if ruta_pdf_relativa in archivos_ya_indexados:
                mtime_guardado = archivos_ya_indexados[ruta_pdf_relativa]
                # Si la fecha del archivo es igual o más vieja que la guardada, se omite
                if mtime_actual <= mtime_guardado:
                    if callback_progreso: 
                        callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_relativa, None)
                    continue 
                else:
                    # El archivo fue modificado. Se borra de las bases de datos antiguas
                    es_modificado = True
                    dbs_carpeta = glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db"))
                    for db_p in dbs_carpeta:
                        try:
                            conn_del = sqlite3.connect(db_p)
                            conn_del.execute("DELETE FROM documentos WHERE ruta = ?", (ruta_pdf_relativa,))
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
                        conexion.execute("INSERT OR IGNORE INTO info_db (clave, valor) VALUES ('ruta_carpeta', ?)", (ruta_carpeta_relativa,))
                        conexion.commit()
                        archivos_nuevos_en_lote = 0
                    
            except Exception as e_doc:
                with open(archivo_errores, "a", encoding="utf-8") as f:
                    f.write(f"Archivo: {ruta_absoluta} | Error: {e_doc}\n")
                    
    if conexion:
        conexion.commit()
        conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
        conexion.commit()
        conexion.close()

def buscar_texto(consulta_str, carpetas_permitidas=None, limite=50, offset=0, anio_min=None, anio_max=None, incluir_desconocidos=True, limite_maximo=10000):
    if not carpetas_permitidas: return {"total": 0, "resultados": []}

    archivos_db_objetivo = []
    for carpeta in carpetas_permitidas:
        hash_ruta = hashlib.md5(carpeta.encode('utf-8')).hexdigest()[:8]
        nombre_base_db = f"{os.path.basename(carpeta.rstrip(os.sep)) or 'raiz'}_{hash_ruta}"
        
        archivos = glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db"))
        if not archivos: archivos = glob.glob(os.path.join(INDICES_DIR, f"{carpeta}__part*.db"))
        archivos_db_objetivo.extend(archivos)

    if not archivos_db_objetivo: return {"error": "No hay índices disponibles."}

    total_hits = 0
    hits_por_db = []

    for db_path in archivos_db_objetivo:
        try:
            conexion = sqlite3.connect(db_path)
            cursor = conexion.cursor()
            
            query_base = "SELECT COUNT(*) FROM documentos WHERE contenido MATCH ?"
            params = [consulta_str]

            if anio_min is not None and anio_max is not None:
                if incluir_desconocidos:
                    query_base += " AND ( (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ?) OR anio = 'Desconocido' )"
                else:
                    query_base += " AND (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ? AND anio != 'Desconocido')"
                params.extend([anio_min, anio_max])

            cursor.execute(query_base, params)
            count = cursor.fetchone()[0]
            if count > 0:
                hits_por_db.append({"db": db_path, "count": count})
                total_hits += count
            conexion.close()
        except sqlite3.OperationalError as e:
            return {"error": f"Error FTS5: {e}"}

    # --- FRENO DE EMERGENCIA ---
    if total_hits > limite_maximo:
        return {"excede_limite": True, "total": total_hits, "limite_maximo": limite_maximo}

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
