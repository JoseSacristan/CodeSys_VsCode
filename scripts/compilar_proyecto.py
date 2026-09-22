# Abre un proyecto CODESYS, compila su aplicacion activa y reporta errores/warnings.
# Pensado para lanzarse desde la tarea de VSCode "CODESYS: Compilar proyecto"
# (te pedira la ruta al .project la primera vez que la ejecutes).
#
# Tambien se puede ejecutar a mano definiendo la variable de entorno antes de
# lanzar CODESYS, por ejemplo desde PowerShell:
#
#   $env:CODESYS_PROJECT_PATH = "C:\ruta\a\Proyecto.project"
#   & "C:\Program Files\CODESYS 3.5.14.10\CODESYS\Common\CODESYS.exe" `
#       --runscript="scripts\compilar_proyecto.py" --noUI `
#       --profile="CODESYS V3.5 SP14 Patch 1"
#
# Nota: se usa una variable de entorno (no --scriptargs) porque CODESYS separa
# --scriptargs por espacios, lo que rompe rutas de Windows tipicas.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pou_paths

project_path = os.environ.get("CODESYS_PROJECT_PATH")
if not project_path:
    print("ERROR: falta la variable de entorno CODESYS_PROJECT_PATH con la ruta al .project")
    system.exit(1)

if not os.path.isfile(project_path):
    print("ERROR: no existe el archivo de proyecto: " + project_path)
    system.exit(1)

print("Abriendo proyecto: " + project_path)
project = projects.open(project_path)

try:
    application = project.active_application
except Exception:
    application = None

if application is None:
    print("ERROR: el proyecto no tiene una aplicacion activa (Application) definida")
    project.close()
    system.exit(1)

print("Compilando aplicacion activa...")
application.build()

# No hay una categoria de mensajes "de compilacion" fija y documentada:
# se recorren todas las categorias activas (con al menos un mensaje desde
# que arranco esta instancia de CODESYS) en vez de adivinar un guid.
errores = []
avisos = []
for categoria in system.get_message_categories(True):
    errores.extend(system.get_message_objects(categoria, Severity.Error | Severity.FatalError))
    avisos.extend(system.get_message_objects(categoria, Severity.Warning))

for msg in avisos:
    print("[WARNING] " + _pou_paths.formatear_mensaje(msg))

for msg in errores:
    print("[ERROR] " + _pou_paths.formatear_mensaje(msg))

print("")
print("Resumen: %d error(es), %d warning(s)" % (len(errores), len(avisos)))

project.close()

if len(errores) > 0:
    system.exit(1)
else:
    system.exit(0)
