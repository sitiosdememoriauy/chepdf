import os
import sys
import sqlite3
import re
import time
import glob
import hashlib
import fitz  # PyMuPDF
import json  

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

RUTA_MAPA = os.path.join(INDICES_DIR, "mapa_carpetas.json")

def sincronizar_mapa_json():
    mapa_nuevo = {}
    archivos_db = glob.glob(os.path.join(INDICES_DIR, "*__part*.db"))
    
    for db_path in archivos_db:
        nombre_db = os.path.basename(db_path)
        conexion = None
        try:
            conexion = sqlite3.connect(db_path, timeout=10.0)
            cursor = conexion.cursor()
            
            cursor.execute('''
                SELECT carpeta, MIN(CAST(anio AS INTEGER)), MAX(CAST(anio AS INTEGER))
                FROM metadatos_pdf 
                WHERE anio != 'Desconocido' AND anio IS NOT NULL AND CAST(anio AS INTEGER) > 0
                GROUP BY carpeta
            ''')
            for carpeta, min_a, max_a in cursor.fetchall():
                if carpeta not in mapa_nuevo: mapa_nuevo[carpeta] = {}
                mapa_nuevo[carpeta][nombre_db] = {"min": int(min_a), "max": int(max_a)}
            
            cursor.execute("SELECT DISTINCT carpeta FROM metadatos_pdf WHERE anio = 'Desconocido'")
            for (carpeta,) in cursor.fetchall():
                if carpeta not in mapa_nuevo: mapa_nuevo[carpeta] = {}
                if nombre_db not in mapa_nuevo[carpeta]:
                    mapa_nuevo[carpeta][nombre_db] = {"min": 0, "max": 0} 
                    
        except sqlite3.OperationalError: pass
        finally:
            if conexion: conexion.close()
            
    with open(RUTA_MAPA, "w", encoding="utf-8") as f:
        json.dump(mapa_nuevo, f, ensure_ascii=False, indent=4)

detener_indexacion = False

# --- NUEVO: Variables para el Kill Switch de búsquedas ---
conexion_busqueda_activa = None
busqueda_cancelada = False

def detener_busqueda():
    """Interrumpe forzosamente cualquier consulta SQL en curso y libera los archivos."""
    global conexion_busqueda_activa, busqueda_cancelada
    busqueda_cancelada = True
    if conexion_busqueda_activa:
        try:
            conexion_busqueda_activa.interrupt()
        except Exception:
            pass
# ---------------------------------------------------------

def obtener_ruta_relativa(ruta_absoluta):
    try: return os.path.relpath(ruta_absoluta, BASE_DIR)
    except ValueError: return ruta_absoluta

