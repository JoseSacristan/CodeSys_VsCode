# PyCodesys — Automatizacion de CODESYS con scripts desde VSCode

Integracion entre VSCode y CODESYS V3.5 SP14 mediante el motor de scripting
propio de CODESYS (IronPython 2.7 embebido). Permite escribir y ejecutar
scripts `.py` desde VSCode que controlan la IDE de CODESYS: abrir proyectos,
compilarlos, generar codigo, exportar POUs, etc.

No es una extension de VSCode para editar programas IEC (ST/LD/FBD) dentro de
CODESYS: eso lo sigue haciendo la IDE de CODESYS. Lo que aqui se monta es la
capacidad de automatizar esa IDE desde fuera, con scripts versionables y
ejecutables con un atajo desde VSCode.

## Como funciona

CODESYS.exe acepta parametros de linea de comandos (documentados en
`ISystem.exit` dentro de `Online Help\en\ScriptEngine.chm`, y verificados a
mano en esta VM):

```
CODESYS.exe --runscript="C:\ruta\a\script.py" --noUI --profile="CODESYS V3.5 SP14 Patch 1"
```

- `--runscript="<ruta>.py"`: ejecuta ese script al arrancar.
- `--noUI`: no muestra la interfaz grafica; al terminar el script, CODESYS
  cierra el proceso solo (ideal para tareas/CI). Sin este flag, CODESYS se
  abre normalmente con su interfaz y el script se ejecuta igual.
- `--profile="<nombre>"`: **obligatorio** en modo `--noUI`. El nombre exacto
  instalado en esta VM es `CODESYS V3.5 SP14 Patch 1` (viene del archivo
  `CODESYS V3.5 SP14 Patch 1.profile` en la carpeta `Profiles` de la
  instalacion).
- `--scriptargs="a b c"`: pasa argumentos a `sys.argv`, pero CODESYS los
  separa por espacios — **no sirve para rutas de Windows con espacios**. Para
  pasar una ruta (p. ej. el `.project` a compilar) se usa mejor una variable
  de entorno antes de lanzar CODESYS (ver `scripts/compilar_proyecto.py`).

Dentro del script, CODESYS inyecta variables globales automaticamente (no se
importan, ya existen cuando el script arranca). Las mas utiles:

| Variable | Que es |
|---|---|
| `system` | Utilidades generales: `write_message()`, `exit()`, `get_message_objects()`, tipos como `Severity`, `PouType`, etc. |
| `projects` | Gestion de proyectos: `open()`, `create()`, `get_by_path()`, `.all`, `.primary` |
| `online` | Conexion/control online con el PLC |
| `librarymanager` | Gestion de librerias |
| `device_repository` | Repositorio de dispositivos/perfiles instalados |

Referencia completa de la API: `Online Help\en\ScriptEngine.chm` dentro de la
instalacion de CODESYS (interfaces `IScript*`, namespace
`_3S.CoDeSys.ScriptEngine.BasicFunctionality`).

**Importante:** son scripts IronPython 2.7, no Python 3. Evitar f-strings y
otra sintaxis exclusiva de Python 3.

## Estructura del proyecto

```
gui_codesys.py              -> interfaz grafica (Tkinter) para elegir el
                                proyecto e importar/sincronizar con un click
plc_src/                    -> carpeta por defecto para el codigo ST de los
                                POUs (configurable, ver mas abajo), un
                                archivo .st por objeto, reflejando la
                                estructura de carpetas del proyecto
scripts/
  hola_codesys.py            -> smoke test, no necesita ningun proyecto abierto
  compilar_proyecto.py       -> abre un .project, compila la aplicacion activa y
                                 reporta errores/warnings (exit code 0/1)
  sincronizar_codesys.py     -> importa POUs de CODESYS a la carpeta destino,
                                 o sube esa carpeta al proyecto + guarda + compila
                                 (segun la variable CODESYS_ACCION)
  _pou_paths.py              -> helpers compartidos usados por sincronizar_codesys.py
.vscode/
  settings.json           -> ruta al exe/perfil de CODESYS, al .project actual
                             y a la carpeta de archivos .st
  tasks.json              -> tareas para ejecutar scripts desde VSCode
  run-codesys-script.ps1  -> wrapper que arma el command line hacia CODESYS
```

### Por que existe `run-codesys-script.ps1`

