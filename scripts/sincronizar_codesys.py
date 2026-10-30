# Script unico para mover codigo ST entre el proyecto CODESYS y una carpeta
# de archivos .st (por defecto plc_src/, configurable).
#
# Que hace lo controla la variable de entorno CODESYS_ACCION:
#   CODESYS_ACCION=importar     -> vuelca los POUs del proyecto a la carpeta destino,
#                                  sin pisar ni borrar .st con cambios locales
#   CODESYS_ACCION=sincronizar  -> sube los .st de la carpeta al proyecto y guarda,
#                                  creando los objetos y carpetas nuevos
#
# Un .st se considera nuevo si no esta en el registro de hashes (ver abajo): si
# ya estaba y su objeto falta, es que se borro o renombro en CODESYS y no se
# vuelve a crear. Que objeto crear lo dice el principio de su declaracion.
#
# No compila: eso lo hace scripts/compilar_proyecto.py, por separado, para
# poder sincronizar tambien librerias (.library), que no tienen aplicacion
# activa que compilar.
#
# Tambien requiere CODESYS_PROJECT_PATH con la ruta al .project o .library.
# CODESYS_SRC_DIR es opcional: si no se define, se usa plc_src/ junto al repo.
# CODESYS_LISTA_ARCHIVOS es opcional y solo aplica a 'sincronizar': ruta a un
# .txt (UTF-8) con los .st a subir, uno por linea, relativos a la carpeta de
# .st y con / como separador. Lo genera la GUI con los archivos marcados en
# su dialogo; sin esa variable (tareas de VSCode) se suben todos.
#
# Solo se leen, escriben o borran archivos .st: cualquier otro archivo de la
# carpeta (notas .md, scripts de prueba...) no se sube al proyecto ni se
# borra nunca, y una carpeta que conserve alguno no cuenta como vacia.
#
# Tanto al importar como al sincronizar se anota el hash de cada .st que
# quedo al dia con el proyecto (scripts/_estado_sync.py), para que la GUI
# sepa cuales cambiaron despues y para que importar sepa cuales puede
# sobrescribir o borrar sin perder trabajo local.
#
# Pensado para lanzarse desde gui_codesys.py (la interfaz grafica) o desde
# las tareas de VSCode "CODESYS: Importar POUs" / "CODESYS: Sincronizar",
# que ya ponen estas variables de entorno.

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _estado_sync
import _pou_paths
import System

ACCIONES_VALIDAS = ("importar", "sincronizar")

# De que objetos puede colgar cada tipo de miembro. No sirve preguntar con
# hasattr(padre, "create_method"): una GVL tambien dice tenerlo
PADRES_ADMITIDOS = {
    "METHOD": ("PROGRAM", "FUNCTION_BLOCK", "INTERFACE"),
    "PROPERTY": ("PROGRAM", "FUNCTION_BLOCK", "INTERFACE"),
    "ACTION": ("PROGRAM", "FUNCTION_BLOCK"),
}

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
    print("ERROR: falta la variable de entorno CODESYS_PROJECT_PATH con la ruta al .project o .library")
    system.exit(1)

if not os.path.isfile(project_path):
    print("ERROR: no existe el archivo de proyecto: " + project_path)
    system.exit(1)


def listar_st_en_disco():
    """{ruta relativa en minusculas: ruta absoluta} de los .st de src_dir."""
    encontrados = {}
    for carpeta_actual, subcarpetas, archivos in os.walk(src_dir):
        subcarpetas[:] = [s for s in subcarpetas if not s.startswith(".")]
        for nombre in archivos:
            if nombre.endswith(".st"):
                ruta = os.path.join(carpeta_actual, nombre)
                encontrados[_estado_sync.ruta_relativa(ruta, src_dir).lower()] = ruta
    return encontrados


def borrar_carpetas_vacias(carpeta):
    """Tras borrar un .st, quita su carpeta y las de encima si quedaron
    vacias (sin pasar de src_dir)."""
    raiz = os.path.normcase(src_dir)
    while os.path.normcase(carpeta) != raiz and os.path.isdir(carpeta) and not os.listdir(carpeta):
        os.rmdir(carpeta)
        carpeta = os.path.dirname(carpeta)


