# Interfaz grafica minima para la integracion VSCode <-> CODESYS de este
# proyecto. Corre con el Python normal de la VM (py.exe / Python 3), NO con
# el IronPython embebido en CODESYS: ese no tiene Tkinter disponible (se
# comprobo directamente: "No module named Tkinter"/"tkinter").
#
# Lanza CODESYS.exe en modo --noUI a traves de .vscode/run-codesys-script.ps1
# (el mismo wrapper que usan las tareas de VSCode) para tres acciones:
#   - Importar POUs: trae el codigo de los POUs del proyecto a la carpeta
#     destino elegida (por defecto plc_src/*.st)
#   - Sincronizar: sube esos .st al proyecto y lo guarda (sin compilar, asi
#     sirve tambien para librerias .library). Antes muestra un dialogo con
#     casillas para elegir que archivos subir, con los que cambiaron desde
#     la ultima importacion/sincronizacion ya marcados.
#   - Compilar: compila la aplicacion activa y reporta errores/warnings
#
# Uso: py gui_codesys.py
# (o desde VSCode, con este archivo abierto: Ctrl+Shift+B, o Ctrl+Shift+P ->
# "Tasks: Run Task" -> "PyCodesys: Abrir interfaz grafica")
#
# Ctrl+Shift+B normalmente ejecuta el archivo activo *a traves de CODESYS*
# (IronPython), que no tiene Tkinter -> por eso run-codesys-script.ps1 tiene
# un caso especial: si el script es este archivo, lo lanza con el Python
# normal de la VM en vez de mandarlo a CODESYS.