CODESYS.exe exige que `--profile` vaya pegado asi: `--profile="Nombre con
espacios"` (comillas justo despues del `=`, dentro de una unica cadena de
argumentos). Ni las tareas `"type": "shell"` de VSCode (PowerShell reescribe
las comillas al reenviar el comando al ejecutable nativo) ni las `"type":
"process"` (VSCode/Node cita cada argumento completo, `"--profile=Nombre..."`,
en vez de solo el valor) logran reproducir exactamente ese formato cuando el
nombre del perfil tiene espacios — cosa que se comprobo a mano en esta VM:
ambas formas hacen que CODESYS ignore el perfil y, o bien aborte pidiendo uno,
o bien abra la interfaz completa en vez de quedarse en modo `--noUI`.

La solucion es que las tareas de `tasks.json` no llamen a CODESYS
directamente, sino a este script de PowerShell, pasandole `-ExePath`,
`-ProfileName` y `-ScriptPath` como parametros normales (esos si viajan bien
con espacios, porque no van pegados con `=`). El script arma el string exacto
que CODESYS necesita y lo lanza con `Start-Process`.

## Configurar el proyecto con el que trabajas

Antes de usar las tareas de compilar/exportar/sincronizar, pon la ruta a tu
`.project` una sola vez en `.vscode/settings.json` (o eligela desde la GUI,
que guarda ahi mismo):

```json
"codesys.projectPath": "C:\\Proyectos\\MiMaquina.project"
```

Por defecto los `.st` se guardan en `plc_src/` dentro de este repo. Si
preferis otra carpeta (por ejemplo, una que ya tengas versionada aparte, o
una compartida entre varias maquinas), poné la ruta en `codesys.srcDir`:

```json
"codesys.srcDir": "C:\\Proyectos\\MiMaquina\\st"
```

Vacio (el valor por defecto) usa `plc_src/` junto a este repo.

## Editar codigo ST en VSCode y sincronizarlo con CODESYS

Flujo de trabajo pensado para editar logica existente sin abrir la IDE de
CODESYS todo el rato. Se puede manejar desde la interfaz grafica
(`gui_codesys.py`) o desde las tareas de VSCode — ambas llaman al mismo
script (`scripts/sincronizar_codesys.py`).

1. **Importar una vez**: vuelca todos los POUs del proyecto a `plc_src/*.st`,
   respetando la carpeta en la que estan organizados dentro de CODESYS. Cada
   archivo trae la declaracion (VAR...END_VAR) y la implementacion (el
   codigo ST) separadas por la linea `(*<<<CODESYS_IMPLEMENTATION>>>*)`.
2. **Editar** los `.st` en VSCode, a mano o pidiendome ayuda directamente
   sobre esos archivos.
3. **Sincronizar y compilar**: sube el contenido de cada `.st` al POU
   correspondiente en el proyecto (por nombre y carpeta, no crea POUs
   nuevos), guarda, compila la aplicacion activa y muestra errores/warnings
   con archivo/linea aproximados.
4. Corregir en el `.st`, repetir el paso 3 hasta que compile limpio.

**Limitacion actual:** el sync solo actualiza POUs que ya existen en el
proyecto. Si creas un `.st` nuevo en `plc_src/` sin que exista ese POU en
CODESYS, el script lo avisa y lo salta en vez de crearlo — hay que crear el
POU una vez desde la IDE de CODESYS (tipo, nombre, lenguaje ST) y despues
volver a "Importar POUs" para que aparezca el archivo y ya se pueda
sincronizar en ambas direcciones.

**Objetos con lenguaje grafico (LD/FBD/CFC) o sin declaracion propia:**
CODESYS solo expone como texto editable el codigo en ST/IL. Muchos objetos
tienen solo una de las dos partes:
- Una GVL (lista de variables globales) o un POU cuyo cuerpo es grafico
  (LD/FBD/CFC, o el propio diagrama de un SFC) exporta su declaracion de
  variables normal, pero la parte de implementacion sale como
  `(*<<<CODESYS_SIN_TEXTO_AQUI>>>*)` — no hay nada editable ahi, es solo un
  marcador. El cuerpo grafico en si no se puede editar desde estos archivos.
- Una accion de un SFC (por ejemplo un paso implementado en ST) normalmente
  no tiene declaracion propia (usa las variables del POU padre), asi que la
  parte de declaracion sale con ese mismo marcador. Eso si es normal y
  esperable, no un error.

Al sincronizar, si dejas contenido real (no el marcador) en una parte que el
objeto no admite — por ejemplo escribiste ST en la implementacion de un POU
grafico — el script lo detecta, avisa en vez de fallar en silencio, y no
toca esa parte.

## Interfaz grafica (gui_codesys.py)