def importar(project):
    """Trae los POUs del proyecto a src_dir sin perder trabajo local, usando
    el registro de hashes (_estado_sync) para saber que .st estan tal cual
    salieron de la ultima importacion/sincronizacion:
      - un .st que cambio en CODESYS se sobrescribe solo si no se toco en
        disco desde entonces; si se toco, se deja y se avisa (conflicto)
      - un .st que solo se toco en disco (CODESYS sigue igual) se deja tal
        cual: son cambios pendientes de sincronizar, no un conflicto
      - un .st cuyo POU ya no existe en el proyecto se borra solo si no se
        toco; si se toco (o nunca salio de una importacion), se deja y se avisa
    Sin registro previo de la carpeta no se sabe que se toco, asi que solo
    se escribe lo que no existe o ya es identico."""
    # Minusculas: Windows no distingue mayusculas en las rutas
    registro = _estado_sync.leer(src_dir)
    hay_registro = registro is not None
    registro = registro or {}
    en_disco = listar_st_en_disco()

    total = [0]
    sin_cambios = []
    actualizados = []
    nuevos = []
    pendientes = []
    borrados = []
    avisos = []
    hashes = {}

    def exportar_uno(obj):
        total[0] += 1
        ruta = _pou_paths.ruta_relativa(obj)
        carpeta = os.path.join(src_dir, *ruta[:-1])
        archivo = os.path.join(carpeta, ruta[-1] + ".st")
        ruta_rel = _estado_sync.ruta_relativa(archivo, src_dir)
        clave = ruta_rel.lower()
        en_disco.pop(clave, None)

        # Los mismos bytes que escribia antes io.open en modo texto (UTF-8,
        # saltos de linea de Windows), armados en memoria para poder comparar
        # por hash antes de escribir. UTF-8 explicito: open() de IronPython
        # 2.7 escribe en ASCII y rompe con cualquier caracter no ASCII del
        # codigo (acentos, el "distinto de" en comentarios, etc.)
        datos = unicode(_pou_paths.texto_a_archivo(obj)).replace(u"\n", u"\r\n").encode("utf-8")
        hash_nuevo = _estado_sync.hash_datos(datos)

        if os.path.isfile(archivo):
            hash_actual = _estado_sync.hash_archivo(archivo)
            if hash_actual == hash_nuevo:
                sin_cambios.append(ruta_rel)
                hashes[clave] = hash_nuevo
                return
            if registro.get(clave) != hash_actual:
                # Se toco en disco: se deja como esta. Se conserva su entrada
                # del registro para que la GUI lo siga viendo como modificado
                if clave in registro:
                    hashes[clave] = registro[clave]
                if registro.get(clave) == hash_nuevo:
                    # CODESYS sigue como en la ultima importacion/sincronizacion:
                    # solo hay cambios locales, pendientes de sincronizar
                    pendientes.append(ruta_rel)
                    return
                if clave in registro:
                    motivo = "cambio en CODESYS y tambien aqui sin sincronizar (conflicto)"
                elif hay_registro:
                    motivo = ("es distinto en CODESYS y no estaba en la ultima importacion"
                              " (puede tener cambios tuyos)")
                else:
                    motivo = ("es distinto en CODESYS y no hay registro previo de esta carpeta"
                              " para saber si tiene cambios tuyos")
                avisos.append(ruta_rel + ": " + motivo +
                              ": NO se sobrescribio. Para quedarte con la version de CODESYS, borra el"
                              " .st (o descarta el cambio en git) y vuelve a importar; para la tuya,"
                              " sincronizalo.")
                return
            actualizados.append(ruta_rel)
        else:
            if not os.path.isdir(carpeta):
                os.makedirs(carpeta)
            nuevos.append(ruta_rel)

        with open(archivo, "wb") as f:
            f.write(datos)
        hashes[clave] = hash_nuevo

    _pou_paths.recorrer_pous(project, exportar_uno)

    # Lo que queda en en_disco son .st sin POU en el proyecto
    for clave in sorted(en_disco):
        archivo = en_disco[clave]
        ruta_rel = _estado_sync.ruta_relativa(archivo, src_dir)
        if clave in registro and registro[clave] == _estado_sync.hash_archivo(archivo):
            os.remove(archivo)
            borrar_carpetas_vacias(os.path.dirname(archivo))
            borrados.append(ruta_rel)
            continue
        if clave in registro:
            hashes[clave] = registro[clave]
            motivo = "tiene cambios sin sincronizar"
        elif hay_registro:
            motivo = "no estaba en la ultima importacion (si es un POU nuevo, sincronizalo para crearlo)"
        else:
            motivo = "no hay registro previo de esta carpeta para saber si tiene cambios tuyos"
        avisos.append(ruta_rel + ": no existe en el proyecto, pero " + motivo + ": NO se borro.")

    # Nuevo punto de partida para detectar cambios: se descarta el registro
    # anterior de esta carpeta (salvo lo que se conservo arriba a proposito)
    guardar_estado(hashes, reemplazar=True)

    print("Importacion desde CODESYS a %s: %d POU(s) en el proyecto" % (src_dir, total[0]))
    print("  Sin cambios: %d" % len(sin_cambios))
    for titulo, lista in (("Nuevos", nuevos),
                          ("Actualizados (cambiaron en CODESYS)", actualizados),
                          ("Borrados (el POU ya no existe en el proyecto)", borrados),
                          ("Con cambios tuyos pendientes de sincronizar (se conservan)", pendientes)):
        print("  %s: %d" % (titulo, len(lista)))
        for ruta_rel in lista:
            print("    - " + ruta_rel)

    if avisos:
        print("Avisos durante la importacion:")
        for a in avisos:
            print("  - " + a)

    return not avisos


