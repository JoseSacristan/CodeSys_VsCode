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
#     sirve tambien para librerias .library)
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
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

        self._limpiar_log()
        self._log("Accion: " + accion)
        self._log("Proyecto: " + ruta_proyecto)
        self._log("Carpeta .st: " + ruta_src)
        self._log("")

        self.proceso_corriendo = True
        for boton in self.botones:
            boton.configure(state="disabled")

        hilo = threading.Thread(
            target=self._correr_proceso,
            args=(accion, ruta_proyecto, ruta_src, config),
            daemon=True,
        )
        hilo.start()

    def _correr_proceso(self, accion, ruta_proyecto, ruta_src, config):
        env = os.environ.copy()
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
            proceso = subprocess.Popen(
                comando,
                env=env,
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
