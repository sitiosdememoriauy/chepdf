VERSION = "1.7.1"

import webbrowser
import flet as ft
import motor_sqlite
import os
import threading
import math
import re
import pathlib
import tempfile
import urllib.parse
import json
import locale
import time
import multiprocessing
import sys
import unicodedata
import asyncio
import tkinter as tk
import certifi

# Le indicamos a Python que use los certificados locales de Mozilla
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['WEBSOCKET_CLIENT_CA_BUNDLE'] = certifi.where()

from tkinter import filedialog

from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableRow, TableCell
from odf.text import P, Span
from odf.style import Style, TextProperties

CONFIG_FILE = os.path.join(motor_sqlite.BASE_DIR, "config.json")

def obtener_idioma_sistema():
    try:
        idioma_local, _ = locale.getlocale()
        if idioma_local is None:
            idioma_local = os.environ.get('LANG', os.environ.get('LANGUAGE', ''))
        if idioma_local and idioma_local.lower().startswith('es'): return 'es'
        return 'en'
    except Exception: return 'es'

def cargar_temas():
    import os
    import sys
    if getattr(sys, 'frozen', False):
        ruta_actual = os.path.dirname(sys.executable)
    else:
        ruta_actual = os.path.dirname(os.path.abspath(__file__))

    ruta_temas = os.path.join(ruta_actual, "themes.json")
    
    temas_default = {
        "dark": {"nombre": "Oscuro", "modo": "dark", "seed_color": "blue"},
        "light": {"nombre": "Claro", "modo": "light", "seed_color": "blue"}
    }
    
    if os.path.exists(ruta_temas):
        import json
        try:
            with open(ruta_temas, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e: 
            print(f"\n⚠️ ATENCIÓN: Se encontró themes.json pero falló la lectura. Error: {e}\n")
    else:
        print(f"\n⚠️ ATENCIÓN: No existe el archivo en la ruta: {ruta_temas}\n")
            
    return temas_default

# Cargamos el diccionario a la memoria global
diccionario_temas = cargar_temas()

def cargar_config():
    config_default = {
        "metodo_anio": "nombre_archivo", 
        "limite_resultados": 1000,
        "idioma": obtener_idioma_sistema(),
        "tamanio_max_db": 2048,
        "modo_busqueda": "rapida",
        "modo_visualizacion": "web",
        "tema_visual": "dark"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: 
                config_guardada = json.load(f)
                config_default.update(config_guardada)
                return config_default
        except Exception: pass
    return config_default

def guardar_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: 
        json.dump(config, f)

def cargar_idioma(codigo_idioma):
    ruta_locale = os.path.join(motor_sqlite.BASE_DIR, "locales", f"{codigo_idioma}.json")
    try:
        with open(ruta_locale, 'r', encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: return {}

def main(page: ft.Page):
    async def al_desconectar(e):
        # Aseguramos que los procesos pesados se detengan
        motor_sqlite.detener_indexacion = True
        motor_sqlite.detener_busqueda()
        
        # Un pequeño respiro para que los hilos cierren archivos si es necesario
        await asyncio.sleep(0.5)
        
        # Matamos el proceso para devolver el control al prompt
        os._exit(0)

    page.on_disconnect = al_desconectar
    # ----------------------------------------------------

    config_app = cargar_config()
    
    # --- APLICAR TEMA AL INICIO ---
    tema_guardado = config_app.get("tema_visual", "dark")
    tema_info = diccionario_temas.get(tema_guardado, diccionario_temas["dark"])
    
    page.theme_mode = ft.ThemeMode.DARK if tema_info["modo"] == "dark" else ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=tema_info["seed_color"])
    # ------------------------------

    page.window.prevent_close = True

    async def al_cerrar_ventana(e):
        evento_str = f"{getattr(e, 'data', '')} {getattr(e, 'type', '')}".lower()
        
        if "close" in evento_str:
            motor_sqlite.detener_indexacion = True
            motor_sqlite.detener_busqueda()
            
            if not page.web:
                page.window.prevent_close = False
                page.window.visible = False
                page.update()
                
                try:
                    await page.window.close() 
                except Exception:
                    pass
                
                await asyncio.sleep(0.1)
                os._exit(0)
            else:
                try:
                    await page.window.close()
                except Exception:
                    pass

    page.window.on_event = al_cerrar_ventana

    diccionario_textos = cargar_idioma(config_app.get("idioma", "es"))
    def t(clave): return diccionario_textos.get(clave, clave)

    page.title = t("app_titulo")
    page.window.icon = "icono_che.ico" 
    page.padding = 10 
    
    estado_busqueda = {"pagina_actual": 1, "resultados_por_pagina": 50, "total_paginas": 1}
    estado_app = {"hilo_indexacion": None, "mostrar_rutas": False}

    # CAMBIO A COLORES SEMÁNTICOS
    txt_estado_indexacion = ft.Text(t("estado_reposo"), italic=True, color="primary", size=13)
    txt_estado_busqueda = ft.Text("", italic=True, color="onSurfaceVariant", size=13)

    lista_checkboxes = ft.ListView(expand=True, spacing=5)
    txt_rango_anios = ft.Text(t("lbl_filtro_temporal_calc"), weight="bold", size=16)
    
    def on_slider_change(e):
        txt_rango_anios.value = t("lbl_rango_anos").format(int(slider_anios.start_value), int(slider_anios.end_value))
        page.update()

    slider_anios = ft.RangeSlider(
        min=1900, max=2030, start_value=1900, end_value=2030, divisions=130, label="{value}",
        disabled=True, on_change=on_slider_change, active_color="primary", inactive_color="surfaceVariant"
    )
    
    check_desconocidos = ft.Checkbox(label=t("lbl_incluir_sin_ano"), value=False, disabled=True)

    def actualizar_filtros_ui():
        estado_previo = {cb.data: cb.value for cb in lista_checkboxes.controls}
        info_carpetas = motor_sqlite.obtener_carpetas_unicas()
        lista_checkboxes.controls.clear()
        
        for ruta_completa, cantidad in info_carpetas.items():
            valor = estado_previo.get(ruta_completa, True)
            texto_mostrar = ruta_completa if estado_app["mostrar_rutas"] else os.path.basename(ruta_completa.rstrip(os.sep)) or t("lbl_raiz")
            lista_checkboxes.controls.append(ft.Checkbox(label=t("lbl_carpeta_con_total").format(texto_mostrar, cantidad), value=valor, data=ruta_completa, tooltip=ruta_completa))
        
        min_anio, max_anio = motor_sqlite.obtener_rango_anios()
        if min_anio and max_anio:
            if min_anio == max_anio:
                slider_anios.min = min_anio - 1
                slider_anios.max = max_anio + 1
                slider_anios.divisions = 2
            else:
                slider_anios.min = min_anio
                slider_anios.max = max_anio
                slider_anios.divisions = max_anio - min_anio

            if slider_anios.disabled or slider_anios.start_value < slider_anios.min or slider_anios.end_value > slider_anios.max:
                slider_anios.start_value = slider_anios.min
                slider_anios.end_value = slider_anios.max

            slider_anios.disabled = False
            check_desconocidos.disabled = False
            txt_rango_anios.value = t("lbl_rango_anos").format(int(slider_anios.start_value), int(slider_anios.end_value))
        else:
            slider_anios.min = 1900; slider_anios.max = 2030
            slider_anios.start_value = 1900; slider_anios.end_value = 2030
            slider_anios.divisions = 130
            slider_anios.disabled = True
            check_desconocidos.disabled = True
            txt_rango_anios.value = t("lbl_filtro_temporal_sin_datos")
        page.update()

    actualizar_filtros_ui()

    def seleccionar_todas(e):
        for cb in lista_checkboxes.controls: cb.value = True
        page.update()

    def deseleccionar_todas(e):
        for cb in lista_checkboxes.controls: cb.value = False
        page.update()

    def detener_proceso(e):
        motor_sqlite.detener_indexacion = True
        txt_estado_indexacion.value = t("msg_deteniendo_segura")
        btn_detener.disabled = True
        btn_detener.icon_color = "onSurfaceVariant" 
        page.update()

    btn_detener = ft.IconButton(icon=ft.Icons.STOP, icon_color="onSurfaceVariant", icon_size=30, tooltip=t("tooltip_detener_index"), disabled=True, on_click=detener_proceso)

    def abrir_dialogo_carpeta_nativo(e):
        root = tk.Tk()
        root.withdraw() 
        root.attributes('-topmost', True) 
        
        ruta = filedialog.askdirectory(title="Selecciona la carpeta a indexar")
        root.destroy() 
        
        if ruta:
            def tarea_indexar():
                nombre_carpeta = os.path.basename(ruta)
                txt_estado_indexacion.value = t("msg_calculando_archivos").format(nombre_carpeta)
                
                btn_indexar.disabled = True
                btn_indexar.icon_color = "onSurfaceVariant"  
                
                btn_borrar_indice.disabled = True 
                btn_borrar_indice.icon_color = "onSurfaceVariant" 
                btn_detener.disabled = False
                btn_detener.icon_color = "error"        
                page.update()
                
                def actualizar_interfaz(actual, total, ruta_carpeta_relativa, anio_doc=None, carpeta_terminada=False, total_carpeta=0):
                    if carpeta_terminada:
                        for cb in lista_checkboxes.controls:
                            if cb.data == ruta_carpeta_relativa:
                                texto_mostrar = ruta_carpeta_relativa if estado_app["mostrar_rutas"] else os.path.basename(ruta_carpeta_relativa.rstrip(os.sep))
                                cb.label = t("lbl_carpeta_con_total").format(texto_mostrar, total_carpeta)
                                page.update()
                                break

                    txt_estado_indexacion.value = t("msg_indexando_progreso").format(os.path.basename(ruta_carpeta_relativa), actual, total)
                    
                    carpetas_ui = [cb.data for cb in lista_checkboxes.controls]
                    if ruta_carpeta_relativa and ruta_carpeta_relativa not in carpetas_ui:
                        texto_mostrar = ruta_carpeta_relativa if estado_app["mostrar_rutas"] else os.path.basename(ruta_carpeta_relativa.rstrip(os.sep))
                        lista_checkboxes.controls.append(ft.Checkbox(label=t("lbl_indexando_puntos").format(texto_mostrar), value=True, data=ruta_carpeta_relativa, tooltip=ruta_carpeta_relativa))
                        lista_checkboxes.controls.sort(key=lambda x: x.data.lower())
                    
                    if anio_doc and anio_doc != "Desconocido":
                        try:
                            anio_int = int(anio_doc)
                            cambio = False
                            if slider_anios.disabled:
                                slider_anios.min = anio_int - 1; slider_anios.max = anio_int + 1
                                slider_anios.start_value = anio_int; slider_anios.end_value = anio_int
                                slider_anios.disabled = False; check_desconocidos.disabled = False
                                cambio = True
                            else:
                                if anio_int < slider_anios.min: slider_anios.min = anio_int; slider_anios.start_value = anio_int; cambio = True
                                if anio_int > slider_anios.max: slider_anios.max = anio_int; slider_anios.end_value = anio_int; cambio = True
                                    
                            if cambio:
                                divisiones = int(slider_anios.max - slider_anios.min)
                                slider_anios.divisions = divisiones if divisiones > 0 else 2
                                txt_rango_anios.value = t("lbl_rango_anos").format(int(slider_anios.start_value), int(slider_anios.end_value))
                        except ValueError: pass
                    if actual % 10 == 0 or actual == total: page.update()
                
                motor_sqlite.indexar_documentos(
                    ruta, 
                    metodo_anio=config_app.get("metodo_anio", "nombre_archivo"), 
                    tamanio_max_mb=config_app.get("tamanio_max_db", 1024),
                    callback_progreso=actualizar_interfaz
                )
                
                if motor_sqlite.detener_indexacion: txt_estado_indexacion.value = t("msg_indexacion_abortada")
                else: txt_estado_indexacion.value = t("msg_index_exito").format(nombre_carpeta)
                
                btn_indexar.disabled = False
                btn_indexar.icon_color = "primary"
                
                btn_borrar_indice.disabled = False 
                btn_borrar_indice.icon_color = "error" 
                btn_detener.disabled = True
                btn_detener.icon_color = "onSurfaceVariant" 
                actualizar_filtros_ui()
                
            estado_app["hilo_indexacion"] = threading.Thread(target=tarea_indexar, daemon=True)
            estado_app["hilo_indexacion"].start()

    btn_indexar = ft.IconButton(
        icon=ft.Icons.CREATE_NEW_FOLDER, 
        icon_size=30, 
        icon_color="primary", 
        tooltip=t("tooltip_indexar_carpeta"), 
        on_click=abrir_dialogo_carpeta_nativo
    )

    texto_advertencia = ft.Text("")
    dropdown_borrar = ft.Dropdown(label=t("lbl_que_deseas_borrar"), options=[], width=350)
    check_confirmacion = ft.Checkbox(label=t("lbl_accion_irreversible"))
    btn_confirmar_borrado = ft.TextButton(content=ft.Text(t("btn_borrar")), style=ft.ButtonStyle(color="error"), disabled=True)
    btn_cancelar_borrado = ft.TextButton(content=ft.Text(t("btn_cancelar")), on_click=lambda e: cerrar_dialogo())

    def on_checkbox_change(e):
        btn_confirmar_borrado.disabled = not check_confirmacion.value
        page.update()
    check_confirmacion.on_change = on_checkbox_change

    def cerrar_dialogo(e=None):
        dlg_borrar.open = False
        page.update()

    def ejecutar_borrado(e):
        seleccion = dropdown_borrar.value
        if not seleccion: return
        if seleccion == t("opt_todas_carpetas"):
            resultado = motor_sqlite.borrar_indice()
            msj = t("msg_indice_borrado_todo")
        else:
            resultado = motor_sqlite.borrar_indice_carpeta(seleccion)
            msj = t("msg_indice_borrado_carpeta").format(seleccion)
        
        dlg_borrar.open = False
        
        if resultado is True:
            txt_estado_indexacion.value = msj
            actualizar_filtros_ui() 
            lista_resultados.controls.clear()
            fila_paginador.visible = False
            contenedor_cargar_mas.visible = False
            btn_exportar.visible = False 
        else: 
            txt_estado_indexacion.value = t("msg_error_borrado").format(resultado)
            
        page.update()

    btn_confirmar_borrado.on_click = ejecutar_borrado

    dlg_borrar = ft.AlertDialog(
        modal=True,
        title=ft.Text(t("lbl_gestion_indice")),
        content=ft.Column([texto_advertencia, dropdown_borrar, ft.Divider(), check_confirmacion], tight=True),
        actions=[btn_cancelar_borrado, btn_confirmar_borrado],
        actions_alignment="end"
    )

    def abrir_dialogo_borrado(e):
        info_carpetas = motor_sqlite.obtener_carpetas_unicas()
        if not info_carpetas:
            texto_advertencia.value = t("msg_indice_vacio")
            dropdown_borrar.visible = False
            check_confirmacion.visible = False
            btn_confirmar_borrado.visible = False
        else:
            texto_advertencia.value = t("msg_selecciona_borrar")
            opciones = [ft.dropdown.Option(t("opt_todas_carpetas"))]
            for c in info_carpetas.keys(): opciones.append(ft.dropdown.Option(c))
            dropdown_borrar.options = opciones
            dropdown_borrar.value = t("opt_todas_carpetas")  
            dropdown_borrar.visible = True
            check_confirmacion.visible = True
            check_confirmacion.value = False
            btn_confirmar_borrado.visible = True
            btn_confirmar_borrado.disabled = True
            
        page.show_dialog(dlg_borrar)
        page.update()

    btn_salir = ft.Button(content=ft.Text(t("btn_salir")), icon=ft.Icons.EXIT_TO_APP)

    async def salir_app(e):
        hilo = estado_app["hilo_indexacion"]
        if hilo and hilo.is_alive():
            motor_sqlite.detener_indexacion = True
            txt_estado_indexacion.value = t("msg_cerrando_app")
            btn_indexar.disabled = True
            btn_detener.disabled = True
            btn_borrar_indice.disabled = True
            btn_salir.disabled = True
            page.update()
            hilo.join(timeout=2)
            
        if page.web:
            txt_estado_indexacion.value = "Sistema desconectado. Ya puedes cerrar esta pestaña con seguridad."
            page.update()
        else:
            page.window.prevent_close = False
            page.window.visible = False
            page.update()
            
            try:
                await page.window.close()
            except Exception:
                pass
                
            await asyncio.sleep(0.1)
            os._exit(0)

    btn_salir.on_click = salir_app

    btn_borrar_indice = ft.IconButton(icon=ft.Icons.DELETE_FOREVER, icon_size=30, icon_color="error", tooltip=t("tooltip_borrar_indice"), on_click=abrir_dialogo_borrado)

    def alternar_vista_rutas(e):
        estado_app["mostrar_rutas"] = not estado_app["mostrar_rutas"]
        e.control.icon = ft.Icons.VISIBILITY if estado_app["mostrar_rutas"] else ft.Icons.VISIBILITY_OFF
        e.control.tooltip = t("tooltip_ocultar_rutas") if estado_app["mostrar_rutas"] else t("tooltip_mostrar_rutas")
        actualizar_filtros_ui()
    btn_alternar_vista = ft.IconButton(icon=ft.Icons.VISIBILITY_OFF, tooltip=t("tooltip_mostrar_rutas"), on_click=alternar_vista_rutas)

    txt_lbl_indexar_carpetas = ft.Text(t("lbl_indexar_carpetas"), weight="bold", size=16)
    txt_lbl_filtro_carpetas = ft.Text(t("lbl_filtro_carpetas"), weight="bold", size=16)
    btn_todas = ft.TextButton(content=ft.Text(t("btn_todas")), on_click=seleccionar_todas)
    btn_ninguna = ft.TextButton(content=ft.Text(t("btn_ninguna")), on_click=deseleccionar_todas)

    barra_lateral = ft.Container(
        width=250, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column([
            txt_lbl_indexar_carpetas, ft.Row([btn_indexar, btn_detener, btn_borrar_indice], alignment=ft.MainAxisAlignment.START, spacing=15),
            ft.Divider(), txt_rango_anios, slider_anios, check_desconocidos, ft.Divider(),
            ft.Row([txt_lbl_filtro_carpetas, btn_alternar_vista], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([btn_todas, btn_ninguna]), ft.Divider(), lista_checkboxes, ft.Divider(), btn_salir
        ])
    )

    def mover_divisor(e: ft.DragUpdateEvent):
        nuevo_ancho = barra_lateral.width + e.local_delta.x
        if 150 <= nuevo_ancho <= 600: 
            barra_lateral.width = nuevo_ancho
            page.update()

    divisor_movil = ft.GestureDetector(
        mouse_cursor=ft.MouseCursor.RESIZE_COLUMN, on_pan_update=mover_divisor,
        content=ft.Container(width=10, bgcolor="transparent", content=ft.VerticalDivider(width=1, color="outlineVariant"))
    )

    def sanitizar_nombre(texto):
        texto_limpio = unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8')
        texto_limpio = texto_limpio.lower()
        texto_limpio = re.sub(r'[^a-z0-9]+', '-', texto_limpio)
        texto_limpio = texto_limpio[:10].strip('-')
        return texto_limpio if texto_limpio else "export"

    def abrir_dialogo_exportar_nativo(e):
        datos = btn_exportar.data
        if not datos: return
        
        palabra_saneada = sanitizar_nombre(datos["consulta"])
        total_hits = datos["total"]
        nombre_sugerido = f"chepdf-{palabra_saneada}-{total_hits}.ods"
        
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True) 
        
        ruta_destino = filedialog.asksaveasfilename(
            title="Guardar resultados como...",
            initialfile=nombre_sugerido,
            defaultextension=".ods",
            filetypes=[("OpenDocument Spreadsheet", "*.ods")]
        )
        
        root.destroy()
        
        if ruta_destino: 
            exportar_resultados_ods(ruta_destino)

    def exportar_resultados_ods(ruta_destino):
        txt_estado_busqueda.value = t("msg_calculando_resultados") if "msg_calculando_resultados" in diccionario_textos else "Exportando resultados, por favor espera..."
        btn_exportar.disabled = True
        page.update()
        
        consulta = txt_busqueda.value
        carpetas_seleccionadas = [cb.data for cb in lista_checkboxes.controls if cb.value]
        anio_min = int(slider_anios.start_value) if not slider_anios.disabled else None
        anio_max = int(slider_anios.end_value) if not slider_anios.disabled else None
        incluir_desc = check_desconocidos.value
        modo_actual = config_app.get("modo_busqueda", "relevancia")
        limite_max = int(config_app.get("limite_resultados", 10000))

        respuesta = motor_sqlite.buscar_texto(
            consulta_str=consulta, carpetas_permitidas=carpetas_seleccionadas,
            limite=limite_max, offset=0, anio_min=anio_min, anio_max=anio_max,
            incluir_desconocidos=incluir_desc, limite_maximo=limite_max, modo_busqueda=modo_actual
        )

        if respuesta.get("cancelada"):
            txt_estado_busqueda.value = "Exportación cancelada por el usuario."
            btn_exportar.disabled = False
            page.update()
            return

        try:
            doc = OpenDocumentSpreadsheet()
            style_highlight = Style(name="HitHighlight", family="text")
            style_highlight.addElement(TextProperties(color="#d32f2f", fontweight="bold"))
            doc.automaticstyles.addElement(style_highlight)

            table = Table(name="Resultados")
            doc.spreadsheet.addElement(table)

            tr_head = TableRow()
            for col in ["Carpeta", "Archivo", "Página", "Año", "Palabra Buscada", "Snippet"]:
                tc = TableCell()
                tc.addElement(P(text=col))
                tr_head.addElement(tc)
            table.addElement(tr_head)

            for res in respuesta.get("resultados", []):
                tr = TableRow()
                ruta_completa = res['ruta']
                carpeta = os.path.dirname(ruta_completa)
                nombre_archivo = os.path.basename(ruta_completa)
                if not carpeta: carpeta = "Raíz"
                
                datos_basicos = [carpeta, nombre_archivo, res['pagina'], res['anio'], consulta]
                for val in datos_basicos:
                    tc = TableCell()
                    tc.addElement(P(text=str(val)))
                    tr.addElement(tc)
                    
                tc_snippet = TableCell()
                p_snippet = P()
                fragmentos = re.split(r'(<b>.*?</b>)', res['extracto'])
                for frag in fragmentos:
                    if frag.startswith('<b>') and frag.endswith('</b>'):
                        span_hit = Span(stylename=style_highlight, text=frag[3:-4])
                        p_snippet.addElement(span_hit)
                    elif frag: p_snippet.addText(frag)
                        
                tc_snippet.addElement(p_snippet)
                tr.addElement(tc_snippet)
                table.addElement(tr)

            doc.save(ruta_destino)
            txt_estado_busqueda.value = f"¡Exportación exitosa! {len(respuesta.get('resultados', []))} resultados guardados en ODS."
        except Exception as ex:
            txt_estado_busqueda.value = f"Error al exportar: {ex}"
            txt_estado_busqueda.color = "error"
            
        btn_exportar.disabled = False
        page.update()

    btn_exportar = ft.Button(
        content=ft.Text(t("btn_exportar") if "btn_exportar" in diccionario_textos else "Exportar ODS"), 
        icon=ft.Icons.TABLE_VIEW, visible=False, on_click=abrir_dialogo_exportar_nativo
    )

    txt_busqueda = ft.TextField(label=t("lbl_buscar_ejemplo"), expand=True, on_submit=lambda e: ejecutar_busqueda(nueva_busqueda=True))
    btn_buscar = ft.Button(content=ft.Text(t("btn_buscar")), icon=ft.Icons.SEARCH, on_click=lambda e: ejecutar_busqueda(nueva_busqueda=True))
    
    btn_detener_busqueda = ft.IconButton(
        icon=ft.Icons.STOP_CIRCLE, 
        icon_color="error", 
        icon_size=30,
        visible=False,
        tooltip="Detener búsqueda",
        on_click=lambda e: motor_sqlite.detener_busqueda()
    )
    
    lista_resultados = ft.ListView(expand=True, spacing=10, padding=10)
    btn_anterior = ft.Button(content=ft.Text(t("btn_anterior")), icon=ft.Icons.ARROW_BACK, on_click=lambda e: cambiar_pagina(-1))
    btn_siguiente = ft.Button(content=ft.Text(t("btn_siguiente")), icon=ft.Icons.ARROW_FORWARD, on_click=lambda e: cambiar_pagina(1))
    txt_paginacion = ft.Text(t("lbl_pagina_1_de_1"), weight="bold")
    fila_paginador = ft.Row(controls=[btn_anterior, txt_paginacion, btn_siguiente], alignment=ft.MainAxisAlignment.CENTER, visible=False)

    btn_cargar_mas = ft.Button(
        content=ft.Text(t("btn_cargar_mas") if "btn_cargar_mas" in diccionario_textos else "Cargar más resultados..."), 
        icon=ft.Icons.DOWNLOADING, on_click=lambda e: cambiar_pagina(1), style=ft.ButtonStyle(bgcolor="primary", color="onPrimary")
    )
    contenedor_cargar_mas = ft.Row([btn_cargar_mas], alignment=ft.MainAxisAlignment.CENTER, visible=False)

    def abrir_pdf(ruta_guardada, pagina, termino_busqueda=""):
        if not os.path.isabs(ruta_guardada): 
            ruta_real = os.path.join(motor_sqlite.BASE_DIR, ruta_guardada)
        else: 
            ruta_real = ruta_guardada
            
        try:
            if not os.path.exists(ruta_real):
                txt_estado_busqueda.value = "Error: El archivo ya no existe en esa ruta. Te sugiero reindexar la carpeta."
                txt_estado_busqueda.color = "error"
                page.update()
                return

            url_base = pathlib.Path(ruta_real).as_uri()
            if termino_busqueda: 
                url_final = f"{url_base}#page={pagina}&search={urllib.parse.quote(termino_busqueda)}"
            else: 
                url_final = f"{url_base}#page={pagina}"
            
            # Restauramos el puente HTML
            temp_dir = tempfile.gettempdir()
            html_path = os.path.join(temp_dir, "puente_visor_forense.html")
            texto_abriendo = t("msg_abriendo_html").format(pagina)
            
            bg_color = "#ffffff" if page.theme_mode == ft.ThemeMode.LIGHT else "#1e1e1e"
            txt_color = "#1e1e1e" if page.theme_mode == ft.ThemeMode.LIGHT else "#ffffff"
            
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(f'''<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0; url={url_final}"></head>
                <body style="background-color: {bg_color}; color: {txt_color}; display: flex; justify-content: center; align-items: center; height: 100vh;">
                    <h2>{texto_abriendo}</h2>
                    <script>window.focus();</script>
                </body></html>''')
            
            # Abrimos el HTML directamente con el OS. 
            # Esto evita el bloqueo de seguridad y mantiene los parámetros vivos.
            ruta_puente_uri = pathlib.Path(html_path).as_uri()
            webbrowser.open(ruta_puente_uri)
            
        except Exception as ex:
            txt_estado_busqueda.value = t("msg_error_abrir").format(ex)
            page.update()

    def cambiar_pagina(delta):
        estado_busqueda["pagina_actual"] += delta
        ejecutar_busqueda(nueva_busqueda=False)

    def ejecutar_busqueda(nueva_busqueda=True):
        consulta = txt_busqueda.value
        if not consulta: return

        modo_actual = config_app.get("modo_busqueda", "relevancia")

        if nueva_busqueda: estado_busqueda["pagina_actual"] = 1
        if nueva_busqueda or modo_actual == "relevancia": lista_resultados.controls.clear()
            
        txt_estado_busqueda.value = t("msg_calculando_resultados")
        txt_estado_busqueda.color = "onSurfaceVariant"
        fila_paginador.visible = False
        contenedor_cargar_mas.visible = False
        btn_exportar.visible = False 
        
        btn_buscar.visible = False
        btn_detener_busqueda.visible = True
        page.update()

        carpetas_seleccionadas = [cb.data for cb in lista_checkboxes.controls if cb.value]
        if not carpetas_seleccionadas:
            txt_estado_busqueda.value = t("msg_selecciona_carpeta")
            btn_buscar.visible = True
            btn_detener_busqueda.visible = False
            page.update()
            return

        offset_actual = (estado_busqueda["pagina_actual"] - 1) * estado_busqueda["resultados_por_pagina"]
        anio_min = int(slider_anios.start_value) if not slider_anios.disabled else None
        anio_max = int(slider_anios.end_value) if not slider_anios.disabled else None
        incluir_desc = check_desconocidos.value
        limite_max = int(config_app.get("limite_resultados", 10000))

        respuesta = motor_sqlite.buscar_texto(
            consulta_str=consulta, carpetas_permitidas=carpetas_seleccionadas,
            limite=estado_busqueda["resultados_por_pagina"], offset=offset_actual,
            anio_min=anio_min, anio_max=anio_max, incluir_desconocidos=incluir_desc,
            limite_maximo=limite_max, modo_busqueda=modo_actual
        )

        btn_buscar.visible = True
        btn_detener_busqueda.visible = False

        if respuesta.get("cancelada"):
            txt_estado_busqueda.value = "Búsqueda cancelada por el usuario."
            txt_estado_busqueda.color = "error"
            page.update()
            return

        if "error" in respuesta:
            txt_estado_busqueda.value = t("msg_error_sintaxis")
            txt_estado_busqueda.color = "error"
            btn_exportar.visible = False
            page.update()
            return
            
        if respuesta.get("excede_limite"):
            txt_estado_busqueda.value = t("msg_limite_excedido").format(limite_max, respuesta['total'])
            txt_estado_busqueda.color = "error"
            btn_exportar.visible = False
            page.update()
            return

        total_hits = respuesta["total"]
        if total_hits == 0:
            txt_estado_busqueda.value = t("msg_sin_resultados")
            txt_estado_busqueda.color = "onSurfaceVariant"
            btn_exportar.visible = False
        else:
            txt_estado_busqueda.color = "onSurfaceVariant"
            btn_exportar.visible = True
            btn_exportar.data = {"consulta": consulta, "total": total_hits}
            estado_busqueda["total_paginas"] = math.ceil(total_hits / estado_busqueda["resultados_por_pagina"])
            tiempo_segundos = respuesta.get("tiempo", 0)
            
            if modo_actual == "relevancia":
                texto_exito = t("msg_busqueda_exito").format(total_hits, estado_busqueda['pagina_actual'])
                txt_estado_busqueda.value = f"{texto_exito} (en {tiempo_segundos} seg)" 
                txt_paginacion.value = t("lbl_paginacion").format(estado_busqueda['pagina_actual'], estado_busqueda['total_paginas'])
                btn_anterior.disabled = (estado_busqueda["pagina_actual"] == 1)
                btn_siguiente.disabled = (estado_busqueda["pagina_actual"] >= estado_busqueda["total_paginas"])
                fila_paginador.visible = True
            else:
                resultados_cargados = len(lista_resultados.controls) + len(respuesta["resultados"])
                txt_estado_busqueda.value = f"Mostrando {resultados_cargados} resultados (Carga rápida - en {tiempo_segundos} seg)"
                if respuesta["total"] > (offset_actual + estado_busqueda["resultados_por_pagina"]): contenedor_cargar_mas.visible = True
                else: contenedor_cargar_mas.visible = False
            
            for res in respuesta["resultados"]:
                fragmentos = re.split(r'(<b>.*?</b>)', f"...{res['extracto']}...")
                spans_extracto = []
                for frag in fragmentos:
                    if frag.startswith('<b>') and frag.endswith('</b>'): spans_extracto.append(ft.TextSpan(frag[3:-4], style=ft.TextStyle(color="error", weight="bold")))
                    else: spans_extracto.append(ft.TextSpan(frag))
                
                etiqueta_anio = t("lbl_ano_con_valor").format(res['anio']) if res['anio'] and res['anio'] != "Desconocido" else t("lbl_ano_desconocido")
                btn_abrir = ft.TextButton(content=ft.Text(t("btn_abrir_pdf").format(os.path.basename(res['ruta']), etiqueta_anio, res['pagina'])), on_click=lambda e, r=res['ruta'], p=res['pagina'], q=consulta: abrir_pdf(r, p, q))
                tarjeta = ft.Card(content=ft.Container(padding=15, content=ft.Column([btn_abrir, ft.Text(res['ruta'], size=10, color="onSurfaceVariant"), ft.Divider(height=1), ft.Text(spans=spans_extracto)])))
                lista_resultados.controls.append(tarjeta)
        page.update()

    panel_estado_sistema = ft.Container(content=ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color="primary"), txt_estado_indexacion]), padding=ft.Padding.only(bottom=5, top=5))

    area_busqueda = ft.Column([
        ft.Row([txt_busqueda, btn_buscar, btn_detener_busqueda, btn_exportar]), 
        panel_estado_sistema,
        txt_estado_busqueda,
        lista_resultados,
        fila_paginador,
        contenedor_cargar_mas
    ], expand=True)

    btn_salir.style = ft.ButtonStyle(color="error")

    span_desarrollo = ft.TextSpan(t("lbl_un_desarrollo_de"), style=ft.TextStyle(size=12, color="onSurfaceVariant"))

    encabezado = ft.Row([
        # --- LADO IZQUIERDO: Logo y Títulos ---
        ft.Row([
            ft.Image(src="icono_che.png", width=60, height=60, fit=ft.BoxFit.CONTAIN),
            ft.Column([
                ft.Row(controls=[ft.Text("Che PDF", size=28, weight="w800"), ft.Text(f"v{VERSION}", size=14, color="onSurfaceVariant", weight="w500") ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.END, spacing=8),
                # 2. Usamos la variable aquí
                ft.Text(spans=[span_desarrollo, ft.TextSpan("sitiosdememoria.uy", url="https://sitiosdememoria.uy", style=ft.TextStyle(size=12, color="primary", decoration=ft.TextDecoration.UNDERLINE))])
            ], spacing=2),
        ]),
        
        # --- EL RESORTE INVISIBLE ---
        ft.Container(expand=True)
        
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    contenedor_principal = ft.Container(content=ft.Row([barra_lateral, divisor_movil, area_busqueda]), expand=True, padding=ft.Padding.only(top=10))

    def cambiar_idioma_inmediato(e):
        idioma_nuevo = dropdown_idioma.value
        if config_app.get("idioma") != idioma_nuevo:
            config_app["idioma"] = idioma_nuevo
            guardar_config(config_app)
            
            diccionario_textos.clear()
            diccionario_textos.update(cargar_idioma(idioma_nuevo))
            
            aplicar_traduccion_al_vuelo()

    dropdown_idioma = ft.Dropdown(
        label=t("lbl_idioma"), 
        value=config_app.get("idioma", "es"), 
        options=[
            ft.dropdown.Option("es", t("lbl_espanol")), 
            ft.dropdown.Option("en", t("lbl_ingles"))
        ], 
        width=300,
        on_select=cambiar_idioma_inmediato  
    )

    radio_metodo_anio = ft.RadioGroup(value=config_app.get("metodo_anio", "nombre_archivo"), content=ft.Column([ft.Radio(value="nombre_archivo", label=t("opt_metodo_nombre")), ft.Radio(value="carpeta", label=t("opt_metodo_carpeta")), ft.Radio(value="metadatos", label=t("opt_metodo_metadatos"))]))
    txt_lbl_modo_busqueda = ft.Text(t("lbl_modo_busqueda") if "lbl_modo_busqueda" in diccionario_textos else "Modo de Búsqueda", weight="bold", size=18)
    
    txt_limite = ft.TextField(label=t("lbl_limite_maximo"), value=str(config_app.get("limite_resultados", 10000)), width=150, height=40, text_size=13, content_padding=10, keyboard_type=ft.KeyboardType.NUMBER)
    txt_limite.visible = config_app.get("modo_busqueda", "relevancia") == "relevancia"
    
    def al_cambiar_modo(e):
        txt_limite.visible = (radio_modo_busqueda.value == "relevancia")
        page.update()

    radio_modo_busqueda = ft.RadioGroup(value=config_app.get("modo_busqueda", "relevancia"), on_change=al_cambiar_modo, content=ft.Column([ft.Row([ft.Radio(value="relevancia", label=t("opt_modo_relevancia") if "opt_modo_relevancia" in diccionario_textos else "Precisión: Ordenar por relevancia FTS5"), txt_limite], alignment=ft.MainAxisAlignment.START), ft.Radio(value="rapida", label=t("opt_modo_rapido") if "opt_modo_rapido" in diccionario_textos else "Velocidad: Carga continua por orden de indexación")]))
    
    dropdown_tamanio_db = ft.Dropdown(label=t("lbl_tamanio_db"), value=str(config_app.get("tamanio_max_db", 2048)), options=[ft.dropdown.Option("500", t("opt_500mb")), ft.dropdown.Option("1024", t("opt_1gb")), ft.dropdown.Option("2048", t("opt_2gb")), ft.dropdown.Option("4096", t("opt_4gb"))], width=350)

    txt_lbl_modo_visual = ft.Text(t("lbl_modo_visual") if "lbl_modo_visual" in diccionario_textos else "Modo de Visualización (Requiere reiniciar la app)", weight="bold", size=18)
    
    radio_modo_visual = ft.RadioGroup(
        value=config_app.get("modo_visualizacion", "web"), 
        content=ft.Column([
            ft.Radio(value="web", label=t("opt_visual_web") if "opt_visual_web" in diccionario_textos else "Navegador Web (Seguro / Máxima compatibilidad)"), 
            ft.Radio(value="escritorio", label=t("opt_visual_escritorio") if "opt_visual_escritorio" in diccionario_textos else "Aplicación de Escritorio (Nativo)")
        ])
    )

    def aplicar_tema_dinamico(id_tema):
        tema = diccionario_temas.get(id_tema, diccionario_temas["dark"])
        
        page.theme_mode = ft.ThemeMode.DARK if tema["modo"] == "dark" else ft.ThemeMode.LIGHT
        page.theme = ft.Theme(color_scheme_seed=tema["seed_color"])
        
        # Eliminamos el código de asignar grises manualmente porque 
        # ahora los Text usan color="onSurfaceVariant" nativamente
        
        config_app["tema_visual"] = id_tema
        guardar_config(config_app)
        page.update()

    opciones_tema = []
    for id_t, info in diccionario_temas.items():
        opciones_tema.append(ft.Radio(value=id_t, label=info["nombre"]))

    txt_lbl_tema = ft.Text(t("lbl_tema_visual") if "lbl_tema_visual" in diccionario_textos else "Tema Visual", weight="bold", size=18)
    radio_tema = ft.RadioGroup(
        value=config_app.get("tema_visual", "dark"),
        on_change=lambda e: aplicar_tema_dinamico(radio_tema.value),
        content=ft.Column(opciones_tema)
    )

    txt_lbl_config_motor = ft.Text(t("lbl_config_motor"), size=20, weight="bold")
    
    # Asignación semántica a textos de la configuración
    txt_desc_config_metodo = ft.Text(t("desc_config_metodo"), color="onSurfaceVariant")
    txt_lbl_rendimiento_busqueda = ft.Text(t("lbl_rendimiento_busqueda"), weight="bold", size=18)
    txt_desc_tamanio_db = ft.Text(t("desc_tamanio_db"), color="onSurfaceVariant")
    txt_desc_config_limite = ft.Text(t("desc_config_limite"), color="onSurfaceVariant")

    contenedor_configuracion = ft.Container(
        padding=20, 
        content=ft.Column([
            txt_lbl_config_motor, 
            dropdown_idioma, 
            ft.Divider(), 
            txt_desc_config_metodo, 
            radio_metodo_anio, 
            ft.Divider(), 
            txt_lbl_modo_busqueda, 
            radio_modo_busqueda, 
            ft.Divider(), 
            txt_lbl_modo_visual, 
            radio_modo_visual, 
            ft.Divider(),
            txt_lbl_rendimiento_busqueda, 
            txt_desc_tamanio_db, 
            dropdown_tamanio_db, 
            ft.Divider(),
            txt_lbl_tema,
            radio_tema,
            ft.Container(height=10)
        ], 
        scroll=ft.ScrollMode.AUTO)
    )

    def crear_paso(numero, titulo, descripcion, icono):
        return ft.Row(
        [
            ft.Container(
                content=ft.Text(str(numero), weight="bold", size=20, color="black"), 
                alignment=ft.Alignment.CENTER, 
                width=40, 
                height=40, 
                border_radius=20, 
                bgcolor="primary" 
            ), 
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icono, size=18, color="primary"), 
                            ft.Text(titulo, weight="bold", size=16)
                        ]
                    ), 
                    ft.Container(
                        content=ft.Text(descripcion, color="onSurfaceVariant"),
                        width=600
                    )
                ], 
                expand=True
            )
        ], 
        alignment=ft.MainAxisAlignment.START, 
        spacing=15
    )

    def construir_pestana_ayuda():
        return ft.Container(
            padding=30, 
            content=ft.Column([
                ft.Text(t("help_titulo"), size=24, weight="bold"), 
                ft.Text(t("help_desc"), color="onSurfaceVariant"), 
                ft.Divider(height=30), 
                ft.Text(t("help_pasos_titulo"), weight="bold", size=18), 
                ft.Container(height=10), 
                
                crear_paso(1, t("help_paso1_tit"), t("help_paso1_desc"), ft.Icons.SETTINGS), 
                ft.Container(height=10), 
                crear_paso(2, t("help_paso2_tit"), t("help_paso2_desc"), ft.Icons.CREATE_NEW_FOLDER), 
                ft.Container(height=10), 
                crear_paso(3, t("help_paso3_tit"), t("help_paso3_desc"), ft.Icons.FILTER_ALT), 
                ft.Container(height=10), 
                crear_paso(4, t("help_paso4_tit"), t("help_paso4_desc"), ft.Icons.SEARCH), 
                ft.Container(height=10), 
                crear_paso(5, t("help_paso5_tit"), t("help_paso5_desc"), ft.Icons.OPEN_IN_NEW), 
                
                ft.Divider(height=40), 
                ft.Text(t("help_sintaxis_tit"), weight="bold", size=18), 
                ft.Text(t("help_sintaxis_desc"), color="onSurfaceVariant"), 
                
                ft.Container(
                    padding=15, 
                    bgcolor="surfaceVariant", 
                    border_radius=5, 
                    content=ft.Column([
                        ft.Text(t("help_sintaxis_frase"), size=13), 
                        ft.Text(t("help_sintaxis_and"), size=13), 
                        ft.Text(t("help_sintaxis_or"), size=13), 
                        ft.Text(t("help_sintaxis_not"), size=13)
                    ])
                )
            ], spacing=10, scroll=ft.ScrollMode.AUTO)
        )

    def construir_pestana_acerca_de():
        return ft.Container(
        padding=40, 
        content=ft.Column([
            ft.Row([ft.Image(src="icono_che.png", width=120, height=120, fit=ft.BoxFit.CONTAIN)], alignment=ft.MainAxisAlignment.CENTER), 
            ft.Row([ft.Text("Che PDF", size=28, weight="bold")], alignment=ft.MainAxisAlignment.CENTER), 
            ft.Row([ft.Text(t("about_desc"), color="onSurfaceVariant", text_align=ft.TextAlign.CENTER)], alignment=ft.MainAxisAlignment.CENTER), 
            ft.Divider(height=40), 
            ft.Text(t("about_detalles_tit"), weight="bold", size=16), 
            ft.Text(t("about_version").format(VERSION)), 
            ft.Text(t("about_fecha")), 
            ft.Text(t("about_licencia")), 
            ft.Container(height=20), 
            ft.Text(t("about_desarrollo"), italic=True, size=15, color="primary"), 
            ft.Container(height=10), 
            ft.Row([
                ft.TextButton(
                    content=ft.Text(t("about_visitar")), 
                    icon=ft.Icons.OPEN_IN_NEW, 
                    url="https://sitiosdememoria.uy"
                )
            ], alignment=ft.MainAxisAlignment.CENTER)
        ])
    )

    def construir_pestana_donar():
        return ft.Container(
        padding=40, 
        content=ft.Column([
            ft.Row([ft.Image(src="aportar.png", width=120, height=120, fit=ft.BoxFit.CONTAIN)], alignment=ft.MainAxisAlignment.CENTER), 
            ft.Row([ft.Text(t("donate_tit"), size=28, weight="bold")], alignment=ft.MainAxisAlignment.CENTER), 
            ft.Row([ft.Text(t("donate_desc"), color="onSurfaceVariant", text_align=ft.TextAlign.CENTER, width=600)], alignment=ft.MainAxisAlignment.CENTER), 
            ft.Container(height=30), 
            ft.Row([
                ft.Button(
                    content=ft.Text(t("donate_btn")), 
                    icon=ft.Icons.VOLUNTEER_ACTIVISM, 
                    icon_color="pink400", 
                    url="https://ko-fi.com/sitiosdememoriauy", 
                    style=ft.ButtonStyle(
                        bgcolor="primaryContainer", 
                        color="onPrimaryContainer", 
                        padding=20
                    )
                )
            ], alignment=ft.MainAxisAlignment.CENTER)
        ])
    )

    mi_tab_bar = ft.TabBar(
        tabs=[
            ft.Tab(label=t("tab_busqueda"), icon=ft.Icons.SEARCH),
            ft.Tab(label=t("tab_config"), icon=ft.Icons.SETTINGS),
            ft.Tab(label=t("tab_ayuda"), icon=ft.Icons.HELP),
            ft.Tab(label=t("tab_acerca_de"), icon=ft.Icons.INFO),
            ft.Tab(label=t("tab_donar"), icon=ft.Icons.VOLUNTEER_ACTIVISM)
        ]
    )

    mi_tab_bar_view = ft.TabBarView(
        expand=True,
        controls=[
            contenedor_principal,           
            contenedor_configuracion,       
            construir_pestana_ayuda(),      
            construir_pestana_acerca_de(),  
            construir_pestana_donar()       
        ]
    )

    def guardar_config_al_cambiar_pestana(e=None):
        config_app["metodo_anio"] = radio_metodo_anio.value
        config_app["tamanio_max_db"] = int(dropdown_tamanio_db.value)
        config_app["modo_busqueda"] = radio_modo_busqueda.value
        config_app["modo_visualizacion"] = radio_modo_visual.value
        config_app["idioma"] = dropdown_idioma.value
        try: 
            config_app["limite_resultados"] = int(txt_limite.value)
        except ValueError: 
            config_app["limite_resultados"] = 10000
        guardar_config(config_app)

    def asignar_texto(obj, valor):
        if not obj: return
        try:
            if hasattr(obj, "label"): obj.label = valor; return
            if hasattr(obj, "text"): obj.text = valor; return
            if hasattr(obj, "content") and hasattr(obj.content, "value"): obj.content.value = valor; return
            if hasattr(obj, "content"): obj.content = ft.Text(valor); return
            if hasattr(obj, "value"): obj.value = valor; return
        except Exception: 
            pass

    def aplicar_traduccion_al_vuelo():
        try:
            page.title = t("app_titulo")
            span_desarrollo.text = t("lbl_un_desarrollo_de")
            asignar_texto(txt_lbl_indexar_carpetas, t("lbl_indexar_carpetas"))
            asignar_texto(txt_lbl_filtro_carpetas, t("lbl_filtro_carpetas"))
            
            asignar_texto(btn_todas, t("btn_todas"))
            asignar_texto(btn_ninguna, t("btn_ninguna"))
            asignar_texto(btn_salir, t("btn_salir"))
            asignar_texto(btn_buscar, t("btn_buscar"))
            asignar_texto(btn_anterior, t("btn_anterior"))
            asignar_texto(btn_siguiente, t("btn_siguiente"))
            asignar_texto(btn_cargar_mas, t("btn_cargar_mas") if "btn_cargar_mas" in diccionario_textos else "Cargar más resultados...")
            asignar_texto(btn_exportar, t("btn_exportar") if "btn_exportar" in diccionario_textos else "Exportar ODS")
            asignar_texto(btn_confirmar_borrado, t("btn_borrar"))
            asignar_texto(btn_cancelar_borrado, t("btn_cancelar"))

            asignar_texto(check_desconocidos, t("lbl_incluir_sin_ano"))
            asignar_texto(txt_busqueda, t("lbl_buscar_ejemplo"))
            asignar_texto(dlg_borrar.title, t("lbl_gestion_indice"))
            asignar_texto(dropdown_borrar, t("lbl_que_deseas_borrar"))
            asignar_texto(check_confirmacion, t("lbl_accion_irreversible"))
            asignar_texto(txt_lbl_config_motor, t("lbl_config_motor"))
            asignar_texto(txt_desc_config_metodo, t("desc_config_metodo"))
            asignar_texto(txt_lbl_rendimiento_busqueda, t("lbl_rendimiento_busqueda"))
            asignar_texto(txt_desc_tamanio_db, t("desc_tamanio_db"))
            
            # --- AGREGAR ESTE BLOQUE PARA EL DROPDOWN DE TAMAÑO ---
            val_tamanio = dropdown_tamanio_db.value
            dropdown_tamanio_db.label = t("lbl_tamanio_db")
            dropdown_tamanio_db.options = [
                ft.dropdown.Option("500", t("opt_500mb")), 
                ft.dropdown.Option("1024", t("opt_1gb")), 
                ft.dropdown.Option("2048", t("opt_2gb")), 
                ft.dropdown.Option("4096", t("opt_4gb"))
            ]
            dropdown_tamanio_db.value = val_tamanio
            # ------------------------------------------------------

            asignar_texto(txt_lbl_modo_busqueda, t("lbl_modo_busqueda") if "lbl_modo_busqueda" in diccionario_textos else "Modo de Búsqueda")
            asignar_texto(txt_desc_config_limite, t("desc_config_limite"))
            asignar_texto(txt_limite, t("lbl_limite_maximo"))

            val_idioma = dropdown_idioma.value
            dropdown_idioma.options = [
                ft.dropdown.Option("es", t("lbl_espanol")), 
                ft.dropdown.Option("en", t("lbl_ingles"))
            ]
            dropdown_idioma.label = t("lbl_idioma")
            dropdown_idioma.value = val_idioma

            asignar_texto(radio_metodo_anio.content.controls[0], t("opt_metodo_nombre"))
            asignar_texto(radio_metodo_anio.content.controls[1], t("opt_metodo_carpeta"))
            asignar_texto(radio_metodo_anio.content.controls[2], t("opt_metodo_metadatos"))
            
            asignar_texto(radio_modo_busqueda.content.controls[0].controls[0], t("opt_modo_relevancia") if "opt_modo_relevancia" in diccionario_textos else "Precisión")
            asignar_texto(radio_modo_busqueda.content.controls[1], t("opt_modo_rapido") if "opt_modo_rapido" in diccionario_textos else "Velocidad")

            asignar_texto(txt_lbl_modo_visual, t("lbl_modo_visual") if "lbl_modo_visual" in diccionario_textos else "Modo de Visualización (Requiere reiniciar la app)")
            asignar_texto(radio_modo_visual.content.controls[0], t("opt_visual_web") if "opt_visual_web" in diccionario_textos else "Navegador Web (Seguro / Máxima compatibilidad)")
            asignar_texto(radio_modo_visual.content.controls[1], t("opt_visual_escritorio") if "opt_visual_escritorio" in diccionario_textos else "Aplicación de Escritorio (Nativo)")

            nombres_tabs = ["tab_busqueda", "tab_config", "tab_ayuda", "tab_acerca_de", "tab_donar"]
            for i, tab_key in enumerate(nombres_tabs):
                asignar_texto(mi_tab_bar.tabs[i], t(tab_key))
            
            mi_tab_bar_view.controls[2] = construir_pestana_ayuda()
            mi_tab_bar_view.controls[3] = construir_pestana_acerca_de()
            mi_tab_bar_view.controls[4] = construir_pestana_donar()
            
            hilo = estado_app["hilo_indexacion"]
            if not hilo or not hilo.is_alive(): 
                asignar_texto(txt_estado_indexacion, t("estado_reposo"))
                
            mi_tab_bar.update()
            mi_tab_bar_view.update()
            page.update()
            actualizar_filtros_ui()
        except Exception:
            pass
           
    tabs = ft.Tabs(
        length=5,
        selected_index=0, 
        expand=True,
        on_change=guardar_config_al_cambiar_pestana,
        content=ft.Column(
            expand=True,
            controls=[
                mi_tab_bar,
                mi_tab_bar_view
            ]
        )
    )

    page.add(encabezado, ft.Divider(), tabs)

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    import sys
    import os

    if getattr(sys, 'frozen', False): 
        ruta_base_real = os.path.dirname(sys.executable)
    else: 
        ruta_base_real = os.path.dirname(os.path.abspath(__file__))
        
    ruta_assets_absoluta = os.path.join(ruta_base_real, "_internal", "assets")

    archivo_log = os.path.join(ruta_base_real, "crash_log.txt")
    if sys.platform == "win32":
        if sys.stdout is None:
            sys.stdout = open(archivo_log, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(archivo_log, "a", encoding="utf-8")
            
        import atexit
        def destruir_log_vacio():
            try:
                if os.path.exists(archivo_log) and os.path.getsize(archivo_log) == 0:
                    os.remove(archivo_log)
            except Exception:
                pass
        
        atexit.register(destruir_log_vacio)

    modo_arranque = "web"
    CONFIG_FILE = os.path.join(ruta_base_real, "config.json") 
    try:
        if os.path.exists(CONFIG_FILE):
            import json
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: 
                conf_previa = json.load(f)
                modo_arranque = conf_previa.get("modo_visualizacion", "web")
    except Exception:
        pass

    import flet as ft
    if modo_arranque == "escritorio":
        ft.run(main, assets_dir=ruta_assets_absoluta)
    else:
        # Le indicamos que solo escuche conexiones locales
        ft.run(main, view=ft.AppView.WEB_BROWSER, assets_dir=ruta_assets_absoluta, host="127.0.0.1")