def guardar_estado(hashes, reemplazar=False):
    # Si falla, el importar/sincronizar en si ya se hizo: solo se avisa (la
    # GUI marcara de mas al sincronizar, no de menos)
    try:
        _estado_sync.actualizar(src_dir, hashes, reemplazar)
    except Exception as e:
        print("Aviso: no se pudo guardar el registro de sincronizacion (%s): %s" % (_estado_sync.ESTADO_PATH, e))


def leer_seleccion():
    """Archivos elegidos en la GUI, como {ruta en minusculas: ruta tal cual}
    (Windows no distingue mayusculas en las rutas). None si no se paso
    CODESYS_LISTA_ARCHIVOS, es decir, sincronizar todos."""
    ruta_lista = os.environ.get("CODESYS_LISTA_ARCHIVOS")
    if not ruta_lista:
        return None
    with io.open(ruta_lista, "r", encoding="utf-8-sig") as f:
        lineas = [linea.rstrip("\r\n").replace("\\", "/") for linea in f]
    return dict((linea.lower(), linea) for linea in lineas if linea)


def buscar_unico(project, segmentos):
    """El objeto en esa ruta del proyecto, o None si no existe."""
    encontrados = project.find(System.Array[str](segmentos))
    if len(encontrados) > 1:
        raise ValueError("'%s' es ambiguo: %d coincidencias en el proyecto" % ("/".join(segmentos), len(encontrados)))
    return encontrados[0] if len(encontrados) == 1 else None


def asegurar_carpetas(project, segmentos, carpetas_creadas):
    """El objeto en esa ruta del proyecto, creando las carpetas que falten.
    Las comprobaciones son necesarias: create_folder no valida nada, y crea
    sin error carpetas duplicadas o dentro de un dispositivo o de un POU."""
    actual = project
    for i in range(1, len(segmentos) + 1):
        camino = segmentos[:i]
        siguiente = buscar_unico(project, camino)
        if siguiente is None:
            # Del .st de un POU cuelgan sus metodos, en una carpeta de disco
            # con su nombre: esa carpeta no es una carpeta del proyecto
            if os.path.isfile(os.path.join(src_dir, *camino) + ".st"):
                raise ValueError("cuelga de %s.st, que tampoco esta en el proyecto (eligelo tambien,"
                                 " o mira por que no se pudo crear)" % "/".join(camino))
            if not hasattr(actual, "create_pou"):
                raise ValueError("no se puede crear la carpeta '%s' dentro de '%s'"
                                 " (revisa que la ruta coincida con la del proyecto)"
                                 % (camino[-1], actual.get_name()))
            actual.create_folder(camino[-1])
            siguiente = buscar_unico(project, camino)
            carpetas_creadas.append("/".join(camino))
        actual = siguiente
    return actual