def inicializar_db(db_path):
    conexion = sqlite3.connect(db_path, timeout=15.0)
    conexion.execute("PRAGMA journal_mode = WAL;")
    conexion.execute("PRAGMA synchronous = NORMAL;")
    conexion.execute("PRAGMA busy_timeout = 5000;") 
    
    cursor = conexion.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS info_db (clave TEXT PRIMARY KEY, valor TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS metadatos_pdf (ruta TEXT PRIMARY KEY, carpeta TEXT, anio TEXT, mtime REAL)''')
    
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS documentos USING fts5(
            ruta UNINDEXED, 
            pagina UNINDEXED, 
            anio UNINDEXED,
            mtime UNINDEXED,
            carpeta, 
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
            match = re.search(r'(18|19|20)\d{2}', os.path.basename(ruta_absoluta))
            if match: return match.group(0)
        elif metodo == "carpeta":
            match = re.search(r'(18|19|20)\d{2}', os.path.basename(os.path.dirname(ruta_absoluta)))
            if match: return match.group(0)
        elif metodo == "metadatos":
            meta = doc.metadata
            if meta and 'creationDate' in meta:
                match = re.search(r'(18|19|20)\d{2}', meta['creationDate'])
                if match: return match.group(0)
    except Exception: pass
    return "Desconocido"

def obtener_rango_anios():
    archivos_db = glob.glob(os.path.join(INDICES_DIR, "*__part*.db"))
    min_absoluto, max_absoluto = None, None
    for db_path in archivos_db:
        conexion = None
        try:
            conexion = sqlite3.connect(db_path, timeout=10.0)
            cursor = conexion.cursor()
            cursor.execute('''SELECT MIN(CAST(anio AS INTEGER)), MAX(CAST(anio AS INTEGER)) FROM metadatos_pdf WHERE anio != 'Desconocido' AND anio IS NOT NULL AND CAST(anio AS INTEGER) > 0''')
            res = cursor.fetchone()
            if res and res[0] is not None and res[1] is not None:
                min_db, max_db = int(res[0]), int(res[1])
                if min_absoluto is None or min_db < min_absoluto: min_absoluto = min_db
                if max_absoluto is None or max_db > max_absoluto: max_absoluto = max_db
        except sqlite3.OperationalError: pass
        finally:
            if conexion: conexion.close()
    return min_absoluto, max_absoluto

def obtener_archivos_ya_indexados_de_carpeta(nombre_base_db):
    archivos_indexados = {}
    for db_path in glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db")):
        conexion = None
        try:
            conexion = sqlite3.connect(db_path, timeout=10.0)
            for fila in conexion.execute("SELECT ruta, mtime FROM metadatos_pdf").fetchall():
                archivos_indexados[fila[0]] = (float(fila[1]) if fila[1] else 0.0, db_path)
        except sqlite3.OperationalError: pass
        finally:
            if conexion: conexion.close()
    return archivos_indexados

def obtener_carpetas_unicas():
    info_carpetas = {}
    for db_path in glob.glob(os.path.join(INDICES_DIR, "*__part*.db")):
        conexion = None
        try:
            conexion = sqlite3.connect(db_path, timeout=10.0)
            for carpeta, cantidad in conexion.execute("SELECT carpeta, COUNT(*) FROM metadatos_pdf GROUP BY carpeta").fetchall():
                carpeta_limpia = carpeta if carpeta else "raiz"
                info_carpetas[carpeta_limpia] = info_carpetas.get(carpeta_limpia, 0) + cantidad
        except sqlite3.OperationalError: pass
        finally:
            if conexion: conexion.close()
    return dict(sorted(info_carpetas.items()))

def borrar_indice():
    try:
        for f in glob.glob(os.path.join(INDICES_DIR, "*.db")): os.remove(f)
        return True
    except Exception as e: return str(e)

def borrar_indice_carpeta(ruta_carpeta):
    try:
        for db_path in glob.glob(os.path.join(INDICES_DIR, "*__part*.db")):
            conexion = None
            is_empty = False
            try:
                conexion = sqlite3.connect(db_path, timeout=15.0)
                cursor = conexion.cursor()
                if ruta_carpeta == "raiz": cursor.execute("SELECT ruta FROM metadatos_pdf WHERE carpeta = ''")
                else: cursor.execute("SELECT ruta FROM metadatos_pdf WHERE carpeta = ?", (ruta_carpeta,))
                    
                rutas_a_borrar = [r[0] for r in cursor.fetchall()]
                if rutas_a_borrar:
                    lote = 500
                    for i in range(0, len(rutas_a_borrar), lote):
                        chunk = rutas_a_borrar[i:i+lote]
                        placeholders = ", ".join(["?"] * len(chunk))
                        cursor.execute(f"DELETE FROM documentos WHERE ruta IN ({placeholders})", chunk)
                        cursor.execute(f"DELETE FROM metadatos_pdf WHERE ruta IN ({placeholders})", chunk)
                    conexion.commit()
                    conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
                    conexion.commit()
                cursor.execute("SELECT COUNT(*) FROM metadatos_pdf")
                if cursor.fetchone()[0] == 0: is_empty = True
            except Exception: pass
            finally:
                if conexion: conexion.close()
            if is_empty:
                try: os.remove(db_path)
                except OSError: pass
        return True
    except Exception as e: return str(e)

def indexar_documentos(carpeta_pdfs, metodo_anio="nombre_archivo", tamanio_max_mb=1024, callback_progreso=None):
    global detener_indexacion
    detener_indexacion = False 
    archivo_errores = os.path.join(BASE_DIR, "errores_indexacion.txt")
    archivo_mupdf_log = os.path.join(BASE_DIR, "log_pdfs_warnings.txt")
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)

    max_db_size_bytes = tamanio_max_mb * 1024 * 1024 
    ruta_raiz_relativa = obtener_ruta_relativa(os.path.abspath(carpeta_pdfs))
    hash_ruta = hashlib.md5(ruta_raiz_relativa.encode('utf-8')).hexdigest()[:8]
    nombre_base_db = f"{os.path.basename(ruta_raiz_relativa.rstrip(os.sep)) or 'raiz'}_{hash_ruta}"
    
    archivos_db_objetivo = glob.glob(os.path.join(INDICES_DIR, f"{nombre_base_db}__part*.db"))

    for db_path in archivos_db_objetivo:
        if detener_indexacion: break
        conexion = None
        is_empty = False
        try:
            conexion = sqlite3.connect(db_path, timeout=15.0)
            cursor = conexion.cursor()
            cursor.execute("SELECT ruta FROM metadatos_pdf")
            rutas_a_borrar = [(r[0],) for r in cursor.fetchall() if not os.path.exists(os.path.join(BASE_DIR, r[0]))]
            if rutas_a_borrar:
                cursor.executemany("DELETE FROM documentos WHERE ruta = ?", rutas_a_borrar)
                cursor.executemany("DELETE FROM metadatos_pdf WHERE ruta = ?", rutas_a_borrar)
                conexion.commit()
                conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
                conexion.commit()
            cursor.execute("SELECT COUNT(*) FROM metadatos_pdf")
            if cursor.fetchone()[0] == 0: is_empty = True
        except sqlite3.OperationalError: pass
        finally:
            if conexion: conexion.close()
        if is_empty:
            try: os.remove(db_path)
            except OSError: pass

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

    total_pdfs = sum(1 for raiz, _, archivos in os.walk(carpeta_pdfs) for a in archivos if a.lower().endswith('.pdf'))
    archivos_procesados, lote_size = 50, 50 
    archivos_nuevos_en_lote = 0
    ruta_carpeta_actual_en_proceso = ""
    archivos_en_subcarpeta_actual = 0
    
    try: 
        for raiz, _, archivos in os.walk(carpeta_pdfs):
            if detener_indexacion: break 
            pdfs_en_raiz = [a for a in archivos if a.lower().endswith('.pdf')]
            if not pdfs_en_raiz: continue
            
            ruta_carpeta_relativa = obtener_ruta_relativa(os.path.abspath(raiz))
            if ruta_carpeta_relativa != ruta_carpeta_actual_en_proceso:
                if ruta_carpeta_actual_en_proceso != "" and callback_progreso:
                    callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_actual_en_proceso, None, carpeta_terminada=True, total_carpeta=archivos_en_subcarpeta_actual)
                ruta_carpeta_actual_en_proceso = ruta_carpeta_relativa
                archivos_en_subcarpeta_actual = 0 
            
            for archivo in pdfs_en_raiz:
                if detener_indexacion: break 
                archivos_procesados += 1
                archivos_en_subcarpeta_actual += 1 
                ruta_absoluta = os.path.abspath(os.path.join(raiz, archivo))
                ruta_pdf_relativa = obtener_ruta_relativa(ruta_absoluta) 
                
                try: mtime_actual = os.path.getmtime(ruta_absoluta)
                except OSError: mtime_actual = 0.0

                es_modificado = False
                if ruta_pdf_relativa in archivos_ya_indexados:
                    mtime_guardado, db_donde_esta = archivos_ya_indexados[ruta_pdf_relativa]
                    if mtime_actual <= mtime_guardado:
                        if callback_progreso: callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_actual_en_proceso, None)
                        continue 
                    else:
                        es_modificado = True
                        conn_del = None
                        try:
                            conn_del = sqlite3.connect(db_donde_esta, timeout=15.0)
                            conn_del.execute("DELETE FROM documentos WHERE ruta = ?", (ruta_pdf_relativa,))
                            conn_del.execute("DELETE FROM metadatos_pdf WHERE ruta = ?", (ruta_pdf_relativa,))
                            conn_del.commit()
                        except: pass
                        finally:
                            if conn_del: conn_del.close()
                    
                try:
                    fitz.TOOLS.reset_mupdf_warnings()
                    doc = fitz.open(ruta_absoluta)
                    alertas_apertura = fitz.TOOLS.mupdf_warnings()
                    if alertas_apertura:
                        with open(archivo_mupdf_log, "a", encoding="utf-8") as f:
                            f.write(f"[APERTURA] Archivo: {ruta_absoluta} -> Detalles: {alertas_apertura.strip().replace(chr(10), ' | ')}\n")
                    if doc.needs_pass: raise Exception("Protegido con contraseña.")
                    
                    anio_doc = extraer_anio_multifuente(ruta_absoluta, doc, metodo_anio)
                    anio_para_ui = None if es_modificado else anio_doc

                    if callback_progreso: callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_relativa, anio_para_ui)
                    
                    cursor.execute(
                        "INSERT OR REPLACE INTO metadatos_pdf (ruta, carpeta, anio, mtime) VALUES (?, ?, ?, ?)",
                        (ruta_pdf_relativa, ruta_carpeta_relativa, anio_doc, mtime_actual)
                    )
                    
                    carpeta_fts = ruta_carpeta_relativa if ruta_carpeta_relativa else "raiz_directorio"

                    for num_pag, pagina in enumerate(doc):
                        fitz.TOOLS.reset_mupdf_warnings()
                        texto = pagina.get_text("text")
                        alertas_pagina = fitz.TOOLS.mupdf_warnings()
                        if alertas_pagina:
                            with open(archivo_mupdf_log, "a", encoding="utf-8") as f:
                                f.write(f"[PÁGINA {num_pag + 1}] Archivo: {ruta_absoluta} -> Detalles: {alertas_pagina.strip().replace(chr(10), ' | ')}\n")
                        
                        if texto.strip():
                            texto_procesado = limpiar_texto_basico(texto)
                            if len(texto_procesado) > 5:
                                cursor.execute(
                                    "INSERT INTO documentos (ruta, pagina, anio, mtime, carpeta, contenido) VALUES (?, ?, ?, ?, ?, ?)",
                                    (ruta_pdf_relativa, str(num_pag + 1), anio_doc, mtime_actual, carpeta_fts, texto_procesado)
                                )
                    doc.close()
                    archivos_nuevos_en_lote += 1
                    time.sleep(0.05)
                    
                    if archivos_nuevos_en_lote % lote_size == 0:
                        conexion.commit()
                        sincronizar_mapa_json()
                        if os.path.getsize(current_db_path) >= max_db_size_bytes: 
                            conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
                            conexion.commit()
                            conexion.close()
                            conexion = None 
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
            if not detener_indexacion:
                conexion.execute("INSERT INTO documentos(documentos) VALUES('optimize');")
                conexion.commit()
            if ruta_carpeta_actual_en_proceso != "" and callback_progreso:
                callback_progreso(archivos_procesados, total_pdfs, ruta_carpeta_actual_en_proceso, None, carpeta_terminada=True, total_carpeta=archivos_en_subcarpeta_actual)
    finally:
        if 'conexion' in locals() and conexion is not None:
            try: conexion.commit()
            except: pass
            conexion.close()
    sincronizar_mapa_json()

def buscar_texto(consulta_str, carpetas_permitidas=None, limite=50, offset=0, anio_min=None, anio_max=None, incluir_desconocidos=True, limite_maximo=10000, modo_busqueda="relevancia"):
    tiempo_inicio = time.time()
    
    # --- IMPLEMENTACIÓN DEL KILL SWITCH ---
    global conexion_busqueda_activa, busqueda_cancelada
    busqueda_cancelada = False
    
    if not carpetas_permitidas: return {"total": 0, "resultados": []}

    mapa = {}
    if os.path.exists(RUTA_MAPA):
        try:
            with open(RUTA_MAPA, "r", encoding="utf-8") as f:
                mapa = json.load(f)
        except Exception: pass

    dbs_a_consultar = {} 
    if mapa:
        db_info_map = {}
        for carpeta_mapa, dbs in mapa.items():
            for db_name, rangos in dbs.items():
                if db_name not in db_info_map: db_info_map[db_name] = {}
                db_info_map[db_name][carpeta_mapa] = rangos

        for db_name, carpetas_dict in db_info_map.items():
            db_path = os.path.join(INDICES_DIR, db_name)
            carpetas_admitidas = []
            todas_admitidas = True
            for carpeta_en_db, rangos in carpetas_dict.items():
                is_allowed = False
                for c_ui in carpetas_permitidas:
                    if c_ui == "raiz":
                        if "/" not in carpeta_en_db and "\\" not in carpeta_en_db:
                            is_allowed = True; break
                    else:
                        if carpeta_en_db == c_ui or carpeta_en_db.startswith(c_ui + "/") or carpeta_en_db.startswith(c_ui + "\\"):
                            is_allowed = True; break

                if is_allowed:
                    if anio_min is not None and anio_max is not None and not incluir_desconocidos:
                        db_min, db_max = rangos.get("min"), rangos.get("max")
                        if db_min is not None and db_max is not None and (anio_min <= db_max) and (anio_max >= db_min):
                            carpetas_admitidas.append(carpeta_en_db)
                        else: todas_admitidas = False
                    else: carpetas_admitidas.append(carpeta_en_db)
                else: todas_admitidas = False
            if carpetas_admitidas:
                dbs_a_consultar[db_path] = None if todas_admitidas else carpetas_admitidas
    else:
        for db in glob.glob(os.path.join(INDICES_DIR, "*__part*.db")):
            dbs_a_consultar[db] = carpetas_permitidas

    if not dbs_a_consultar: return {"total": 0, "resultados": []}

    total_hits = 0
    hits_por_db = []
    tope_conteo = limite_maximo if modo_busqueda == "relevancia" else (offset + limite + 1)

    for db_path, filter_folders in dbs_a_consultar.items():
        if total_hits >= tope_conteo or busqueda_cancelada: break 
            
        conexion = None
        try:
            conexion = sqlite3.connect(db_path, timeout=10.0)
            conexion_busqueda_activa = conexion # <- Guardar estado
            cursor = conexion.cursor()
            
            fts_query = consulta_str
            if filter_folders is not None:
                clausulas_carpeta = []
                for c in filter_folders:
                    c_fts = c if c != "raiz" else "raiz_directorio"
                    clausulas_carpeta.append(f'"{c_fts}"')
                str_carpetas = " OR ".join(clausulas_carpeta)
                fts_query = f'carpeta : ({str_carpetas}) AND ({consulta_str})'
            
            query_base = "SELECT count(*) FROM (SELECT 1 FROM documentos WHERE documentos MATCH ?"
            params = [fts_query]

            if anio_min is not None and anio_max is not None:
                if incluir_desconocidos:
                    query_base += " AND ( (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ?) OR anio = 'Desconocido' )"
                else:
                    query_base += " AND (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ? AND anio != 'Desconocido')"
                params.extend([anio_min, anio_max])

            # ¡RECUPERAMOS LA INSTRUCCIÓN LIMIT VITAL!
            query_base += f" LIMIT {tope_conteo - total_hits})"

            cursor.execute(query_base, params)
            count = cursor.fetchone()[0]
            
            if count > 0:
                hits_por_db.append({"db": db_path, "count": count, "fts_query": fts_query})
                total_hits += count
                
            if modo_busqueda == "relevancia" and total_hits > limite_maximo:
                return {"excede_limite": True, "total": f"+{limite_maximo}", "limite_maximo": limite_maximo}

        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                return {"total": 0, "resultados": [], "cancelada": True}
            return {"error": f"Error FTS5: {e}"}
        finally:
            conexion_busqueda_activa = None # <- Liberar
            if conexion: conexion.close()

    if total_hits == 0 or busqueda_cancelada: return {"total": 0, "resultados": []}

    resultados = []
    offset_restante, limite_restante = offset, limite

    for db_info in hits_por_db:
        if limite_restante <= 0 or busqueda_cancelada: break 
        if offset_restante >= db_info["count"]:
            offset_restante -= db_info["count"]
            continue

        conexion = None
        try:
            conexion = sqlite3.connect(db_info["db"], timeout=10.0)
            conexion_busqueda_activa = conexion # <- Guardar estado
            cursor = conexion.cursor()
            
            query_search = '''
                SELECT ruta, pagina, snippet(documentos, 5, '<b>', '</b>', '...', 60), anio 
                FROM documentos 
                WHERE documentos MATCH ? 
            '''
            params_search = [db_info["fts_query"]]
            
            if anio_min is not None and anio_max is not None:
                if incluir_desconocidos:
                    query_search += " AND ( (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ?) OR anio = 'Desconocido' )"
                else:
                    query_search += " AND (CAST(anio AS INTEGER) >= ? AND CAST(anio AS INTEGER) <= ? AND anio != 'Desconocido')"
                params_search.extend([anio_min, anio_max])
                
            if modo_busqueda == "relevancia": query_search += " ORDER BY rank LIMIT ? OFFSET ?"
            else: query_search += " LIMIT ? OFFSET ?"
                
            params_search.extend([limite_restante, offset_restante])
            
            cursor.execute(query_search, params_search)
            filas = cursor.fetchall()

            for r in filas:
                resultados.append({"ruta": r[0], "pagina": r[1], "extracto": r[2], "anio": r[3]})

            limite_restante -= len(filas)
            offset_restante = 0 
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                return {"total": 0, "resultados": [], "cancelada": True}
            pass 
        finally:
            conexion_busqueda_activa = None # <- Liberar
            if conexion: conexion.close()

    tiempo_fin = time.time()
    tiempo_total = round(tiempo_fin - tiempo_inicio, 4)
    
    return {"total": total_hits, "resultados": resultados, "tiempo": tiempo_total}