```
py gui_codesys.py
```

o desde VSCode, con `gui_codesys.py` como archivo activo: `Ctrl+Shift+B`, o
`Ctrl+Shift+P` -> "Tasks: Run Task" -> **PyCodesys: Abrir interfaz
grafica**. Ambas caminos funcionan igual.

`Ctrl+Shift+B` normalmente ejecuta el archivo activo *a traves de CODESYS*
(su IronPython, que no tiene Tkinter — daria `ImportError: No module named
queue` con este archivo). Por eso `run-codesys-script.ps1` tiene un caso
especial: si el script a ejecutar es `gui_codesys.py`, lo lanza con el
Python normal de la VM en vez de mandarlo a CODESYS, asi el atajo funciona
igual sin importar que archivo tengas abierto.

Ventana con:
- Un campo con la ruta al `.project` actual y un boton **Buscar...** (abre un
  selector de archivos, filtrado a `*.project`). La ruta elegida se guarda
  automaticamente en `codesys.projectPath` dentro de `.vscode/settings.json`,
  asi que queda sincronizada con las tareas de VSCode.
- Un campo con la carpeta donde se guardan/leen los `.st` (por defecto
  `plc_src/` de este repo) y su propio boton **Buscar...** (selector de
  carpetas). Igual que el proyecto, la carpeta elegida se guarda en
  `codesys.srcDir` dentro de `.vscode/settings.json`.
- Boton **Importar POUs** y boton **Sincronizar y compilar**, que llaman a
  `scripts/sincronizar_codesys.py` con `CODESYS_ACCION=importar` o
  `CODESYS_ACCION=sincronizar` respectivamente, exactamente igual que las
  tareas de VSCode (mismo wrapper `run-codesys-script.ps1`).
- Un panel de texto donde se ve la salida de CODESYS en vivo, linea por
  linea, mientras corre en segundo plano (los botones se deshabilitan
  mientras hay una accion en curso para evitar lanzar dos CODESYS a la vez).

