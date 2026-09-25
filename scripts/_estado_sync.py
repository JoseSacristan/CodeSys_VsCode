# Registro de que .st estan al dia con el proyecto CODESYS: guarda, por
# cada carpeta de .st, el hash MD5 de cada archivo tal como quedo la ultima
# vez que se importo desde CODESYS o se sincronizo hacia CODESYS. Con eso la
# GUI marca de antemano, al sincronizar, solo los archivos que cambiaron
# desde entonces.
#
# Lo usan dos interpretes distintos: scripts/sincronizar_codesys.py
# (IronPython 2.7 dentro de CODESYS), que es quien lo escribe, y
# gui_codesys.py (Python 3), que solo lo lee. Por eso no usa nada exclusivo
# de Python 3. Se comprobo que json y hashlib existen en el IronPython de
# CODESYS y que el MD5 de un mismo archivo da igual en los dos.
#
# El registro vive en estado_sincronizacion.json, en la raiz del repo (no en
# la carpeta de .st, para no ensuciar un repo de codigo PLC que ya tenga su
# propio control de versiones).

import hashlib
import io
import json
import os

ESTADO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "estado_sincronizacion.json",
)


def _clave_carpeta(src_dir):
    return os.path.normcase(os.path.abspath(src_dir))


def ruta_relativa(ruta_archivo, src_dir):
    """Ruta del .st relativa a src_dir, con / como separador. Es el formato
    de las claves del registro y de la lista de archivos elegidos en la GUI."""
    return os.path.relpath(ruta_archivo, src_dir).replace("\\", "/")


def hash_datos(datos):
    return hashlib.md5(datos).hexdigest()


def hash_archivo(ruta):
    with open(ruta, "rb") as f:
        return hash_datos(f.read())


def _leer_todo():
    try:
        with io.open(ESTADO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def leer(src_dir):
    """{ruta_relativa en minusculas: hash} de src_dir, o None si esa carpeta
    nunca se importo/sincronizo (o el registro no existe o esta corrupto).
    Las claves van en minusculas porque Windows no distingue mayusculas en
    las rutas: hay que buscar con ruta.lower()."""
    return _leer_todo().get(_clave_carpeta(src_dir))


def actualizar(src_dir, hashes, reemplazar=False):
    """Anota los hashes de src_dir. Con reemplazar=True (tras importar, que
    revisa todos los .st) se descarta lo anterior de esa carpeta; si no,
    se suman a lo que ya habia."""
    todo = _leer_todo()
    clave = _clave_carpeta(src_dir)
    if reemplazar or clave not in todo:
        todo[clave] = {}
    for ruta, valor in hashes.items():
        todo[clave][ruta.lower()] = valor
    # ensure_ascii (por defecto): el texto queda en ASCII puro, asi no hay
    # diferencias de str/unicode entre IronPython y Python 3 al escribirlo.
    # separators explicito: el de Python 2 deja un espacio al final de cada linea
    texto = json.dumps(todo, indent=4, sort_keys=True, separators=(",", ": "))
    with io.open(ESTADO_PATH, "w", encoding="utf-8") as f:
        f.write(u"" + texto + u"\n")