def quitar_accesores_sin_archivo(propiedad, carpeta):
    """create_property crea siempre Get y Set. Si en disco solo esta uno, el
    otro se quita: un Set vacio haria escribible una propiedad de solo lectura
    y las escrituras se perderian sin error. Sin ninguno, se dejan los dos."""
    accesores = list(propiedad.get_children())
    sobrantes = [a for a in accesores if not os.path.isfile(os.path.join(carpeta, a.get_name() + ".st"))]
    if len(sobrantes) < len(accesores):
        for accesor in sobrantes:
            accesor.remove()


def crear_objeto(project, segmentos, declaracion, carpetas_creadas):
    """Crea en el proyecto el objeto de un .st nuevo (y las carpetas que le
    falten) y lo devuelve, aun con el contenido por defecto de CODESYS. Si no
    se puede, lanza una excepcion con el motivo."""
    nombre = segmentos[-1]
    clase, declarado = _pou_paths.clasificar_declaracion(declaracion)
    if clase is None:
        raise ValueError("su declaracion no empieza por PROGRAM, FUNCTION_BLOCK, FUNCTION, TYPE,"
                         " VAR_GLOBAL, INTERFACE, METHOD ni PROPERTY")
    if declarado and declarado.lower() != nombre.lower():
        raise ValueError("el archivo se llama %s pero su declaracion dice %s" % (nombre, declarado))

    if clase in PADRES_ADMITIDOS:
        padre = buscar_unico(project, segmentos[:-1]) if len(segmentos) > 1 else None
        clase_padre = None
        if padre is not None and hasattr(padre, "textual_declaration"):
            clase_padre, _ = _pou_paths.clasificar_declaracion(padre.textual_declaration.text)
        if clase_padre not in PADRES_ADMITIDOS[clase]:
            raise ValueError("%s tiene que ir en la carpeta de su padre, que debe existir y ser uno de: %s"
                             % (clase, ", ".join(PADRES_ADMITIDOS[clase])))
        if clase == "METHOD":
            return padre.create_method(nombre)
        if clase == "ACTION":
            return padre.create_action(nombre)
        propiedad = padre.create_property(nombre)
        quitar_accesores_sin_archivo(propiedad, os.path.join(src_dir, *segmentos))
        return propiedad

    contenedor = asegurar_carpetas(project, segmentos[:-1], carpetas_creadas)
    if not hasattr(contenedor, "create_pou"):
        raise ValueError("no se pueden crear objetos dentro de '%s'" % contenedor.get_name())
    if clase == "PROGRAM":
        return contenedor.create_pou(nombre, PouType.Program, ImplementationLanguages.st)
    if clase == "FUNCTION_BLOCK":
        return contenedor.create_pou(nombre, PouType.FunctionBlock, ImplementationLanguages.st)
    if clase == "FUNCTION":
        # CODESYS exige un tipo de retorno; el de verdad llega con la
        # declaracion del archivo, que se aplica justo despues
        return contenedor.create_pou(nombre, PouType.Function, ImplementationLanguages.st, "BOOL")
    if clase == "INTERFACE":
        return contenedor.create_interface(nombre)
    if clase == "TYPE":
        return contenedor.create_dut(nombre, DutType.Structure)
    return contenedor.create_gvl(nombre)


def comprobar_que_es_nuevo(ruta_relativa, registro):
    """Solo se crea lo que nunca estuvo en el proyecto: recrear un objeto que
    se borro o renombro en CODESYS desharia ese cambio sin que nadie lo pida."""
    if registro is None:
        raise ValueError("no hay registro previo de esta carpeta para saber si es nuevo o se borro"
                         " en CODESYS: importa y vuelve a sincronizar")
    if ruta_relativa.lower() in registro:
        raise ValueError("ya estuvo en el proyecto y su objeto no esta, asi que se borro o renombro en"
                         " CODESYS. Si ya no lo quieres, borra el .st; para volver a crearlo, sacalo"
                         " de la carpeta, importa, vuelve a ponerlo y sincroniza")