import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Registro compartido con scripts/sincronizar_codesys.py (que corre en el
# IronPython de CODESYS) de que .st estan al dia con el proyecto
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
import _estado_sync  # noqa: E402
SETTINGS_PATH = os.path.join(BASE_DIR, ".vscode", "settings.json")
# Ultimo proyecto y carpeta de .st elegidos. Van en un archivo visible en la
# raiz del repo, no en .vscode/ (carpeta oculta). Tambien lo lee
# run-codesys-script.ps1, asi las tareas de VSCode usan las mismas rutas.
RUTAS_PATH = os.path.join(BASE_DIR, "rutas_codesys.json")
WRAPPER_PATH = os.path.join(BASE_DIR, ".vscode", "run-codesys-script.ps1")
SCRIPT_SINCRONIZAR = os.path.join(BASE_DIR, "scripts", "sincronizar_codesys.py")
SCRIPT_COMPILAR = os.path.join(BASE_DIR, "scripts", "compilar_proyecto.py")
SRC_DIR_POR_DEFECTO = os.path.join(BASE_DIR, "plc_src")

CREATE_NO_WINDOW = 0x08000000


def leer_rutas():
    """Lee rutas_codesys.json ({"projectPath": ..., "srcDir": ...}). Si no
    existe todavia (primera vez), devuelve las rutas vacias."""
    try:
        with open(RUTAS_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def leer_config():
    """Lee codesys.exePath / codesys.profile de settings.json y
    projectPath / srcDir de rutas_codesys.json.

    settings.json admite comentarios (formato jsonc de VSCode), asi que se
    extraen los valores con regex en vez de json.load para no romper con
    los comentarios.
    """
    with open(SETTINGS_PATH, "r") as f:
        contenido = f.read()

    def extraer(clave):
        patron = r'"' + re.escape(clave) + r'"\s*:\s*"((?:[^"\\]|\\.)*)"'
        m = re.search(patron, contenido)
        if not m:
            return ""
        return json.loads('"' + m.group(1) + '"')

    rutas = leer_rutas()
    return {
        "exePath": extraer("codesys.exePath"),
        "profile": extraer("codesys.profile"),
        "projectPath": rutas.get("projectPath", ""),
        "srcDir": rutas.get("srcDir", ""),
    }


def guardar_ruta(clave, nuevo_valor):
    """Guarda una ruta (projectPath o srcDir) en rutas_codesys.json,
    conservando la otra. Crea el archivo si no existe."""
    rutas = leer_rutas()
    rutas[clave] = nuevo_valor
    with open(RUTAS_PATH, "w", encoding="utf-8") as f:
        json.dump(rutas, f, indent=4, ensure_ascii=False)
        f.write("\n")


def listar_st(src_dir):
    """Rutas relativas (con /) de todos los .st bajo src_dir, ordenadas como
    un arbol: en cada nivel primero las carpetas y luego los archivos."""
    rutas = []
    for carpeta_actual, subcarpetas, archivos in os.walk(src_dir):
        # .git y similares: nunca tienen .st y pueden ser enormes
        subcarpetas[:] = [s for s in subcarpetas if not s.startswith(".")]
        for nombre in archivos:
            if nombre.endswith(".st"):
                rutas.append(_estado_sync.ruta_relativa(os.path.join(carpeta_actual, nombre), src_dir))

    def orden(ruta):
        partes = ruta.lower().split("/")
        return [(0, p) for p in partes[:-1]] + [(1, partes[-1])]

    return sorted(rutas, key=orden)


def _imagen_casilla(maestro, estado):
    """Casilla de 13x13 px dibujada a mano ("marcado", "vacio" o "parcial"):
    ttk.Treeview no trae checkboxes, y los caracteres Unicode de casilla
    dependen de la fuente."""
    tam = 13
    img = tk.PhotoImage(master=maestro, width=tam, height=tam)
    img.put("#ffffff", to=(0, 0, tam, tam))
    for i in range(tam):
        for x, y in ((i, 0), (i, tam - 1), (0, i), (tam - 1, i)):
            img.put("#555555", to=(x, y, x + 1, y + 1))
    if estado == "marcado":
        for x, y in ((3, 5), (4, 6), (5, 7), (6, 6), (7, 5), (8, 4), (9, 3)):
            img.put("#1f5fbf", to=(x, y, x + 1, y + 2))
    elif estado == "parcial":
        img.put("#1f5fbf", to=(3, 3, tam - 3, tam - 3))
    return img


class DialogoSeleccion(tk.Toplevel):
    """Ventana modal con el arbol de .st de la carpeta y una casilla por
    archivo y por carpeta, para elegir cuales sincronizar. Vienen marcados
    los que cambiaron desde la ultima importacion/sincronizacion (o todos, si
    no hay registro de esa carpeta). Al cerrarse deja en self.resultado la
    lista de rutas relativas elegidas, o None si se cancelo."""

    def __init__(self, padre, src_dir, rutas):
        tk.Toplevel.__init__(self, padre)
        self.title("Sincronizar - elige los archivos")
        self.transient(padre)
        self.geometry("700x520+%d+%d" % (padre.winfo_rootx() + 40, padre.winfo_rooty() + 20))
        self.minsize(480, 320)

        self.resultado = None
        self.imagenes = dict((e, _imagen_casilla(self, e)) for e in ("marcado", "vacio", "parcial"))
        self.marcado = {}      # item de archivo -> bool (las carpetas se calculan)
        self.ruta_de = {}      # item de archivo -> ruta relativa
        self.cambiados = set() # items de archivo modificados o nuevos

        self._construir_ui(src_dir)
        registro = _estado_sync.leer(src_dir)
        self._cargar(src_dir, rutas, registro)
        self._explicar(registro)
        self._refrescar()

        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        self.bind("<Escape>", lambda e: self._cancelar())
        self.bind("<Return>", lambda e: self._aceptar())
        self.grab_set()
        self.arbol.focus_set()
        self.wait_window()

    def _construir_ui(self, src_dir):
        tk.Label(self, text="Carpeta: " + src_dir, anchor="w").pack(fill="x", padx=10, pady=(10, 0))
        self.etiqueta_info = tk.Label(self, anchor="w", justify="left", fg="#555555")
        self.etiqueta_info.pack(fill="x", padx=10, pady=(2, 6))
        self.etiqueta_info.bind("<Configure>", lambda e: self.etiqueta_info.configure(wraplength=e.width))

        marco_arbol = tk.Frame(self)
        marco_arbol.pack(fill="both", expand=True, padx=10)
        self.arbol = ttk.Treeview(marco_arbol, columns=("estado", "fecha"), selectmode="browse")
        self.arbol.heading("#0", text="Archivo", anchor="w")
        self.arbol.heading("estado", text="Estado", anchor="w")
        self.arbol.heading("fecha", text="Modificado", anchor="w")
        self.arbol.column("#0", width=400, stretch=True)
        self.arbol.column("estado", width=90, stretch=False)
        self.arbol.column("fecha", width=120, stretch=False)
        self.arbol.tag_configure("cambiado", foreground="#b35900")
        barra = ttk.Scrollbar(marco_arbol, orient="vertical", command=self.arbol.yview)
        self.arbol.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.arbol.pack(side="left", fill="both", expand=True)
        self.arbol.bind("<Button-1>", self._al_hacer_click)
        self.arbol.bind("<space>", self._al_pulsar_espacio)

        marco_botones = tk.Frame(self, padx=10, pady=10)
        marco_botones.pack(fill="x")
        tk.Button(marco_botones, text="Marcar todos",
                  command=lambda: self._marcar(lambda item: True)).pack(side="left")
        tk.Button(marco_botones, text="Desmarcar todos",
                  command=lambda: self._marcar(lambda item: False)).pack(side="left", padx=6)
        self.boton_cambiados = tk.Button(marco_botones, text="Solo los cambiados",
                                         command=lambda: self._marcar(lambda item: item in self.cambiados))
        self.boton_cambiados.pack(side="left")

        tk.Button(marco_botones, text="Cancelar", width=10, command=self._cancelar).pack(side="right")
        self.boton_aceptar = tk.Button(marco_botones, text="Sincronizar", width=12, command=self._aceptar)
        self.boton_aceptar.pack(side="right", padx=6)
        self.etiqueta_contador = tk.Label(marco_botones)
        self.etiqueta_contador.pack(side="right", padx=6)

    def _cargar(self, src_dir, rutas, registro):
        carpetas = {(): ""}  # segmentos de la carpeta -> item del arbol
        for ruta in rutas:
            partes = tuple(ruta.split("/"))
            for i in range(1, len(partes)):
                if partes[:i] not in carpetas:
                    carpetas[partes[:i]] = self.arbol.insert(carpetas[partes[:i - 1]], "end", text=" " + partes[i - 1])

            ruta_abs = os.path.join(src_dir, *partes)
            if registro is None:
                estado = ""
            elif ruta.lower() not in registro:
                estado = "nuevo"
            elif registro[ruta.lower()] != _estado_sync.hash_archivo(ruta_abs):
                estado = "modificado"
            else:
                estado = ""
            fecha = time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(ruta_abs)))

            padre = carpetas[partes[:-1]]
            item = self.arbol.insert(padre, "end", text=" " + partes[-1], values=(estado, fecha),
                                     tags=("cambiado",) if estado else ())
            self.ruta_de[item] = ruta
            self.marcado[item] = registro is None or bool(estado)
            if estado:
                self.cambiados.add(item)
                # Desplegar las carpetas donde hay algo cambiado, para verlo
                # sin tener que buscarlo
                while padre:
                    self.arbol.item(padre, open=True)
                    padre = self.arbol.parent(padre)

    def _explicar(self, registro):
        if registro is None:
            texto = ("No hay registro de la ultima importacion/sincronizacion de esta carpeta, asi que "
                     "van todos marcados. Desde esta sincronizacion en adelante se marcaran solo los "
                     "archivos que cambien.")
            self.boton_cambiados.configure(state="disabled")
        elif self.cambiados:
            texto = ("Marcados los %d archivo(s) que cambiaron desde la ultima importacion/sincronizacion "
                     "(\"nuevo\" = no estaba en esa importacion; si el POU no existe en CODESYS, "
                     "se avisara y se saltara)." % len(self.cambiados))
        else:
            texto = "Ningun archivo cambio desde la ultima importacion/sincronizacion."
            self.boton_cambiados.configure(state="disabled")
        self.etiqueta_info.configure(text=texto)

    def _archivos_bajo(self, item):
        if item in self.marcado:
            return [item]
        archivos = []
        for hijo in self.arbol.get_children(item):
            archivos.extend(self._archivos_bajo(hijo))
        return archivos

    def _pintar(self, item):
        """Pone la casilla de item (y de todo lo que cuelga de el) segun lo
        marcado. Devuelve (archivos marcados, archivos totales) bajo item."""
        if item in self.marcado:
            self.arbol.item(item, image=self.imagenes["marcado" if self.marcado[item] else "vacio"])
            return (1 if self.marcado[item] else 0), 1
        marcados = total = 0
        for hijo in self.arbol.get_children(item):
            m, t = self._pintar(hijo)
            marcados += m
            total += t
        if item:
            if marcados == 0:
                estado = "vacio"
            elif marcados == total:
                estado = "marcado"
            else:
                estado = "parcial"
            self.arbol.item(item, image=self.imagenes[estado])
        return marcados, total

    def _refrescar(self):
        marcados, total = self._pintar("")
        self.etiqueta_contador.configure(text="%d de %d marcados" % (marcados, total))
        self.boton_aceptar.configure(state="normal" if marcados else "disabled")

    def _alternar(self, item):
        """Marca/desmarca un archivo, o todos los de una carpeta (si estaban
        todos marcados los desmarca; si no, los marca)."""
        archivos = self._archivos_bajo(item)
        nuevo = not all(self.marcado[a] for a in archivos)
        for a in archivos:
            self.marcado[a] = nuevo
        self._refrescar()

    def _marcar(self, criterio):
        for item in self.marcado:
            self.marcado[item] = criterio(item)
        self._refrescar()

    def _al_hacer_click(self, evento):
        if self.arbol.identify_region(evento.x, evento.y) not in ("tree", "cell"):
            return None
        if "indicator" in self.arbol.identify_element(evento.x, evento.y):
            return None  # la flechita de la carpeta: desplegar/plegar normal
        item = self.arbol.identify_row(evento.y)
        if not item:
            return None
        self.arbol.focus(item)
        self.arbol.selection_set(item)
        self._alternar(item)
        return "break"

    def _al_pulsar_espacio(self, evento):
        item = self.arbol.focus()
        if item:
            self._alternar(item)
        return "break"

    def _aceptar(self):
        elegidos = [self.ruta_de[item] for item in self.marcado if self.marcado[item]]
        if not elegidos:
            return
        self.resultado = elegidos
        self.destroy()

    def _cancelar(self):
        self.resultado = None
        self.destroy()


