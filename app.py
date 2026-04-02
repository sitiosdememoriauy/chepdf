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
        "limite_resultados": 10000,
        "idioma": obtener_idioma_sistema(),
        "carpetas_base": []
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

    # 2. Definir la función traductora
    def t(clave):
        
        return diccionario_textos.get(clave, clave)

    page.title = t("app_titulo")
    page.window.icon = "icono_che.ico" 
    page.theme_mode = "dark"
    page.padding = 10 
    
    txt_estado_indexacion = ft.Text(t("estado_reposo"), italic=True, color="blue300", size=13)

    config_app = cargar_config()

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
    
    txt_rango_anios = ft.Text("Filtro Temporal (Calculando...)", weight="bold", size=16)
    
    def on_slider_change(e):
        txt_rango_anios.value = f"Años: {int(slider_anios.start_value)} - {int(slider_anios.end_value)}"
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
    
    check_desconocidos = ft.Checkbox(label="Incluir docs sin año detectado", value=True, disabled=True)

    def actualizar_filtros_ui():
        estado_previo = {cb.data: cb.value for cb in lista_checkboxes.controls}
        info_carpetas = motor_sqlite.obtener_carpetas_unicas()
        lista_checkboxes.controls.clear()
        
        for ruta_completa, cantidad in info_carpetas.items():
            valor = estado_previo.get(ruta_completa, True)
            texto_mostrar = ruta_completa if estado_app["mostrar_rutas"] else os.path.basename(ruta_completa.rstrip(os.sep)) or "raiz"
            lista_checkboxes.controls.append(ft.Checkbox(label=f"{texto_mostrar} ({cantidad})", value=valor, data=ruta_completa, tooltip=ruta_completa))
        
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
            txt_rango_anios.value = f"Años: {int(slider_anios.start_value)} - {int(slider_anios.end_value)}"
        else:
            slider_anios.min = 1900
            slider_anios.max = 2030
            slider_anios.start_value = 1900
            slider_anios.end_value = 2030
            slider_anios.divisions = 130
            slider_anios.disabled = True
            check_desconocidos.disabled = True
            txt_rango_anios.value = "Filtro Temporal (Sin datos)"

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
        txt_estado_indexacion.value = "Deteniendo indexación de forma segura... Consolidando datos."
        btn_detener.disabled = True
        btn_detener.icon_color = "grey500" 
        page.update()

    btn_detener = ft.IconButton(icon="stop", icon_color="grey500", icon_size=30, tooltip="Detener indexación", disabled=True, on_click=detener_proceso)

    def on_carpeta_seleccionada(e: ft.FilePickerResultEvent):
        if e.path:
            # --- GUARDAR CARPETA BASE EN CONFIG ---
            ruta_abs = os.path.abspath(e.path)
            if "carpetas_base" not in config_app:
                config_app["carpetas_base"] = []
            if ruta_abs not in config_app["carpetas_base"]:
                config_app["carpetas_base"].append(ruta_abs)
                guardar_config(config_app)
            # --------------------------------

            def tarea_indexar():
                nombre_carpeta = os.path.basename(e.path)
                txt_estado_indexacion.value = f"Calculando el total de archivos en la carpeta '{nombre_carpeta}'..."
                
                btn_indexar.disabled = True
                btn_borrar_indice.disabled = True 
                btn_borrar_indice.icon_color = "grey500" 
                btn_detener.disabled = False
                btn_detener.icon_color = "red400"        
                page.update()
                
                # Agregamos los dos nuevos parámetros con valores por defecto
                def actualizar_interfaz(actual, total, ruta_carpeta_relativa, anio_doc=None, carpeta_terminada=False, total_carpeta=0):
                    
                    if carpeta_terminada:
                        for cb in lista_checkboxes.controls:
                            if cb.data == ruta_carpeta_relativa:
                                texto_mostrar = ruta_carpeta_relativa if estado_app["mostrar_rutas"] else os.path.basename(ruta_carpeta_relativa.rstrip(os.sep))
                                # Cambiamos el texto para mostrar el número final
                                cb.label = f"{texto_mostrar} ({total_carpeta})"
                                page.update()
                                break

                    txt_estado_indexacion.value = f"Indexando '{os.path.basename(ruta_carpeta_relativa)}': Archivo {actual} de {total}"
                    
                    carpetas_ui = [cb.data for cb in lista_checkboxes.controls]
                    if ruta_carpeta_relativa and ruta_carpeta_relativa not in carpetas_ui:
                        texto_mostrar = ruta_carpeta_relativa if estado_app["mostrar_rutas"] else os.path.basename(ruta_carpeta_relativa.rstrip(os.sep))
                        # Mejoramos el mensaje para que sea evidente que está trabajando
                        lista_checkboxes.controls.append(ft.Checkbox(label=f"{texto_mostrar} (Indexando...)", value=True, data=ruta_carpeta_relativa, tooltip=ruta_carpeta_relativa))
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
                                txt_rango_anios.value = f"Años: {int(slider_anios.start_value)} - {int(slider_anios.end_value)}"
                        except ValueError:
                            pass

                    if actual % 10 == 0 or actual == total:
                        page.update()
                
                motor_sqlite.indexar_documentos(e.path, metodo_anio=config_app.get("metodo_anio", "nombre_archivo"), callback_progreso=actualizar_interfaz)
                
                if motor_sqlite.detener_indexacion:
                    txt_estado_indexacion.value = "Deteniendo... Actualizando interfaz visual."
                    page.update()
                
                actualizar_filtros_ui() # <-- Primero actualizamos
                
                if motor_sqlite.detener_indexacion:
                    txt_estado_indexacion.value = "Indexación abortada por el usuario. Progreso guardado."
                else:
                    txt_estado_indexacion.value = f"¡Éxito! Se finalizó el análisis de la carpeta '{nombre_carpeta}'."
                
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
    dropdown_borrar = ft.Dropdown(label="¿Qué deseas borrar?", options=[], width=350)
    check_confirmacion = ft.Checkbox(label="Comprendo que esta acción es irreversible.")
    btn_confirmar_borrado = ft.TextButton("Borrar", style=ft.ButtonStyle(color="red400"), disabled=True)

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
        if seleccion == "⭐ TODAS LAS CARPETAS":
            resultado = motor_sqlite.borrar_indice()
            msj = "Índice completo borrado exitosamente. Listo para empezar de cero."
        else:
            resultado = motor_sqlite.borrar_indice_carpeta(seleccion)
            msj = f"Índice de '{seleccion}' borrado exitosamente."
        
        page.close(dlg_borrar)
        if resultado is True:
            txt_estado_indexacion.value = msj
            actualizar_filtros_ui() 
            lista_resultados.controls.clear()
            fila_paginador.visible = False
        else:
            txt_estado_indexacion.value = f"Error al borrar: {resultado}"
        page.update()

    btn_confirmar_borrado.on_click = ejecutar_borrado

    dlg_borrar = ft.AlertDialog(
        modal=True,
        title=ft.Text("Gestión del Índice"),
        content=ft.Column([texto_advertencia, dropdown_borrar, ft.Divider(), check_confirmacion], tight=True),
        actions=[ft.TextButton("Cancelar / Cerrar", on_click=cerrar_dialogo), btn_confirmar_borrado],
        actions_alignment="end"
    )

    def abrir_dialogo_borrado(e):
        info_carpetas = motor_sqlite.obtener_carpetas_unicas()
        if not info_carpetas:
            texto_advertencia.value = "El índice ya está completamente vacío."
            dropdown_borrar.visible = False
            check_confirmacion.visible = False
            btn_confirmar_borrado.visible = False
        else:
            texto_advertencia.value = "Selecciona si deseas borrar todo o solo una carpeta."
            opciones = [ft.dropdown.Option("⭐ TODAS LAS CARPETAS")]
            for c in info_carpetas.keys(): opciones.append(ft.dropdown.Option(c))
            dropdown_borrar.options = opciones
            dropdown_borrar.value = "⭐ TODAS LAS CARPETAS"  
            dropdown_borrar.visible = True
            check_confirmacion.visible = True
            check_confirmacion.value = False
            btn_confirmar_borrado.visible = True
            btn_confirmar_borrado.disabled = True
        page.open(dlg_borrar)
        page.update()

    btn_salir = ft.ElevatedButton("Salir de Che PDF", icon="exit_to_app")

    def salir_app(e):
        hilo = estado_app["hilo_indexacion"]
        if hilo and hilo.is_alive():
            motor_sqlite.detener_indexacion = True
            txt_estado_indexacion.value = "Cerrando de forma segura... Guardando los últimos archivos."
            btn_indexar.disabled = True
            btn_detener.disabled = True
            btn_borrar_indice.disabled = True
            btn_salir.disabled = True
            page.update()
            hilo.join(timeout=2)
        page.window.close()
    btn_salir.on_click = salir_app

    # --- 4. ENSAMBLAJE DE BARRA LATERAL ---
    btn_indexar = ft.IconButton(icon="create_new_folder", icon_size=30, tooltip="Indexar carpeta", on_click=lambda _: selector_carpetas.get_directory_path())
    btn_borrar_indice = ft.IconButton(icon="delete_forever", icon_size=30, icon_color="red400", tooltip="Borrar Índice", on_click=abrir_dialogo_borrado)

    def alternar_vista_rutas(e):
        estado_app["mostrar_rutas"] = not estado_app["mostrar_rutas"]
        e.control.icon = "visibility" if estado_app["mostrar_rutas"] else "visibility_off"
        e.control.tooltip = "Ocultar rutas" if estado_app["mostrar_rutas"] else "Mostrar rutas"
        actualizar_filtros_ui()
    btn_alternar_vista = ft.IconButton(icon="visibility_off", tooltip="Mostrar rutas", on_click=alternar_vista_rutas)

    barra_lateral = ft.Container(
        width=250,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column([
            ft.Text("Indexar carpetas", weight="bold", size=16),
            ft.Row([btn_indexar, btn_detener, btn_borrar_indice], alignment=ft.MainAxisAlignment.START, spacing=15),
            ft.Divider(),
            
            txt_rango_anios,
            slider_anios,
            check_desconocidos,
            ft.Divider(),
            
            ft.Row([ft.Text("Filtro por Carpetas", weight="bold", size=16), btn_alternar_vista], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([ft.TextButton("Todas", on_click=seleccionar_todas), ft.TextButton("Ninguna", on_click=deseleccionar_todas)]),
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
    txt_busqueda = ft.TextField(label="Buscar término (ej: Cóndor)", expand=True, on_submit=lambda e: ejecutar_busqueda(nueva_busqueda=True))
    btn_buscar = ft.ElevatedButton("Buscar", icon="search", on_click=lambda e: ejecutar_busqueda(nueva_busqueda=True))
    
    lista_resultados = ft.ListView(expand=True, spacing=10, padding=10)

    btn_anterior = ft.ElevatedButton("Anterior", icon="arrow_back", on_click=lambda e: cambiar_pagina(-1))
    btn_siguiente = ft.ElevatedButton("Siguiente", icon="arrow_forward", on_click=lambda e: cambiar_pagina(1))
    txt_paginacion = ft.Text("Página 1 de 1", weight="bold")
    fila_paginador = ft.Row(controls=[btn_anterior, txt_paginacion, btn_siguiente], alignment="center", visible=False)

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
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(f'''<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0; url={url_final}"></head>
                <body style="background-color: #1e1e1e; color: #ffffff; display: flex; justify-content: center; align-items: center; height: 100vh;">
                    <h2>Abriendo documento en la página {pagina}...</h2>
                    <script>window.focus();</script>
                </body></html>''')
            
            # --- FORZAR PRIMER PLANO EN NAVEGADORES---
            uri_html = pathlib.Path(html_path).as_uri()
            page.launch_url(uri_html)
            
        except Exception as ex:
            txt_estado_busqueda.value = f"Error al abrir: {ex}"
            page.update()

    def cambiar_pagina(delta):
        estado_busqueda["pagina_actual"] += delta
        ejecutar_busqueda(nueva_busqueda=False)

    def ejecutar_busqueda(nueva_busqueda=True):
        consulta = txt_busqueda.value
        if not consulta: return
        if nueva_busqueda: estado_busqueda["pagina_actual"] = 1
            
        lista_resultados.controls.clear()
        txt_estado_busqueda.value = "Calculando resultados..."
        fila_paginador.visible = False
        page.update()

        carpetas_seleccionadas = [cb.data for cb in lista_checkboxes.controls if cb.value]
        if not carpetas_seleccionadas:
            txt_estado_busqueda.value = "Por favor, selecciona al menos una carpeta."
            page.update()
            return

        offset_actual = (estado_busqueda["pagina_actual"] - 1) * estado_busqueda["resultados_por_pagina"]

        anio_min = int(slider_anios.start_value) if not slider_anios.disabled else None
        anio_max = int(slider_anios.end_value) if not slider_anios.disabled else None
        incluir_desc = check_desconocidos.value
        
        # Lectura del límite de la configuración
        limite_max = int(config_app.get("limite_resultados", 10000))

        respuesta = motor_sqlite.buscar_texto(
            consulta_str=consulta, 
            carpetas_permitidas=carpetas_seleccionadas,
            limite=estado_busqueda["resultados_por_pagina"],
            offset=offset_actual,
            anio_min=anio_min,
            anio_max=anio_max,
            incluir_desconocidos=incluir_desc,
            limite_maximo=limite_max
        )

        if "error" in respuesta:
            txt_estado_busqueda.value = "⚠️ Error de sintaxis en la búsqueda."
            txt_estado_busqueda.color = "red400"
            page.update()
            return
            
        # --- MANEJO DEL EXCESO DE RESULTADOS ---
        if respuesta.get("excede_limite"):
            txt_estado_busqueda.value = f"⚠️ Se han encontrado más de {limite_max} resultados ({respuesta['total']} en total). Por favor aplique algún filtro adicional de año o carpeta para acotar los resultados o incluya más palabras clave."
            txt_estado_busqueda.color = "orange400"
            page.update()
            return

        total_hits = respuesta["total"]
        if total_hits == 0:
            txt_estado_busqueda.value = "No se encontraron resultados para esos filtros."
            txt_estado_busqueda.color = "grey400"
        else:
            txt_estado_busqueda.color = "grey400" # Restaura el color normal
            estado_busqueda["total_paginas"] = math.ceil(total_hits / estado_busqueda["resultados_por_pagina"])
            txt_estado_busqueda.value = f"🎯 ¡Éxito! La palabra generó {total_hits} hits. Mostrando página {estado_busqueda['pagina_actual']}."
            txt_paginacion.value = f"Página {estado_busqueda['pagina_actual']} de {estado_busqueda['total_paginas']}"
            
            btn_anterior.disabled = (estado_busqueda["pagina_actual"] == 1)
            btn_siguiente.disabled = (estado_busqueda["pagina_actual"] >= estado_busqueda["total_paginas"])
            fila_paginador.visible = True
            
            for res in respuesta["resultados"]:
                fragmentos = re.split(r'(<b>.*?</b>)', f"...{res['extracto']}...")
                spans_extracto = []
                for frag in fragmentos:
                    if frag.startswith('<b>') and frag.endswith('</b>'):
                        spans_extracto.append(ft.TextSpan(frag[3:-4], style=ft.TextStyle(color="red400", weight="bold")))
                    else:
                        spans_extracto.append(ft.TextSpan(frag))
                
                etiqueta_anio = f" [Año: {res['anio']}]" if res['anio'] and res['anio'] != "Desconocido" else " [Año: Desconocido]"
                btn_abrir = ft.TextButton(
                    text=f"📄 {os.path.basename(res['ruta'])}{etiqueta_anio} (Pág. {res['pagina']})",
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
        fila_paginador
    ], expand=True)

    # --- 6. PESTAÑAS Y CONTENEDORES PRINCIPALES ---
    encabezado = ft.Row([
        ft.Image(src="icono_che.png", width=60, height=60, fit=ft.ImageFit.CONTAIN),
        ft.Column([
            ft.Text("Che PDF", size=28, weight="w800"), 
            ft.Text(
                spans=[
                    ft.TextSpan("Un desarrollo de ", style=ft.TextStyle(size=12, color="grey400")),
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
    
    # 1. PRIMERO definimos los controles visuales (para que las funciones los puedan leer)
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
            ft.Radio(value="nombre_archivo", label="Extraer desde el nombre del archivo (Ej: '2020-09-05 - 5 DEDOS.pdf')"),
            ft.Radio(value="carpeta", label="Extraer desde la carpeta que lo contiene (Ej: 'Archivos/1976/')"),
            ft.Radio(value="metadatos", label="Extraer desde los metadatos internos del PDF (creationDate)"),
        ])
    )
    
    txt_limite = ft.TextField(
        label="Límite máximo de resultados por búsqueda",
        value=str(config_app.get("limite_resultados", 10000)),
        width=300,
        keyboard_type=ft.KeyboardType.NUMBER
    )
    
    txt_feedback_config = ft.Text(color="transparent")

    # 2. DESPUÉS definimos la función que guarda los datos (ahora sí sabe qué es dropdown_idioma)
    def guardar_configuracion(e):
        config_app["metodo_anio"] = radio_metodo_anio.value
        config_app["idioma"] = dropdown_idioma.value

        try:
            config_app["limite_resultados"] = int(txt_limite.value)
        except ValueError:
            config_app["limite_resultados"] = 10000
            txt_limite.value = "10000"
            
        guardar_config(config_app)
        
        txt_feedback_config.value = t("msj_config_guardada")
        txt_feedback_config.color = "orange400"
        page.update()

    # 3. LUEGO creamos el botón que llama a la función
    btn_guardar_config = ft.ElevatedButton("Guardar Configuración", icon="save", on_click=guardar_configuracion)

    # 4. FINALMENTE ensamblamos todo en el contenedor visual
    contenedor_configuracion = ft.Container(
        padding=20,
        content=ft.Column([
            ft.Text("Configuración del Motor", size=20, weight="bold"),
            dropdown_idioma,
            ft.Divider(),
            ft.Text("Selecciona cómo quieres que el motor deduzca el año histórico al indexar.", color="grey400"),
            radio_metodo_anio,
            ft.Divider(),
            ft.Text("Rendimiento de Búsqueda", weight="bold"),
            ft.Text("Define el tope máximo de resultados antes de que el sistema te pida afinar la búsqueda. Esto previene tiempos de carga excesivos en repositorios masivos.", color="grey400"),
            txt_limite,
            ft.Container(height=10),
            btn_guardar_config,
            txt_feedback_config
        ])
    )

    # --- PESTAÑA DE AYUDA ---
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

    contenedor_ayuda = ft.Container(
        padding=30,
        content=ft.Column([
            ft.Text("Guía de Uso de Che PDF", size=24, weight="bold"),
            ft.Text("Che PDF te permite indexar y buscar texto dentro de documentos PDF históricos de forma eficiente, incluso en repositorios de gran volumen.", color="grey400"),
            ft.Divider(height=30),
            
            ft.Text("Paso a Paso: Guía Básica", weight="bold", size=18),
            ft.Container(height=10),
            
            crear_paso(1, "Configuración inicial", "Antes de empezar, ve a la pestaña 'Configuración' y selecciona el método de extracción del año histórico (nombre, carpeta o metadatos). Esto es vital para el filtro temporal.", "settings"),
            ft.Container(height=10),
            crear_paso(2, "Indexar tus archivos", "Usa el botón 'Crear nueva carpeta indexada' (icono de carpeta con un '+') en el panel izquierdo para seleccionar la carpeta raíz que contiene tus PDFs. El proceso comenzará automáticamente. Observa el Monitor del Sistema para el progreso.", "create_new_folder"),
            ft.Container(height=10),
            crear_paso(3, "Filtrar resultados (Panel Izquierdo)", "Una vez indexado, usa la barra deslizable ('Filtro Temporal') para acotar por rango de años o las casillas de verificación para seleccionar solo ciertas carpetas.", "filter_alt"),
            ft.Container(height=10),
            crear_paso(4, "Buscar", "Escribe tu término en la barra superior. Si hay demasiados resultados (según tu límite en Configuración), el sistema te pedirá afinar la búsqueda.", "search"),
            ft.Container(height=10),
            crear_paso(5, "Ver documentos", "Haz clic en el título de un documento para abrirlo en tu navegador por defecto, directamente en la página correcta y con el término resaltado.", "open_in_new"),
            
            ft.Divider(height=40),
            
            ft.Text("Sintaxis de Búsqueda Avanzada", weight="bold", size=18),
            ft.Text("El motor soporta la sintaxis potente de SQLite FTS5:", color="grey400"),
            ft.Container(
                padding=15,
                bgcolor="grey900",
                border_radius=5,
                content=ft.Column([
                    ft.Text("• Frase exacta: Usar comillas. Ej: \"ministerio de defensa\"", size=13),
                    ft.Text("• Operador AND: buscar palabras juntas (por defecto). Ej: condor AND acta", size=13),
                    ft.Text("• Operador OR: buscar una u otra. Ej: prisionero OR detenido", size=13),
                    ft.Text("• Operador NOT: excluir una palabra. Ej: condor NOT paraguay", size=13),
                ])
            )
        ], spacing=10, scroll=ft.ScrollMode.AUTO)
    )

    # --- PESTAÑA ACERCA DE ---
    contenedor_acerca_de = ft.Container(
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
                    "Motor avanzado de indexación y búsqueda documental, diseñado para procesar grandes volúmenes de archivos PDF.", 
                    color="grey400", 
                    text_align=ft.TextAlign.CENTER
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
            
            ft.Divider(height=40),
            
            ft.Text("Detalles del Proyecto", weight="bold", size=16),
            ft.Text("• Versión: 1.0"),
            ft.Text("• Fecha de creación: Marzo de 2026"),
            ft.Text("• Licencia: GNU GPLv3 (Software Libre) - Eres libre de usar, estudiar, compartir y modificar este software para cualquier propósito."),
            
            ft.Container(height=20),
            
            ft.Text(
                "Esta aplicación fue desarrollada por sitiosdememoria.uy con el objetivo de facilitar el análisis y la investigación de grandes volúmenes documentales. Cuenta con una licencia de software libre que permite su uso, estudio, difusión y modificación, como parte del compromiso del proyecto con las luchas por memoria, verdad y justicia.",
                italic=True,
                size=15,
                color="blue200"
            ),
            
            ft.Container(height=10),
            
            ft.Row([
                ft.TextButton(
                    text="Visitar sitiosdememoria.uy", 
                    icon="open_in_new",
                    url="https://sitiosdememoria.uy"
                )
            ], alignment=ft.MainAxisAlignment.CENTER)
            
        ])
    )

    # --- PESTAÑA DONAR ---
    contenedor_donar = ft.Container(
        padding=40,
        content=ft.Column([
            ft.Row([
                ft.Image(src="aportar.png", width=120, height=120, fit=ft.ImageFit.CONTAIN)
            ], alignment=ft.MainAxisAlignment.CENTER),
            
            ft.Row([
                ft.Text("Apoya el proyecto", size=28, weight="bold")
            ], alignment=ft.MainAxisAlignment.CENTER),
            
            ft.Row([
                ft.Text(
                    "Che PDF es y siempre será una herramienta de software libre y gratuita. Tu aporte voluntario nos ayuda a mantener nuestra infraestructura, desarrollar nuevas herramientas y continuar con el trabajo militante de investigación y preservación de la memoria histórica.", 
                    color="grey400", 
                    text_align=ft.TextAlign.CENTER,
                    width=600
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
            
            ft.Container(height=30),
            
            ft.Row([
                ft.ElevatedButton(
                    text="Hacer un aporte solidario", 
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

    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=300,
        tabs=[
            ft.Tab(text="Búsqueda Documental", icon="search", content=contenedor_principal),
            ft.Tab(text="Configuración", icon="settings", content=contenedor_configuracion),
            ft.Tab(text="Ayuda", icon="help", content=contenedor_ayuda),
            ft.Tab(text="Acerca de", icon="info", content=contenedor_acerca_de),
            ft.Tab(text="Donar", icon="volunteer_activism", content=contenedor_donar)
        ],
        expand=1
    )

    page.add(encabezado, ft.Divider(), tabs)

ft.app(target=main, assets_dir="_internal/assets")
