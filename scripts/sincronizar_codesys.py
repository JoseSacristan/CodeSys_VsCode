# Script unico para mover codigo ST entre el proyecto CODESYS y una carpeta
# de archivos .st (por defecto plc_src/, configurable).
#
# Que hace lo controla la variable de entorno CODESYS_ACCION:
#   CODESYS_ACCION=importar     -> vuelca los POUs del proyecto a la carpeta destino
#   CODESYS_ACCION=sincronizar  -> sube los .st de la carpeta al proyecto, guarda,
#                                   compila la aplicacion activa y reporta
#                                   errores/warnings
#
# Tambien requiere CODESYS_PROJECT_PATH con la ruta al .project.
# CODESYS_SRC_DIR es opcional: si no se define, se usa plc_src/ junto al repo.
#
# Pensado para lanzarse desde gui_codesys.py (la interfaz grafica) o desde
# las tareas de VSCode "CODESYS: Importar POUs" / "CODESYS: Sincronizar y
# compilar", que ya ponen estas variables de entorno.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pou_paths
import System

ACCIONES_VALIDAS = ("importar", "sincronizar")

accion = os.environ.get("CODESYS_ACCION", "")
project_path = os.environ.get("CODESYS_PROJECT_PATH")

src_dir = os.environ.get("CODESYS_SRC_DIR")
if not src_dir:
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plc_src")
src_dir = os.path.abspath(src_dir)

if accion not in ACCIONES_VALIDAS:
    print("ERROR: CODESYS_ACCION debe ser 'importar' o 'sincronizar' (valor recibido: %r)" % accion)
    system.exit(1)

if not project_path:
    print("ERROR: falta la variable de entorno CODESYS_PROJECT_PATH con la ruta al .project")
    system.exit(1)

if not os.path.isfile(project_path):
    print("ERROR: no existe el archivo de proyecto: " + project_path)
    system.exit(1)


def importar(project):
    exportados = []

    def exportar_uno(obj):
        ruta = _pou_paths.ruta_relativa(obj)
        carpeta = os.path.join(src_dir, *ruta[:-1])
        if not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        archivo = os.path.join(carpeta, ruta[-1] + ".st")
        contenido = _pou_paths.texto_a_archivo(obj)
        with open(archivo, "w") as f:
            f.write(contenido)
        exportados.append("/".join(ruta))

    _pou_paths.recorrer_pous(project, exportar_uno)

    print("Importados %d POU(s) desde CODESYS a %s:" % (len(exportados), src_dir))
    for nombre in exportados:
        print("  - " + nombre)

    return True


def sincronizar(project):
    if not os.path.isdir(src_dir):
        print("ERROR: no existe " + src_dir)
        print("Corre antes la accion 'importar' para generar los .st")
        return False

    actualizados = []
    avisos_sync = []

    for carpeta_actual, _subcarpetas, archivos in os.walk(src_dir):
        for nombre_archivo in archivos:
            if not nombre_archivo.endswith(".st"):
                continue

            ruta_archivo = os.path.join(carpeta_actual, nombre_archivo)
            ruta_relativa = os.path.relpath(ruta_archivo, src_dir)
            segmentos = ruta_relativa.replace("\\", "/").split("/")
            segmentos[-1] = segmentos[-1][:-len(".st")]

            with open(ruta_archivo, "r") as f:
                contenido = f.read()

            try:
                declaracion, implementacion = _pou_paths.archivo_a_texto(contenido)
            except ValueError as e:
                avisos_sync.append(ruta_relativa + ": " + str(e))
                continue

            encontrados = project.find(System.Array[str](segmentos))
            if len(encontrados) == 0:
                avisos_sync.append(ruta_relativa + ": no existe ese POU en el proyecto (crealo una vez en la IDE de CODESYS y vuelve a importar)")
                continue
            if len(encontrados) > 1:
                avisos_sync.append(ruta_relativa + ": nombre ambiguo, %d coincidencias en el proyecto" % len(encontrados))
                continue

            pou = encontrados[0]
            avisos_pou = _pou_paths.aplicar_textos(pou, declaracion, implementacion)
            for a in avisos_pou:
                avisos_sync.append(ruta_relativa + ": " + a)
            actualizados.append(ruta_relativa)

    if avisos_sync:
        print("Avisos durante la sincronizacion:")
        for a in avisos_sync:
            print("  - " + a)

    print("Sincronizados %d archivo(s):" % len(actualizados))
    for a in actualizados:
        print("  - " + a)

    if not actualizados:
        print("Nada que compilar.")
        return not avisos_sync

    project.save()

    try:
        application = project.active_application
    except Exception:
        application = None

    if application is None:
        print("ERROR: el proyecto no tiene una aplicacion activa (Application) definida")
        return False

    print("")
    print("Compilando aplicacion activa...")
    application.build()

    # No hay una categoria de mensajes "de compilacion" fija y documentada:
    # se recorren todas las categorias activas (con al menos un mensaje
    # desde que arranco esta instancia de CODESYS) en vez de adivinar un guid.
    errores = []
    avisos_build = []
    for categoria in system.get_message_categories(True):
        errores.extend(system.get_message_objects(categoria, Severity.Error | Severity.FatalError))
        avisos_build.extend(system.get_message_objects(categoria, Severity.Warning))

    for m in avisos_build:
        print("[WARNING] " + _pou_paths.formatear_mensaje(m))
    for m in errores:
        print("[ERROR] " + _pou_paths.formatear_mensaje(m))

    print("")
    print("Resumen: %d error(es), %d warning(s)" % (len(errores), len(avisos_build)))

    return len(errores) == 0 and not avisos_sync


print("Abriendo proyecto: " + project_path)
project = projects.open(project_path)

if accion == "importar":
    ok = importar(project)
else:
    ok = sincronizar(project)

project.close()

system.exit(0 if ok else 1)