class AppCodesys(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("PyCodesys - VSCode <-> CODESYS")
        self.geometry("780x500")
        self.minsize(560, 360)

        self.config_actual = leer_config()
        self.project_path = tk.StringVar(value=self.config_actual["projectPath"])
        self.src_dir = tk.StringVar(value=self.config_actual["srcDir"] or SRC_DIR_POR_DEFECTO)
        self.cola_salida = queue.Queue()
        self.proceso_corriendo = False

        self._construir_ui()
        self._revisar_cola()

    def _construir_ui(self):
        marco_proyecto = tk.Frame(self, padx=10, pady=10)
        marco_proyecto.pack(fill="x")

        tk.Label(marco_proyecto, text="Proyecto CODESYS:", width=20, anchor="w").pack(side="left")
        self.entry_proyecto = tk.Entry(marco_proyecto, textvariable=self.project_path)
        self.entry_proyecto.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(marco_proyecto, text="Buscar...", command=self._elegir_proyecto).pack(side="left")

        marco_src = tk.Frame(self, padx=10, pady=0)
        marco_src.pack(fill="x")

        tk.Label(marco_src, text="Carpeta de archivos .st:", width=20, anchor="w").pack(side="left")
        self.entry_src = tk.Entry(marco_src, textvariable=self.src_dir)
        self.entry_src.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(marco_src, text="Buscar...", command=self._elegir_src_dir).pack(side="left")

        marco_botones = tk.Frame(self, padx=10, pady=4)
        marco_botones.pack(fill="x")

        self.botones = []
        for texto, accion in (("Importar POUs", "importar"),
                              ("Sincronizar", "sincronizar"),
                              ("Compilar", "compilar")):
            boton = tk.Button(marco_botones, text=texto, width=20,
                              command=lambda a=accion: self._ejecutar_accion(a))
            boton.pack(side="left", padx=(0, 8))
            self.botones.append(boton)

        self.texto_salida = scrolledtext.ScrolledText(self, state="disabled", font=("Consolas", 10))
        self.texto_salida.pack(fill="both", expand=True, padx=10, pady=10)

    def _elegir_proyecto(self):
        ruta = filedialog.askopenfilename(
            title="Selecciona el proyecto CODESYS",
            filetypes=[("Proyecto o libreria CODESYS", "*.project *.library"), ("Todos los archivos", "*.*")],
        )
        if not ruta:
            return
        self.project_path.set(ruta)
        guardar_ruta("projectPath", ruta)

    def _elegir_src_dir(self):
        ruta = filedialog.askdirectory(
            title="Selecciona la carpeta donde guardar/leer los .st",
            initialdir=self.src_dir.get() or BASE_DIR,
        )
        if not ruta:
            return
        ruta = os.path.normpath(ruta)
        self.src_dir.set(ruta)
        guardar_ruta("srcDir", ruta)

    def _log(self, texto):
        self.texto_salida.configure(state="normal")
        self.texto_salida.insert("end", texto + "\n")
        self.texto_salida.see("end")
        self.texto_salida.configure(state="disabled")

    def _limpiar_log(self):
        self.texto_salida.configure(state="normal")
        self.texto_salida.delete("1.0", "end")
        self.texto_salida.configure(state="disabled")

    def _ejecutar_accion(self, accion):
        if self.proceso_corriendo:
            messagebox.showinfo("PyCodesys", "Ya hay una accion en curso, espera a que termine.")
            return

        ruta_proyecto = self.project_path.get().strip()
        if not ruta_proyecto:
            messagebox.showwarning("PyCodesys", "Primero selecciona un proyecto CODESYS (.project o .library).")
            return
        if not os.path.isfile(ruta_proyecto):
            messagebox.showerror("PyCodesys", "No existe el archivo:\n" + ruta_proyecto)
            return

        config = leer_config()
        if not config["exePath"] or not os.path.isfile(config["exePath"]):
            messagebox.showerror(
                "PyCodesys",
                "No se encuentra CODESYS.exe en la ruta configurada.\n"
                "Revisa 'codesys.exePath' en .vscode/settings.json.",
            )
            return

        ruta_src = self.src_dir.get().strip() or SRC_DIR_POR_DEFECTO

        seleccion = None
        if accion == "sincronizar":
            rutas = listar_st(ruta_src) if os.path.isdir(ruta_src) else []
            if not rutas:
                messagebox.showwarning(
                    "PyCodesys",
                    "No hay archivos .st en:\n" + ruta_src + "\n\nUsa antes 'Importar POUs'.",
                )
                return
            seleccion = DialogoSeleccion(self, ruta_src, rutas).resultado
            if seleccion is None:
                return

        self._limpiar_log()
        self._log("Accion: " + accion)
        self._log("Proyecto: " + ruta_proyecto)
        self._log("Carpeta .st: " + ruta_src)
        if seleccion is not None:
            self._log("Archivos elegidos (%d):" % len(seleccion))
            for ruta in seleccion:
                self._log("  - " + ruta)
        self._log("")

        self.proceso_corriendo = True
        for boton in self.botones:
            boton.configure(state="disabled")

        hilo = threading.Thread(
            target=self._correr_proceso,
            args=(accion, ruta_proyecto, ruta_src, config, seleccion),
            daemon=True,
        )
        hilo.start()

    def _correr_proceso(self, accion, ruta_proyecto, ruta_src, config, seleccion):
        env = os.environ.copy()
        env.pop("CODESYS_LISTA_ARCHIVOS", None)
        ruta_lista = None
        if accion == "compilar":
            script = SCRIPT_COMPILAR
        else:
            script = SCRIPT_SINCRONIZAR
            env["CODESYS_ACCION"] = accion
            env["CODESYS_SRC_DIR"] = ruta_src

        comando = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", WRAPPER_PATH,
            "-ExePath", config["exePath"],
            "-ProfileName", config["profile"],
            "-ScriptPath", script,
            "-NoUI",
            "-ProjectPath", ruta_proyecto,
        ]

        try:
            if seleccion is not None:
                # La lista va en un archivo y no directo en la variable de
                # entorno: con cientos de POUs podria pasarse del limite de
                # longitud de una variable de entorno de Windows
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pycodesys_",
                                                 suffix=".txt", delete=False) as f:
                    f.write("\n".join(seleccion) + "\n")
                    ruta_lista = f.name
                env["CODESYS_LISTA_ARCHIVOS"] = ruta_lista

            proceso = subprocess.Popen(
                comando,
                env=env,
                # Sin consola propia cuando se abre con pyw.exe (acceso
                # directo del escritorio): stdin explicito para no heredar
                # un handle invalido
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            for linea in proceso.stdout:
                self.cola_salida.put(("linea", linea.rstrip("\n")))
            codigo = proceso.wait()
        except Exception as e:
            self.cola_salida.put(("linea", "ERROR lanzando CODESYS: " + str(e)))
            codigo = -1
        finally:
            if ruta_lista:
                try:
                    os.remove(ruta_lista)
                except OSError:
                    pass

        self.cola_salida.put(("fin", codigo))

    def _revisar_cola(self):
        try:
            while True:
                tipo, valor = self.cola_salida.get_nowait()
                if tipo == "linea":
                    self._log(valor)
                elif tipo == "fin":
                    self._log("")
                    self._log("(proceso terminado, codigo de salida %s)" % valor)
                    self.proceso_corriendo = False
                    for boton in self.botones:
                        boton.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._revisar_cola)


if __name__ == "__main__":
    app = AppCodesys()
    app.mainloop()