Corre con el Python normal de la VM (`py`), **no** con el IronPython
embebido en CODESYS — se comprobo que ese IronPython no tiene Tkinter
disponible (`import Tkinter` / `import tkinter` fallan con "No module
named..."), por eso la GUI es un proceso aparte que lanza CODESYS por
fuera, igual que hacen las tareas de VSCode.

## Otras tareas de VSCode

- **CODESYS: Ejecutar script actual (sin interfaz)** (`Ctrl+Shift+B`, tarea
  de build por defecto): ejecuta el script `.py` abierto en el editor contra
  CODESYS en modo `--noUI`. La salida (`print()` y
  `system.write_message()`) aparece en el panel de terminal de VSCode.
- **CODESYS: Ejecutar script actual (con interfaz)**: igual, pero mostrando
  la IDE de CODESYS (util para depurar visualmente un script).
- **CODESYS: Compilar proyecto**: solo compila, sin tocar `plc_src/` (util
  si editaste algo directamente en la IDE de CODESYS).
- **CODESYS: Importar POUs** / **CODESYS: Sincronizar y compilar**: lo mismo
  que los botones de la GUI, para quien prefiera quedarse en VSCode
  (`Ctrl+Shift+P` -> "Tasks: Run Task").

## Escribir scripts nuevos

Cualquier `.py` dentro de `scripts/` (o en cualquier carpeta del workspace)
se puede ejecutar con la tarea de VSCode: solo hay que tenerlo abierto en el
editor activo y pulsar `Ctrl+Shift+B`. Patron tipico:

```python
project = projects.open(r"C:\ruta\a\Proyecto.project")

try:
    app = project.active_application
except Exception:
    app = None  # ver nota abajo: no siempre devuelve None, a veces lanza excepcion

app.build()

errores = system.get_message_objects(SV_POU, Severity.Error | Severity.FatalError)
for e in errores:
    print(e.position_text + ": " + e.text)

project.close()
system.exit(1 if errores else 0)
```

**Gotcha de la API:** `project.active_application` no siempre devuelve `None`
cuando el proyecto no tiene ninguna aplicacion (por ejemplo un proyecto
recien creado, sin dispositivo) — en ese caso lanza una excepcion
(`ScriptObjects requiere un Guid no vacío`). Por eso todos los scripts de
este repo envuelven ese acceso en `try/except` en vez de comparar contra
`None` directamente. Se descubrio probando contra un proyecto de prueba
vacio, no esta documentado explicitamente en el CHM.

Para pedirme ayuda escribiendo o revisando uno de estos scripts, basta con
abrir el archivo y pedirlo directamente — al ser texto plano (`.py`), lo edito
como cualquier otro archivo del repo.

## Si CODESYS se actualiza (cambia de version/parche)

La ruta del ejecutable y el nombre del perfil son especificos de la version
instalada. Si CODESYS se actualiza:

1. Buscar la nueva carpeta de instalacion: `Get-ChildItem "C:\Program Files\CODESYS*"`.
2. Buscar el nombre exacto del perfil:
   `Get-ChildItem "C:\Program Files\CODESYS <version>\CODESYS\Profiles"` (el
   nombre es el del archivo `.profile` sin la extension).
3. Actualizar `codesys.exePath` y `codesys.profile` en
   `.vscode/settings.json`.

## Notas de verificacion

Todo lo de arriba se probo de verdad contra la instalacion de esta VM, no es
solo teoria sacada de internet o del CHM:

- `--runscript`, `--noUI`, `--profile`, el nombre exacto del perfil,
  `--scriptargs` y el problema de espacios en rutas.
- El wrapper `run-codesys-script.ps1` completo, incluyendo con rutas de
  script con espacios.
- Crear un proyecto y un POU de prueba, leer/escribir su
  `textual_declaration` y `textual_implementation`, guardar, cerrar CODESYS
  por completo y reabrir el proyecto para confirmar que los cambios
  persistieron en disco (no solo en memoria).
- `find()` con un array de segmentos de ruta (`System.Array[str]([...])`)
  para localizar un POU exacto por su ubicacion en el arbol.
- El flujo completo de `sincronizar_codesys.py` en ambos modos (`importar` ->
  editar el `.st` a mano -> `sincronizar`), confirmando que el cambio llega
  al proyecto real.
- `gui_codesys.py`: se lanzo la ventana de verdad (arranca y responde, sin
  errores), se probaron `leer_config()`/`guardar_valor()` contra el
  `settings.json` real (preserva los comentarios, no rompe el resto de
  claves, incluyendo `codesys.srcDir`) y se probo la misma cadena de
  `subprocess.Popen` -> PowerShell -> `run-codesys-script.ps1` ->
  CODESYS.exe que usan los botones, incluyendo que la ruta al perfil (con
  espacios) llega bien y que la salida se recibe en vivo linea por linea.
- `CODESYS_SRC_DIR` (carpeta de `.st` configurable, no fija a `plc_src/`):
  se probo `sincronizar_codesys.py` en modo `importar` apuntando a una
  carpeta distinta, confirmando que ahi es donde termina escribiendo los
  archivos.
- **"Importar POUs" se probo contra un proyecto real de maquina** (mezcla de
  GVLs, un POU con cuerpo grafico y acciones en ST), no solo contra el
  proyecto de prueba vacio. Asi se encontro y corrigio un bug real: la
  primera version exigia declaracion Y implementacion a la vez para
  considerar un objeto "exportable", lo cual descartaba silenciosamente
  *todos* los objetos de un proyecto real (donde casi ningun objeto tiene
  ambas partes a la vez). Ahora basta con tener alguna de las dos, y la
  parte faltante se marca explicitamente con `SIN_TEXTO` en vez de omitirse.

- **"Sincronizar y compilar" se probo contra el mismo proyecto real**, con
  `application.build()` de verdad contra la aplicacion del proyecto. Encontro
  y corrigio dos bugs mas:
  - `SV_POU` **no** es el guid de categoria de mensajes de compilacion (esa
    suposicion inicial era incorrecta y tiraba `ArgumentNullException` al
    llamar `get_message_objects`). No existe una categoria "de compilacion"
    fija y documentada; la forma correcta es pedir
    `system.get_message_categories(True)` (las categorias con algun mensaje
    desde que arranco esa instancia de CODESYS) y recorrerlas todas.
  - `mensaje.position_text` puede ser `None` (avisos que no apuntan a una
    linea concreta, como un archivo no exportado) — concatenar con `+`
    directo rompia con `TypeError`. Ahora hay un helper
    (`_pou_paths.formatear_mensaje`) que lo maneja.
  
  Con estas correcciones, una compilacion real con 0 errores y 1 warning
  (un GVL no exportado) se reporto correctamente, coincidiendo con lo que
  CODESYS imprime por su cuenta en modo `--noUI`. Sigue sin
  probarse el caso con un **error** de verdad (solo warning), asi que si el
  formato de un mensaje de error se ve raro, es facil de ajustar viendo la
  salida real.
