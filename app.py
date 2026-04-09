VERSION = "1.3"

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

CONFIG_FILE = os.path.join(motor_sqlite.BASE_DIR, "config.json")

def obtener_idioma_sistema():
    try:
        idioma_local, _ = locale.getlocale()
        
        if idioma_local is None:
            idioma_local = os.environ.get('LANG', os.environ.get('LANGUAGE', ''))
            
        if idioma_local and idioma_local.lower().startswith('es'):
            return 'es'
        return 'en'
    except Exception:
        return 'es'

def cargar_config():
    config_default = {
        "metodo_anio": "nombre_archivo", 
        "limite_resultados": 1000,
        "idioma": obtener_idioma_sistema(),
        "tamanio_max_db": 2048,
        "modo_busqueda": "rapida"
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: 
                config_guardada = json.load(f)
                config_default.update(config_guardada)
                return config_default
        except Exception: 
            pass
            
    return config_default

def guardar_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: 
        json.dump(config, f)

def cargar_idioma(codigo_idioma):
    ruta_locale = os.path.join(motor_sqlite.BASE_DIR, "locales", f"{codigo_idioma}.json")
    try:
        with open(ruta_locale, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def main(page: ft.Page):
    config_app = cargar_config()
    
    # 1. Cargar el diccionario correspondiente
    diccionario_textos = cargar_idioma(config_app.get("idioma", "es"))

    # 2. Definir la función traductora dinámica
    def t(clave):
        return diccionario_textos.get(clave, clave)

    page.title = t("app_titulo")
    page.window.icon = "icono_che.ico" 
    page.theme_mode = "dark"
    page.padding = 10 
    
    estado_busqueda = {
        "pagina_actual": 1,
        "resultados_por_pagina": 50,
        "total_paginas": 1
    }
    
    estado_app = {
        "hilo_indexacion": None,
        "mostrar_rutas": False 
    }

    # --- CONTROLES DE ESTADO INDEPENDIENTES ---
    txt_estado_indexacion = ft.Text(t("estado_reposo"), italic=True, color="blue300", size=13)
    txt_estado_busqueda = ft.Text("", italic=True, color="grey400", size=13)

    # --- 1. CONTROLES DEL PANEL LATERAL (FILTROS) ---
    lista_checkboxes = ft.ListView(expand=True, spacing=5)
    
    txt_rango_anios = ft.Text(t("lbl_filtro_temporal_calc"), weight="bold", size=16)
    
    def on_slider_change(e):
        txt_rango_anios.value = t("lbl_rango_anos").format(int(slider_anios.start_value), int(slider_anios.end_value))
        page.update()

    slider_anios = ft.RangeSlider(
        min=1900, max=2030,
        start_value=1900, end_value=2030,
        divisions=130,
        label="{value}",
        disabled=True,
        on_change=on_slider_change,
        active_color="blue400",
        inactive_color="grey800"
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
            slider_anios.min = 1900
            slider_anios.max = 2030
            slider_anios.start_value = 1900
            slider_anios.end_value = 2030
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

    # --- 2. LÓGICA DE INDEXACIÓN ---
    def detener_proceso(e):
        motor_sqlite.detener_indexacion = True
        txt_estado_indexacion.value = t("msg_deteniendo_segura")
        btn_detener.disabled = True
        btn_detener.icon_color = "grey500" 
        page.update()

    btn_detener = ft.IconButton(icon="stop", icon_color="grey500", icon_size=30, tooltip=t("tooltip_detener_index"), disabled=True, on_click=detener_proceso)

    def on_carpeta_seleccionada(e: ft.FilePickerResultEvent):
        if e.path:

            def tarea_indexar():
                nombre_carpeta = os.path.basename(e.path)
                txt_estado_indexacion.value = t("msg_calculando_archivos").format(nombre_carpeta)
                
                btn_indexar.disabled = True
                btn_borrar_indice.disabled = True 
                btn_borrar_indice.icon_color = "grey500" 
                btn_detener.disabled = False
                btn_detener.icon_color = "red400"        
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
                                slider_anios.min = anio_int - 1
                                slider_anios.max = anio_int + 1
                                slider_anios.start_value = anio_int
                                slider_anios.end_value = anio_int
                                slider_anios.disabled = False
                                check_desconocidos.disabled = False
                                cambio = True
                            else:
                                if anio_int < slider_anios.min:
                                    slider_anios.min = anio_int
                                    slider_anios.start_value = anio_int 
                                    cambio = True
                                if anio_int > slider_anios.max:
                                    slider_anios.max = anio_int
                                    slider_anios.end_value = anio_int 
                                    cambio = True
                                    
                            if cambio:
                                divisiones = int(slider_anios.max - slider_anios.min)
                                slider_anios.divisions = divisiones if divisiones > 0 else 2
                                txt_rango_anios.value = t("lbl_rango_anos").format(int(slider_anios.start_value), int(slider_anios.end_value))
                        except ValueError:
                            pass

                    if actual % 10 == 0 or actual == total:
                        page.update()
                
                motor_sqlite.indexar_documentos(
                    e.path, 
                    metodo_anio=config_app.get("metodo_anio", "nombre_archivo"), 
                    tamanio_max_mb=config_app.get("tamanio_max_db", 1024),
                    callback_progreso=actualizar_interfaz
                )
                
                if motor_sqlite.detener_indexacion:
                    txt_estado_indexacion.value = t("msg_deteniendo_interfaz")
                    page.update()
                
                actualizar_filtros_ui() 
                
                if motor_sqlite.detener_indexacion:
                    txt_estado_indexacion.value = t("msg_indexacion_abortada")
                else:
                    txt_estado_indexacion.value = t("msg_index_exito").format(nombre_carpeta)
                
                btn_indexar.disabled = False
                btn_borrar_indice.disabled = False 
                btn_borrar_indice.icon_color = "red400" 
                btn_detener.disabled = True
                btn_detener.icon_color = "grey500" 
                actualizar_filtros_ui() 
                
            estado_app["hilo_indexacion"] = threading.Thread(target=tarea_indexar, daemon=True)
            estado_app["hilo_indexacion"].start()

    selector_carpetas = ft.FilePicker(on_result=on_carpeta_seleccionada)
    page.overlay.append(selector_carpetas)

    # --- 3. LÓGICA DE BORRADO ---
    texto_advertencia = ft.Text("")
    dropdown_borrar = ft.Dropdown(label=t("lbl_que_deseas_borrar"), options=[], width=350)
    check_confirmacion = ft.Checkbox(label=t("lbl_accion_irreversible"))
    btn_confirmar_borrado = ft.TextButton(t("btn_borrar"), style=ft.ButtonStyle(color="red400"), disabled=True)
    btn_cancelar_borrado = ft.TextButton(t("btn_cancelar"), on_click=lambda e: cerrar_dialogo())

    def on_checkbox_change(e):
        btn_confirmar_borrado.disabled = not check_confirmacion.value
        page.update()
    check_confirmacion.on_change = on_checkbox_change

    def cerrar_dialogo(e=None):
        page.close(dlg_borrar)
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
        
        page.close(dlg_borrar)
        if resultado is True:
            txt_estado_indexacion.value = msj
            actualizar_filtros_ui() 
            lista_resultados.controls.clear()
            fila_paginador.visible = False
            contenedor_cargar_mas.visible = False
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
        page.open(dlg_borrar)
        page.update()

    btn_salir = ft.ElevatedButton(t("btn_salir"), icon="exit_to_app")

    def salir_app(e):
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
        page.window.close()
    btn_salir.on_click = salir_app

    # --- 4. ENSAMBLAJE DE BARRA LATERAL ---
    btn_indexar = ft.IconButton(icon="create_new_folder", icon_size=30, tooltip=t("tooltip_indexar_carpeta"), on_click=lambda _: selector_carpetas.get_directory_path())
    btn_borrar_indice = ft.IconButton(icon="delete_forever", icon_size=30, icon_color="red400", tooltip=t("tooltip_borrar_indice"), on_click=abrir_dialogo_borrado)

    def alternar_vista_rutas(e):
        estado_app["mostrar_rutas"] = not estado_app["mostrar_rutas"]
        e.control.icon = "visibility" if estado_app["mostrar_rutas"] else "visibility_off"
        e.control.tooltip = t("tooltip_ocultar_rutas") if estado_app["mostrar_rutas"] else t("tooltip_mostrar_rutas")
        actualizar_filtros_ui()
    btn_alternar_vista = ft.IconButton(icon="visibility_off", tooltip=t("tooltip_mostrar_rutas"), on_click=alternar_vista_rutas)

    txt_lbl_indexar_carpetas = ft.Text(t("lbl_indexar_carpetas"), weight="bold", size=16)
    txt_lbl_filtro_carpetas = ft.Text(t("lbl_filtro_carpetas"), weight="bold", size=16)
    btn_todas = ft.TextButton(t("btn_todas"), on_click=seleccionar_todas)
    btn_ninguna = ft.TextButton(t("btn_ninguna"), on_click=deseleccionar_todas)

    barra_lateral = ft.Container(
        width=250,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column([
            txt_lbl_indexar_carpetas,
            ft.Row([btn_indexar, btn_detener, btn_borrar_indice], alignment=ft.MainAxisAlignment.START, spacing=15),
            ft.Divider(),
            
            txt_rango_anios,
            slider_anios,
            check_desconocidos,
            ft.Divider(),
            
            ft.Row([txt_lbl_filtro_carpetas, btn_alternar_vista], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([btn_todas, btn_ninguna]),
            ft.Divider(),
            lista_checkboxes,
            ft.Divider(),
            btn_salir
        ])
    )

    def mover_divisor(e: ft.DragUpdateEvent):
        nuevo_ancho = barra_lateral.width + e.delta_x
        if 150 <= nuevo_ancho <= 600:
            barra_lateral.width = nuevo_ancho
            page.update()

    divisor_movil = ft.GestureDetector(
        mouse_cursor=ft.MouseCursor.RESIZE_COLUMN,
        on_pan_update=mover_divisor,
        content=ft.Container(width=10, bgcolor="transparent", content=ft.VerticalDivider(width=1, color="white24"))
    )

    # --- 5. ÁREA PRINCIPAL DE BÚSQUEDA ---
    txt_busqueda = ft.TextField(label=t("lbl_buscar_ejemplo"), expand=True, on_submit=lambda e: ejecutar_busqueda(nueva_busqueda=True))
    btn_buscar = ft.ElevatedButton(t("btn_buscar"), icon="search", on_click=lambda e: ejecutar_busqueda(nueva_busqueda=True))
    
    lista_resultados = ft.ListView(expand=True, spacing=10, padding=10)

    btn_anterior = ft.ElevatedButton(t("btn_anterior"), icon="arrow_back", on_click=lambda e: cambiar_pagina(-1))
    btn_siguiente = ft.ElevatedButton(t("btn_siguiente"), icon="arrow_forward", on_click=lambda e: cambiar_pagina(1))
    txt_paginacion = ft.Text(t("lbl_pagina_1_de_1"), weight="bold")
    fila_paginador = ft.Row(controls=[btn_anterior, txt_paginacion, btn_siguiente], alignment="center", visible=False)

    btn_cargar_mas = ft.ElevatedButton(
        t("btn_cargar_mas") if "btn_cargar_mas" in diccionario_textos else "Cargar más resultados...", 
        icon="downloading", 
        on_click=lambda e: cambiar_pagina(1),
        style=ft.ButtonStyle(bgcolor="blue800", color="white")
    )
    contenedor_cargar_mas = ft.Row([btn_cargar_mas], alignment="center", visible=False)

    def abrir_pdf(ruta_guardada, pagina, termino_busqueda=""):
        if not os.path.isabs(ruta_guardada):
            ruta_real = os.path.join(motor_sqlite.BASE_DIR, ruta_guardada)
        else:
            ruta_real = ruta_guardada
        try:
            url_base = pathlib.Path(ruta_real).as_uri()
            if termino_busqueda:
                url_final = f"{url_base}#page={pagina}&search={urllib.parse.quote(termino_busqueda)}"
            else:
                url_final = f"{url_base}#page={pagina}"
            
            temp_dir = tempfile.gettempdir()
            html_path = os.path.join(temp_dir, "puente_visor_forense.html")
            
            texto_abriendo = t("msg_abriendo_html").format(pagina)
            
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(f'''<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0; url={url_final}"></head>
                <body style="background-color: #1e1e1e; color: #ffffff; display: flex; justify-content: center; align-items: center; height: 100vh;">
                    <h2>{texto_abriendo}</h2>
                    <script>window.focus();</script>
                </body></html>''')
            
            uri_html = pathlib.Path(html_path).as_uri()
            page.launch_url(uri_html)
            
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

        if nueva_busqueda: 
            estado_busqueda["pagina_actual"] = 1
            
        if nueva_busqueda or modo_actual == "relevancia":
            lista_resultados.controls.clear()
            
        txt_estado_busqueda.value = t("msg_calculando_resultados")
        fila_paginador.visible = False
        contenedor_cargar_mas.visible = False
        page.update()

        carpetas_seleccionadas = [cb.data for cb in lista_checkboxes.controls if cb.value]
        if not carpetas_seleccionadas:
            txt_estado_busqueda.value = t("msg_selecciona_carpeta")
            page.update()
            return

        offset_actual = (estado_busqueda["pagina_actual"] - 1) * estado_busqueda["resultados_por_pagina"]

        anio_min = int(slider_anios.start_value) if not slider_anios.disabled else None
        anio_max = int(slider_anios.end_value) if not slider_anios.disabled else None
        incluir_desc = check_desconocidos.value
        
        limite_max = int(config_app.get("limite_resultados", 10000))

        respuesta = motor_sqlite.buscar_texto(
            consulta_str=consulta, 
            carpetas_permitidas=carpetas_seleccionadas,
            limite=estado_busqueda["resultados_por_pagina"],
            offset=offset_actual,
            anio_min=anio_min,
            anio_max=anio_max,
            incluir_desconocidos=incluir_desc,
            limite_maximo=limite_max,
            modo_busqueda=modo_actual
        )

        if "error" in respuesta:
            txt_estado_busqueda.value = t("msg_error_sintaxis")
            txt_estado_busqueda.color = "red400"
            page.update()
            return
            
        if respuesta.get("excede_limite"):
            txt_estado_busqueda.value = t("msg_limite_excedido").format(limite_max, respuesta['total'])
            txt_estado_busqueda.color = "orange400"
            page.update()
            return

        total_hits = respuesta["total"]
        if total_hits == 0:
            txt_estado_busqueda.value = t("msg_sin_resultados")
            txt_estado_busqueda.color = "grey400"
        else:
            txt_estado_busqueda.color = "grey400"
            estado_busqueda["total_paginas"] = math.ceil(total_hits / estado_busqueda["resultados_por_pagina"])
            
            if modo_actual == "relevancia":
                txt_estado_busqueda.value = t("msg_busqueda_exito").format(total_hits, estado_busqueda['pagina_actual'])
                txt_paginacion.value = t("lbl_paginacion").format(estado_busqueda['pagina_actual'], estado_busqueda['total_paginas'])
                btn_anterior.disabled = (estado_busqueda["pagina_actual"] == 1)
                btn_siguiente.disabled = (estado_busqueda["pagina_actual"] >= estado_busqueda["total_paginas"])
                fila_paginador.visible = True
            else:
                resultados_cargados = len(lista_resultados.controls) + len(respuesta["resultados"])
                txt_estado_busqueda.value = f"Mostrando {resultados_cargados} resultados (Carga rápida)"
                
                if respuesta["total"] > (offset_actual + estado_busqueda["resultados_por_pagina"]):
                    contenedor_cargar_mas.visible = True
                else:
                    contenedor_cargar_mas.visible = False
            
            for res in respuesta["resultados"]:
                fragmentos = re.split(r'(<b>.*?</b>)', f"...{res['extracto']}...")
                spans_extracto = []
                for frag in fragmentos:
                    if frag.startswith('<b>') and frag.endswith('</b>'):
                        spans_extracto.append(ft.TextSpan(frag[3:-4], style=ft.TextStyle(color="red400", weight="bold")))
                    else:
                        spans_extracto.append(ft.TextSpan(frag))
                
                etiqueta_anio = t("lbl_ano_con_valor").format(res['anio']) if res['anio'] and res['anio'] != "Desconocido" else t("lbl_ano_desconocido")
                btn_abrir = ft.TextButton(
                    text=t("btn_abrir_pdf").format(os.path.basename(res['ruta']), etiqueta_anio, res['pagina']),
                    on_click=lambda e, r=res['ruta'], p=res['pagina'], q=consulta: abrir_pdf(r, p, q)
                )

                tarjeta = ft.Card(content=ft.Container(padding=15, content=ft.Column([btn_abrir, ft.Text(res['ruta'], size=10, color="grey500"), ft.Divider(height=1), ft.Text(spans=spans_extracto)])))
                lista_resultados.controls.append(tarjeta)
        page.update()

    panel_estado_sistema = ft.Container(
        content=ft.Row([
            ft.Icon("info_outline", size=16, color="blue300"), 
            txt_estado_indexacion
        ]),
        padding=ft.padding.only(bottom=5, top=5)
    )

    area_busqueda = ft.Column([
        ft.Row([txt_busqueda, btn_buscar]), 
        panel_estado_sistema,
        txt_estado_busqueda,
        lista_resultados,
        fila_paginador,
        contenedor_cargar_mas
    ], expand=True)

    # --- 6. PESTAÑAS Y CONTENEDORES PRINCIPALES ---
    encabezado = ft.Row([
        ft.Image(src="icono_che.png", width=60, height=60, fit=ft.ImageFit.CONTAIN),
        ft.Column([
            ft.Row(
                controls=[
                    ft.Text("Che PDF", size=28, weight="w800"), 
                    ft.Text(f"v{VERSION}", size=14, color="grey500", weight="w500") 
                ],
                alignment=ft.MainAxisAlignment.START, 
                vertical_alignment=ft.CrossAxisAlignment.END,
                spacing=8
            ),
            # -------------------------------------------------------
            ft.Text(
                spans=[
                    ft.TextSpan(t("lbl_un_desarrollo_de"), style=ft.TextStyle(size=12, color="grey400")),
                    ft.TextSpan(
                        "sitiosdememoria.uy", 
                        url="https://sitiosdememoria.uy", 
                        style=ft.TextStyle(size=12, color="blue300", decoration=ft.TextDecoration.UNDERLINE)
                    )
                ]
            )
        ], spacing=2),
    ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    contenedor_principal = ft.Row([barra_lateral, divisor_movil, area_busqueda], expand=True)

    # --- PESTAÑA DE CONFIGURACIÓN ---
    dropdown_idioma = ft.Dropdown(
        label=t("lbl_idioma"),
        value=config_app.get("idioma", "es"),
        options=[
            ft.dropdown.Option("es", t("lbl_espanol")),
            ft.dropdown.Option("en", t("lbl_ingles"))
        ],
        width=300
    )

    radio_metodo_anio = ft.RadioGroup(
        value=config_app.get("metodo_anio", "nombre_archivo"),
        content=ft.Column([
            ft.Radio(value="nombre_archivo", label=t("opt_metodo_nombre")),
            ft.Radio(value="carpeta", label=t("opt_metodo_carpeta")),
            ft.Radio(value="metadatos", label=t("opt_metodo_metadatos")),
        ])
    )
    
    txt_lbl_modo_busqueda = ft.Text(t("lbl_modo_busqueda") if "lbl_modo_busqueda" in diccionario_textos else "Modo de Búsqueda", weight="bold", size=18)
    
    txt_limite = ft.TextField(
        label=t("lbl_limite_maximo"),
        value=str(config_app.get("limite_resultados", 10000)),
        width=150,
        height=40,
        text_size=13,
        content_padding=10,
        keyboard_type=ft.KeyboardType.NUMBER
    )
    txt_limite.visible = config_app.get("modo_busqueda", "relevancia") == "relevancia"
    
    def al_cambiar_modo(e):
        txt_limite.visible = (radio_modo_busqueda.value == "relevancia")
        page.update()

    radio_modo_busqueda = ft.RadioGroup(
        value=config_app.get("modo_busqueda", "relevancia"),
        on_change=al_cambiar_modo,
        content=ft.Column([
            ft.Row([
                ft.Radio(value="relevancia", label=t("opt_modo_relevancia") if "opt_modo_relevancia" in diccionario_textos else "Precisión: Ordenar por relevancia FTS5"),
                txt_limite
            ], alignment=ft.MainAxisAlignment.START),
            ft.Radio(value="rapida", label=t("opt_modo_rapido") if "opt_modo_rapido" in diccionario_textos else "Velocidad: Carga continua por orden de indexación"),
        ])
    )
    
    dropdown_tamanio_db = ft.Dropdown(
        label=t("lbl_tamanio_db"),
        value=str(config_app.get("tamanio_max_db", 2048)), 
        options=[
            ft.dropdown.Option("500", t("opt_500mb")),
            ft.dropdown.Option("1024", t("opt_1gb")),
            ft.dropdown.Option("2048", t("opt_2gb")),
            ft.dropdown.Option("4096", t("opt_4gb"))
        ],
        width=350
    )

    # Variables para la configuracion
    txt_lbl_config_motor = ft.Text(t("lbl_config_motor"), size=20, weight="bold")
    txt_desc_config_metodo = ft.Text(t("desc_config_metodo"), color="grey400")
    txt_lbl_rendimiento_busqueda = ft.Text(t("lbl_rendimiento_busqueda"), weight="bold", size=18)
    txt_desc_tamanio_db = ft.Text(t("desc_tamanio_db"), color="grey400")
    txt_desc_config_limite = ft.Text(t("desc_config_limite"), color="grey400")
    
    btn_guardar_config = ft.ElevatedButton(t("btn_guardar_config"), icon="save")

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
            txt_lbl_rendimiento_busqueda,
            txt_desc_tamanio_db,
            dropdown_tamanio_db,
            ft.Container(height=10)
        ], scroll=ft.ScrollMode.AUTO)
    )

    # --- LÓGICA DE TRADUCCIÓN AL VUELO ---
    def aplicar_traduccion_al_vuelo():
        page.title = t("app_titulo")

        # Barra lateral y Tooltips
        txt_lbl_indexar_carpetas.value = t("lbl_indexar_carpetas")
        txt_lbl_filtro_carpetas.value = t("lbl_filtro_carpetas")
        btn_todas.text = t("btn_todas")
        btn_ninguna.text = t("btn_ninguna")
        btn_salir.text = t("btn_salir")
        check_desconocidos.label = t("lbl_incluir_sin_ano")

        btn_indexar.tooltip = t("tooltip_indexar_carpeta")
        btn_detener.tooltip = t("tooltip_detener_index")
        btn_borrar_indice.tooltip = t("tooltip_borrar_indice")
        btn_alternar_vista.tooltip = t("tooltip_ocultar_rutas") if estado_app["mostrar_rutas"] else t("tooltip_mostrar_rutas")

        # Búsqueda
        txt_busqueda.label = t("lbl_buscar_ejemplo")
        btn_buscar.text = t("btn_buscar")
        btn_anterior.text = t("btn_anterior")
        btn_siguiente.text = t("btn_siguiente")
        btn_cargar_mas.text = t("btn_cargar_mas") if "btn_cargar_mas" in diccionario_textos else "Cargar más resultados..."

        # Dialogo borrar
        dlg_borrar.title.value = t("lbl_gestion_indice")
        dropdown_borrar.label = t("lbl_que_deseas_borrar")
        check_confirmacion.label = t("lbl_accion_irreversible")
        btn_confirmar_borrado.text = t("btn_borrar")
        btn_cancelar_borrado.text = t("btn_cancelar")

        # Configuración
        txt_lbl_config_motor.value = t("lbl_config_motor")

        val_idioma = dropdown_idioma.value
        val_tamanio = dropdown_tamanio_db.value
        
        dropdown_idioma.value = None
        dropdown_tamanio_db.value = None
        
        page.update() 
        
        time.sleep(0.05)

        dropdown_idioma.label = t("lbl_idioma")
        dropdown_idioma.options = [
            ft.dropdown.Option("es", t("lbl_espanol")),
            ft.dropdown.Option("en", t("lbl_ingles"))
        ]

        dropdown_tamanio_db.label = t("lbl_tamanio_db")
        dropdown_tamanio_db.options = [
            ft.dropdown.Option("500", t("opt_500mb")),
            ft.dropdown.Option("1024", t("opt_1gb")),
            ft.dropdown.Option("2048", t("opt_2gb")),
            ft.dropdown.Option("4096", t("opt_4gb"))
        ]
        
        dropdown_idioma.value = val_idioma
        dropdown_tamanio_db.value = val_tamanio
        # ==========================================================

        txt_desc_config_metodo.value = t("desc_config_metodo")
        
        # --- Recreamos la columna completa para el método de año ---
        radio_metodo_anio.content = ft.Column([
            ft.Radio(value="nombre_archivo", label=t("opt_metodo_nombre")),
            ft.Radio(value="carpeta", label=t("opt_metodo_carpeta")),
            ft.Radio(value="metadatos", label=t("opt_metodo_metadatos")),
        ])

        txt_lbl_rendimiento_busqueda.value = t("lbl_rendimiento_busqueda")
        txt_desc_tamanio_db.value = t("desc_tamanio_db")
        
        txt_lbl_modo_busqueda.value = t("lbl_modo_busqueda") if "lbl_modo_busqueda" in diccionario_textos else "Modo de Búsqueda"
        
        # --- Recreamos la columna completa para el modo de búsqueda ---
        radio_modo_busqueda.content = ft.Column([
            ft.Radio(value="relevancia", label=t("opt_modo_relevancia") if "opt_modo_relevancia" in diccionario_textos else "Precisión: Ordenar por relevancia FTS5 (Recomendado)"),
            ft.Radio(value="rapida", label=t("opt_modo_rapido") if "opt_modo_rapido" in diccionario_textos else "Velocidad: Carga continua por orden de indexación (Instantáneo)"),
        ])

        txt_desc_config_limite.value = t("desc_config_limite")
        txt_limite.label = t("lbl_limite_maximo")
        btn_guardar_config.text = t("btn_guardar_config")

        # Reconstruir pestañas completas
        tabs.tabs[2].content = construir_pestana_ayuda()
        tabs.tabs[3].content = construir_pestana_acerca_de()
        tabs.tabs[4].content = construir_pestana_donar()

        # Títulos de las pestañas
        tabs.tabs[0].text = t("tab_busqueda")
        tabs.tabs[1].text = t("tab_config")
        tabs.tabs[2].text = t("tab_ayuda")
        tabs.tabs[3].text = t("tab_acerca_de")
        tabs.tabs[4].text = t("tab_donar")

        hilo = estado_app["hilo_indexacion"]
        if not hilo or not hilo.is_alive():
            txt_estado_indexacion.value = t("estado_reposo")
            
        if estado_busqueda["total_paginas"] == 1:
            txt_paginacion.value = t("lbl_pagina_1_de_1")
        else:
            txt_paginacion.value = t("lbl_paginacion").format(estado_busqueda['pagina_actual'], estado_busqueda['total_paginas'])

        actualizar_filtros_ui()

    def cambiar_idioma_inmediato(e):
        idioma_nuevo = dropdown_idioma.value
        if config_app.get("idioma") != idioma_nuevo:
            config_app["idioma"] = idioma_nuevo
            guardar_config(config_app)
            
            nonlocal diccionario_textos
            diccionario_textos = cargar_idioma(idioma_nuevo)
            aplicar_traduccion_al_vuelo()
            page.update()

    dropdown_idioma.on_change = cambiar_idioma_inmediato

    # --- PESTAÑA DE AYUDA (Constructora) ---
    def crear_paso(numero, titulo, descripcion, icono):
        return ft.Row([
            ft.Container(
                content=ft.Text(str(numero), weight="bold", size=20, color="white"),
                alignment=ft.alignment.center,
                width=40,
                height=40,
                border_radius=20,
                bgcolor="blue700"
            ),
            ft.Column([
                ft.Row([ft.Icon(icono, size=18, color="blue200"), ft.Text(titulo, weight="bold", size=16)]),
                ft.Container(content=ft.Text(descripcion, color="grey300"),width=600)
            ], expand=True)
        ], alignment=ft.MainAxisAlignment.START, spacing=15)

    def construir_pestana_ayuda():
        return ft.Container(
            padding=30,
            content=ft.Column([
                ft.Text(t("help_titulo"), size=24, weight="bold"),
                ft.Text(t("help_desc"), color="grey400"),
                ft.Divider(height=30),
                
                ft.Text(t("help_pasos_titulo"), weight="bold", size=18),
                ft.Container(height=10),
                
                crear_paso(1, t("help_paso1_tit"), t("help_paso1_desc"), "settings"),
                ft.Container(height=10),
                crear_paso(2, t("help_paso2_tit"), t("help_paso2_desc"), "create_new_folder"),
                ft.Container(height=10),
                crear_paso(3, t("help_paso3_tit"), t("help_paso3_desc"), "filter_alt"),
                ft.Container(height=10),
                crear_paso(4, t("help_paso4_tit"), t("help_paso4_desc"), "search"),
                ft.Container(height=10),
                crear_paso(5, t("help_paso5_tit"), t("help_paso5_desc"), "open_in_new"),
                
                ft.Divider(height=40),
                
                ft.Text(t("help_sintaxis_tit"), weight="bold", size=18),
                ft.Text(t("help_sintaxis_desc"), color="grey400"),
                ft.Container(
                    padding=15,
                    bgcolor="grey900",
                    border_radius=5,
                    content=ft.Column([
                        ft.Text(t("help_sintaxis_frase"), size=13),
                        ft.Text(t("help_sintaxis_and"), size=13),
                        ft.Text(t("help_sintaxis_or"), size=13),
                        ft.Text(t("help_sintaxis_not"), size=13),
                    ])
                )
            ], spacing=10, scroll=ft.ScrollMode.AUTO)
        )

    # --- PESTAÑA ACERCA DE (Constructora) ---
    def construir_pestana_acerca_de():
        return ft.Container(
            padding=40,
            content=ft.Column([
                ft.Row([
                    ft.Image(src="icono_che.png", width=120, height=120, fit=ft.ImageFit.CONTAIN)
                ], alignment=ft.MainAxisAlignment.CENTER),
                
                ft.Row([
                    ft.Text("Che PDF", size=28, weight="bold")
                ], alignment=ft.MainAxisAlignment.CENTER),
                
                ft.Row([
                    ft.Text(
                        t("about_desc"), 
                        color="grey400", 
                        text_align=ft.TextAlign.CENTER
                    )
                ], alignment=ft.MainAxisAlignment.CENTER),
                
                ft.Divider(height=40),
                
                ft.Text(t("about_detalles_tit"), weight="bold", size=16),
                ft.Text(t("about_version").format(VERSION)),
                ft.Text(t("about_fecha")),
                ft.Text(t("about_licencia")),
                
                ft.Container(height=20),
                
                ft.Text(
                    t("about_desarrollo"),
                    italic=True,
                    size=15,
                    color="blue200"
                ),
                
                ft.Container(height=10),
                
                ft.Row([
                    ft.TextButton(
                        text=t("about_visitar"), 
                        icon="open_in_new",
                        url="https://sitiosdememoria.uy"
                    )
                ], alignment=ft.MainAxisAlignment.CENTER)
                
            ])
        )

    # --- PESTAÑA DONAR (Constructora) ---
    def construir_pestana_donar():
        return ft.Container(
            padding=40,
            content=ft.Column([
                ft.Row([
                    ft.Image(src="aportar.png", width=120, height=120, fit=ft.ImageFit.CONTAIN)
                ], alignment=ft.MainAxisAlignment.CENTER),
                
                ft.Row([
                    ft.Text(t("donate_tit"), size=28, weight="bold")
                ], alignment=ft.MainAxisAlignment.CENTER),
                
                ft.Row([
                    ft.Text(
                        t("donate_desc"), 
                        color="grey400", 
                        text_align=ft.TextAlign.CENTER,
                        width=600
                    )
                ], alignment=ft.MainAxisAlignment.CENTER),
                
                ft.Container(height=30),
                
                ft.Row([
                    ft.ElevatedButton(
                        text=t("donate_btn"), 
                        icon="two_fingers_up", 
                        icon_color="pink400", 
                        url="https://ko-fi.com/sitiosdememoriauy",
                        style=ft.ButtonStyle(
                            bgcolor="grey900",
                            color="white",
                            padding=20
                        )
                    )
                ], alignment=ft.MainAxisAlignment.CENTER)
            ])
        )

    def guardar_config_al_cambiar_pestana(e):
        # Esta función corre en silencio cada vez que tocás una pestaña superior
        config_app["metodo_anio"] = radio_metodo_anio.value
        config_app["tamanio_max_db"] = int(dropdown_tamanio_db.value)
        config_app["modo_busqueda"] = radio_modo_busqueda.value

        try:
            config_app["limite_resultados"] = int(txt_limite.value)
        except ValueError:
            config_app["limite_resultados"] = 10000
            
        guardar_config(config_app)

    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=300,
        on_change=guardar_config_al_cambiar_pestana, 
        tabs=[
            ft.Tab(text=t("tab_busqueda"), icon="search", content=contenedor_principal),
            ft.Tab(text=t("tab_config"), icon="settings", content=contenedor_configuracion),
            ft.Tab(text=t("tab_ayuda"), icon="help", content=construir_pestana_ayuda()),
            ft.Tab(text=t("tab_acerca_de"), icon="info", content=construir_pestana_acerca_de()),
            ft.Tab(text=t("tab_donar"), icon="volunteer_activism", content=construir_pestana_donar())
        ],
        expand=1
    )

    page.add(encabezado, ft.Divider(), tabs)

if __name__ == '__main__':
    multiprocessing.freeze_support()
    
    if getattr(sys, 'frozen', False):
        ruta_base_real = os.path.dirname(sys.executable)
    else:
        ruta_base_real = os.path.dirname(os.path.abspath(__file__))

    ruta_assets_absoluta = os.path.join(ruta_base_real, "_internal", "assets")
    ft.app(target=main, assets_dir=ruta_assets_absoluta)