def sincronizar(project):
    if not os.path.isdir(src_dir):
        print("ERROR: no existe " + src_dir)
        print("Corre antes la accion 'importar' para generar los .st")
        return False

    seleccion = leer_seleccion()
    if seleccion is not None:
        print("Archivos elegidos para sincronizar: %d" % len(seleccion))

    registro = _estado_sync.leer(src_dir)
    actualizados = []
    creados = []
    carpetas_creadas = []
    avisos_sync = []
    vistos = set()
    hashes = {}

    # os.walk va de arriba abajo: el .st de un POU se trata antes que los de
    # sus metodos, que estan en una subcarpeta y necesitan que ya exista
    for carpeta_actual, subcarpetas, archivos in os.walk(src_dir):
        # Ni .git ni similares (la GUI tampoco las muestra): un .st de una
        # copia de seguridad oculta acabaria creando objetos en el proyecto
        subcarpetas[:] = [s for s in subcarpetas if not s.startswith(".")]
        for nombre_archivo in archivos:
            if not nombre_archivo.endswith(".st"):
                continue

            ruta_archivo = os.path.join(carpeta_actual, nombre_archivo)
            ruta_relativa = _estado_sync.ruta_relativa(ruta_archivo, src_dir)
            if seleccion is not None:
                if ruta_relativa.lower() not in seleccion:
                    continue
                vistos.add(ruta_relativa.lower())

            segmentos = ruta_relativa.split("/")
            segmentos[-1] = segmentos[-1][:-len(".st")]

            # Hash de lo que hay en disco *antes* de leerlo: si el archivo se
            # modifica mientras tanto, el registro queda con el viejo y la GUI
            # lo seguira viendo como cambiado (nunca al reves)
            hash_leido = _estado_sync.hash_archivo(ruta_archivo)

            # utf-8-sig: tolera el BOM si algun editor lo agrega al guardar
            with io.open(ruta_archivo, "r", encoding="utf-8-sig") as f:
                contenido = f.read()

            try:
                declaracion, implementacion = _pou_paths.archivo_a_texto(contenido)
            except ValueError as e:
                avisos_sync.append(ruta_relativa + ": " + str(e))
                continue

            encontrados = project.find(System.Array[str](segmentos))
            if len(encontrados) > 1:
                avisos_sync.append(ruta_relativa + ": nombre ambiguo, %d coincidencias en el proyecto" % len(encontrados))
                continue

            if len(encontrados) == 1:
                pou = encontrados[0]
                actualizados.append(ruta_relativa)
            else:
                try:
                    comprobar_que_es_nuevo(ruta_relativa, registro)
                    pou = crear_objeto(project, segmentos, declaracion, carpetas_creadas)
                except Exception as e:
                    avisos_sync.append(ruta_relativa + ": no se creo: " + str(e))
                    continue
                creados.append(ruta_relativa)

            avisos_pou = _pou_paths.aplicar_textos(pou, declaracion, implementacion)
            for a in avisos_pou:
                avisos_sync.append(ruta_relativa + ": " + a)
            # Con avisos el POU no quedo igual que el archivo (se ignoro una
            # parte): no se da por sincronizado
            if not avisos_pou:
                hashes[ruta_relativa] = hash_leido

    if seleccion is not None:
        for clave in sorted(set(seleccion) - vistos):
            avisos_sync.append(seleccion[clave] + ": ya no existe en la carpeta de .st")

    if avisos_sync:
        print("Avisos durante la sincronizacion:")
        for a in avisos_sync:
            print("  - " + a)

    print("Sincronizados %d archivo(s):" % len(actualizados))
    for a in actualizados:
        print("  - " + a)

    for titulo, lista in (("Objetos creados en el proyecto", creados),
                          ("Carpetas creadas en el proyecto", carpetas_creadas)):
        if lista:
            print("%s: %d" % (titulo, len(lista)))
            for a in lista:
                print("  - " + a)

    if actualizados or creados:
        project.save()
        print("Proyecto guardado (para compilar, usa la accion Compilar aparte).")
        guardar_estado(hashes)

    return not avisos_sync


print("Abriendo proyecto: " + project_path)
project = projects.open(project_path)

if accion == "importar":
    ok = importar(project)
else:
    ok = sincronizar(project)

project.close()

system.exit(0 if ok else 1)
