# Utilidades compartidas por scripts/sincronizar_codesys.py.
#
# No usa ninguna variable global inyectada por CODESYS (system, projects, ...),
# solo metodos de los objetos que le pasan los scripts que si la importan.
# Por eso es seguro importarlo con un simple "import _pou_paths".

import re

MARCADOR_IMPLEMENTACION = "(*<<<CODESYS_IMPLEMENTATION>>>*)"

# Se usa cuando el objeto no tiene esa parte como texto en absoluto:
#   - sin declaracion textual: pasa en acciones/transiciones, que comparten
#     las variables del POU padre y no tienen su propio VAR...END_VAR.
#   - sin implementacion textual: pasa cuando el cuerpo es grafico
#     (LD, FBD, CFC, o el propio grafo de un SFC), CODESYS no lo expone
#     como texto editable via scripting.
SIN_TEXTO = "(*<<<CODESYS_SIN_TEXTO_AQUI>>>*)"

# Como empieza la declaracion de los objetos que llevan su nombre en ella
_RE_DECLARACION = re.compile(
    r"(PROGRAM|FUNCTION_BLOCK|FUNCTION|INTERFACE|METHOD|PROPERTY|TYPE)\b"
    r"(?:\s+(?:PUBLIC|PRIVATE|PROTECTED|INTERNAL|ABSTRACT|FINAL)\b)*"
    r"\s+(\w+)",
    re.IGNORECASE | re.UNICODE)
_RE_GVL = re.compile(r"VAR_GLOBAL\b", re.IGNORECASE)


def es_pou_textual(obj):
    """True si el objeto tiene alguna parte de codigo textual (declaracion
    y/o implementacion). La mayoria de POUs y GVL tienen declaracion; solo
    los que estan en ST/IL tienen ademas implementacion textual."""
    return hasattr(obj, "textual_declaration") or hasattr(obj, "textual_implementation")


def ruta_relativa(obj):
    """Lista de nombres desde la raiz del proyecto hasta obj (sin incluir el proyecto)."""
    partes = [obj.get_name()]
    actual = obj.parent
    while actual is not None and not getattr(actual, "is_root", False):
        partes.append(actual.get_name())
        actual = actual.parent
    partes.reverse()
    return partes


def recorrer_pous(raiz, callback):
    """Recorre recursivamente el arbol bajo raiz y llama callback(obj) por cada objeto textual."""
    for hijo in raiz.get_children():
        if es_pou_textual(hijo):
            callback(hijo)
        recorrer_pous(hijo, callback)


def texto_a_archivo(obj):
    """Arma el contenido del .st a partir de un objeto real de CODESYS,
    usando SIN_TEXTO para las partes que ese objeto no tiene."""
    declaracion = obj.textual_declaration.text if hasattr(obj, "textual_declaration") else SIN_TEXTO
    implementacion = obj.textual_implementation.text if hasattr(obj, "textual_implementation") else SIN_TEXTO
    return declaracion + "\n" + MARCADOR_IMPLEMENTACION + "\n" + implementacion


def archivo_a_texto(contenido):
    partes = contenido.split(MARCADOR_IMPLEMENTACION, 1)
    if len(partes) != 2:
        raise ValueError("falta el marcador " + MARCADOR_IMPLEMENTACION)
    declaracion, implementacion = partes
    if declaracion.endswith("\n"):
        declaracion = declaracion[:-1]
    if implementacion.startswith("\n"):
        implementacion = implementacion[1:]
    return declaracion, implementacion


def _saltar_encabezado(texto):
    """Quita del principio de una declaracion los blancos, comentarios (los
    (* *) pueden ir anidados) y pragmas {attribute ...}."""
    i = 0
    while i < len(texto):
        if texto[i].isspace():
            i += 1
        elif texto.startswith("//", i) or texto.startswith("{", i):
            fin = texto.find("\n" if texto[i] == "/" else "}", i)
            i = len(texto) if fin < 0 else fin + 1
        elif texto.startswith("(*", i):
            nivel = 1
            i += 2
            while i < len(texto) and nivel:
                if texto.startswith("(*", i):
                    nivel += 1
                    i += 2
                elif texto.startswith("*)", i):
                    nivel -= 1
                    i += 2
                else:
                    i += 1
        else:
            break
    return texto[i:]


def clasificar_declaracion(declaracion):
    """Que objeto describe la declaracion de un .st, como (clase, nombre):
      - clase: "PROGRAM", "FUNCTION_BLOCK", "FUNCTION", "INTERFACE", "METHOD",
        "PROPERTY", "TYPE", "GVL", "ACTION" (sin declaracion propia) o None si
        no se reconoce (por ejemplo el VAR...END_VAR de un Get/Set)
      - nombre: el que trae escrito la declaracion, None si no lleva (GVL y
        acciones: su nombre es solo el del archivo)"""
    if declaracion == SIN_TEXTO or not declaracion.strip():
        return "ACTION", None
    cuerpo = _saltar_encabezado(declaracion)
    if _RE_GVL.match(cuerpo):
        return "GVL", None
    m = _RE_DECLARACION.match(cuerpo)
    if m:
        return m.group(1).upper(), m.group(2)
    return None, None


def aplicar_textos(obj, declaracion, implementacion):
    """Escribe declaracion/implementacion en obj. Devuelve una lista de
    avisos (texto) si el archivo trae contenido real para una parte que
    ese objeto no admite (por ejemplo, ST escrito a mano para un POU cuyo
    cuerpo es grafico)."""
    avisos = []

    if declaracion != SIN_TEXTO:
        if hasattr(obj, "textual_declaration"):
            obj.textual_declaration.replace(declaracion)
        elif declaracion.strip():
            avisos.append("trae texto de declaracion pero este objeto no admite declaracion textual (se ignoro)")

    if implementacion != SIN_TEXTO:
        if hasattr(obj, "textual_implementation"):
            obj.textual_implementation.replace(implementacion)
        elif implementacion.strip():
            avisos.append("trae texto de implementacion pero este objeto no admite implementacion textual, probablemente su cuerpo es grafico LD/FBD/CFC (se ignoro)")

    return avisos


def formatear_mensaje(m):
    """Formatea un IScriptMessage para imprimir. position_text puede ser
    None (avisos que no apuntan a una linea concreta, como un archivo no
    exportado), asi que no se puede concatenar directo con +."""
    if m.position_text:
        return m.position_text + ": " + m.text
    return m.text
