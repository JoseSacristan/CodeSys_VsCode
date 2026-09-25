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
  compilar_proyecto.py       -> abre un .project, compila la aplicacion activa y
                                 reporta errores/warnings (exit code 0/1)
  sincronizar_codesys.py     -> importa POUs de CODESYS a la carpeta destino,
                                 o sube esa carpeta al proyecto + guarda, sin
                                 compilar (segun la variable CODESYS_ACCION)
  _pou_paths.py              -> helpers compartidos usados por sincronizar_codesys.py
  _estado_sync.py            -> registro de que .st estan al dia con el
                                 proyecto (lo usan el script y la GUI)
rutas_codesys.json          -> ultimo proyecto y carpeta de .st elegidos (lo
                                crea la GUI; no se versiona)
estado_sincronizacion.json  -> hash de cada .st tal como quedo en la ultima
                                importacion/sincronizacion, por carpeta (lo
                                crea sincronizar_codesys.py; no se versiona)
.vscode/
  settings.json           -> ruta al exe/perfil de CODESYS
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

El proyecto (`.project` o `.library`) y la carpeta de `.st` con los que
trabajas se guardan en `rutas_codesys.json`, en la raiz de este repo (a la
vista, no dentro de `.vscode/`, que es una carpeta oculta). Lo normal es
elegirlos desde la GUI con los botones **Buscar...**, que crean y actualizan
ese archivo; tambien se puede editar a mano:

```json
{
    "projectPath": "C:\\Proyectos\\MiMaquina.project",
    "srcDir": "C:\\Proyectos\\MiMaquina\\st"
}
```

Por defecto (`srcDir` vacio o ausente) los `.st` se guardan en `plc_src/`
dentro de este repo; poné otra carpeta si preferis una que ya tengas
versionada aparte, o una compartida entre varias maquinas.

Las tareas de VSCode leen ese mismo archivo: como `${config:...}` solo
puede leer `settings.json`, es `run-codesys-script.ps1` quien lo lee y pasa
las rutas a CODESYS (`CODESYS_PROJECT_PATH` / `CODESYS_SRC_DIR`). El archivo
esta en `.gitignore` porque las rutas son de cada maquina.

## Editar codigo ST en VSCode y sincronizarlo con CODESYS

Flujo de trabajo pensado para editar logica existente sin abrir la IDE de
CODESYS todo el rato. Se puede manejar desde la interfaz grafica
(`gui_codesys.py`) o desde las tareas de VSCode — ambas llaman a los mismos
scripts (`scripts/sincronizar_codesys.py` y `scripts/compilar_proyecto.py`).

1. **Importar**: vuelca todos los POUs del proyecto a `plc_src/*.st`,
   respetando la carpeta en la que estan organizados dentro de CODESYS. Cada
   archivo trae la declaracion (VAR...END_VAR) y la implementacion (el
   codigo ST) separadas por la linea `(*<<<CODESYS_IMPLEMENTATION>>>*)`.
   Se puede repetir cuando cambie algo en CODESYS: no pisa ni borra `.st`
   con cambios tuyos (ver "Importar sin perder trabajo local").
2. **Editar** los `.st` en VSCode, a mano o pidiendome ayuda directamente
   sobre esos archivos.
3. **Sincronizar**: sube el contenido de cada `.st` al POU correspondiente
   en el proyecto (por nombre y carpeta, no crea POUs nuevos) y guarda. No
   compila. Desde la GUI primero se eligen en un dialogo los archivos a
   subir (ver abajo); la tarea de VSCode sube todos.
4. **Compilar**: compila la aplicacion activa y muestra errores/warnings con
   archivo/linea aproximados.
5. Corregir en el `.st`, repetir los pasos 3 y 4 hasta que compile limpio.

Sincronizar y compilar son acciones separadas para poder trabajar tambien
con librerias (`.library`): se importan y sincronizan igual que un
`.project`, pero no tienen aplicacion activa, asi que "Compilar" sobre una
libreria termina con "el proyecto no tiene una aplicacion activa". El coste
es que en un `.project` son dos arranques de CODESYS en vez de uno.

**Limitacion actual:** el sync solo actualiza POUs que ya existen en el
proyecto. Si creas un `.st` nuevo en `plc_src/` sin que exista ese POU en
CODESYS, el script lo avisa y lo salta en vez de crearlo — hay que crear el
POU una vez desde la IDE de CODESYS (tipo, nombre, lenguaje ST, en la
carpeta que corresponda) y despues sincronizar el `.st`. Importar antes no
pisa tu `.st` (el POU recien creado esta vacio y tu archivo no estaba en la
ultima importacion: avisa y lo deja).

### Importar sin perder trabajo local

Importar usa el mismo registro de hashes que el dialogo de sincronizar
(`estado_sincronizacion.json`) para saber que `.st` siguen tal cual
salieron de la ultima importacion/sincronizacion, y con eso decide archivo
por archivo:

| Situacion del `.st` | Que hace importar |
|---|---|
| Igual que en CODESYS | Nada (ni lo reescribe, asi conserva su fecha) |
| El POU es nuevo en CODESYS | Lo crea |
| Cambio en CODESYS y no lo tocaste | Lo sobrescribe con la version de CODESYS |
| Lo cambiaste tu y CODESYS sigue igual | Lo deja: cambios pendientes de sincronizar |
| Cambio en CODESYS **y** lo cambiaste tu | Lo deja y avisa (conflicto) |
| Su POU se borro en CODESYS y no lo tocaste | Lo borra (y las carpetas que queden vacias) |
| Su POU se borro en CODESYS pero lo cambiaste | Lo deja y avisa |
| No estaba en la ultima importacion (lo creaste tu) | Lo deja y avisa |

Si hubo avisos, termina con codigo de salida 1. En un conflicto, para
quedarte con la version de CODESYS borra el `.st` (o descarta el cambio en
git) y vuelve a importar; para quedarte con la tuya, sincronizalo.

La primera importacion en una carpeta que ya tiene `.st` pero no tiene
registro (por ejemplo, una importada con una version anterior de estos
scripts) no puede saber que tocaste: solo escribe lo que falta o ya es
identico, y avisa de todo lo distinto o sobrante sin tocarlo. Desde ahi ya
hay registro.

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

Lo mas comodo: el acceso directo **PyCodesys** del escritorio. Apunta a
`pyw.exe` (el lanzador de Python sin ventana de consola) con
`C:\Fuentes\PyCodesys\gui_codesys.py` como argumento y el icono de
CODESYS. Si se mueve el repo o se pierde el acceso directo, se recrea asi
(PowerShell):

```powershell
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\PyCodesys.lnk")
$lnk.TargetPath = (Get-Command pyw).Source
$lnk.Arguments = '"C:\Fuentes\PyCodesys\gui_codesys.py"'
$lnk.WorkingDirectory = "C:\Fuentes\PyCodesys"
$lnk.IconLocation = "C:\Program Files\CODESYS 3.5.14.10\CODESYS\Common\CODESYS.exe,0"
$lnk.Save()
```

Tambien se puede abrir desde una terminal:

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
- Un campo con la ruta al `.project`/`.library` actual y un boton
  **Buscar...** (abre un selector de archivos, filtrado a `*.project` y
  `*.library`). La ruta elegida se guarda
  automaticamente en `rutas_codesys.json`, asi que queda sincronizada con
  las tareas de VSCode.
- Un campo con la carpeta donde se guardan/leen los `.st` (por defecto
  `plc_src/` de este repo) y su propio boton **Buscar...** (selector de
  carpetas). Igual que el proyecto, la carpeta elegida se guarda en
  `rutas_codesys.json`.
- Botones **Importar POUs** y **Sincronizar**, que llaman a
  `scripts/sincronizar_codesys.py` con `CODESYS_ACCION=importar` o
  `CODESYS_ACCION=sincronizar` respectivamente, y boton **Compilar**, que
  llama a `scripts/compilar_proyecto.py`; exactamente igual que las tareas
  de VSCode (mismo wrapper `run-codesys-script.ps1`).
- Al pulsar **Sincronizar** se abre antes un dialogo con el arbol de `.st`
  de la carpeta (mismas carpetas que en CODESYS) y una casilla por archivo
  y por carpeta, para elegir que subir:
  - Vienen marcados solo los que cambiaron desde la ultima importacion o
    sincronizacion, en naranja y con su estado: *modificado* (su contenido
    ya no es el que se importo/subio) o *nuevo* (no estaba en la ultima
    importacion; si el POU no existe en CODESYS se avisara y se saltara).
    Las carpetas que los contienen se abren solas.
  - Click en un archivo lo marca/desmarca (tambien con la barra
    espaciadora); click en una carpeta marca o desmarca todo lo que tiene
    dentro. Botones **Marcar todos**, **Desmarcar todos** y **Solo los
    cambiados**.
  - Si no hay registro previo de esa carpeta (primera vez), van todos
    marcados; desde esa sincronizacion ya se marcan solo los cambiados.

  La deteccion de cambios usa `estado_sincronizacion.json`:
  `sincronizar_codesys.py` guarda ahi el hash MD5 de cada `.st` al
  importar (los que quedan iguales a CODESYS) y al sincronizar (solo los
  que se subieron sin avisos),
  y la GUI lo compara con el contenido actual. Se compara contenido, no
  fecha de modificacion, asi que guardar un archivo sin cambios no lo
  marca. La lista elegida le llega al script en un `.txt` temporal
  (variable `CODESYS_LISTA_ARCHIVOS`); sin esa variable, como en la tarea
  de VSCode, se suben todos.
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
- **CODESYS: Importar POUs** / **CODESYS: Sincronizar** / **CODESYS:
  Compilar proyecto**: lo mismo que los botones de la GUI, para quien prefiera quedarse en VSCode
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
  errores), se probaron `leer_config()`/`guardar_ruta()` (lee el exe/perfil
  de `settings.json` con sus comentarios y las rutas de
  `rutas_codesys.json`) y se probo la misma cadena de
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

- **"Sincronizar y compilar" (cuando aun era una sola accion) se probo
  contra el mismo proyecto real**, con
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
  
  - Los `.st` se escriben/leen en UTF-8 explicito (`io.open`): el `open()`
    de IronPython 2.7 usa ASCII y rompia con `UnicodeEncodeError` al importar
    una libreria (`WaGenLib.library`) con un `≠` en los comentarios.

  Con estas correcciones, una compilacion real con 0 errores y 1 warning
  (un GVL no exportado) se reporto correctamente, coincidiendo con lo que
  CODESYS imprime por su cuenta en modo `--noUI`. Sigue sin
  probarse el caso con un **error** de verdad (solo warning), asi que si el
  formato de un mensaje de error se ve raro, es facil de ajustar viendo la
  salida real.

- **Sincronizacion selectiva** (dialogo de casillas + registro de
  cambios), probada contra una *copia* de `WaGenLib.library` (131 POUs):
  - Se comprobo antes que el IronPython de CODESYS tiene `json` y
    `hashlib`, y que el MD5 de un mismo archivo coincide con el de Python 3
    (el registro lo escribe uno y lo lee el otro).
  - Importar -> editar 2 `.st` y crear 1 nuevo -> el dialogo marco
    exactamente esos 3. Se probaron los clicks en archivo, en carpeta, en
    la flechita de desplegar (no marca) y la barra espaciadora.
  - Sincronizar eligiendo solo uno de los modificados, el nuevo (sin POU
    en el proyecto) y uno inexistente: subio solo el elegido, aviso de los
    otros dos, y al reimportar la copia en otra carpeta el cambio estaba
    en la libreria y el otro modificado no. Despues, el dialogo seguia
    marcando el modificado no subido y el nuevo, y ya no el subido.
  - El camino completo del boton (lista en `.txt` temporal, que se borra
    al terminar) lanzado con `pyw.exe`, como desde el acceso directo.

- **Importar sin perder trabajo local**, probado contra otra copia de
  `WaGenLib.library`: con un script se borraron 3 POUs en CODESYS (uno con
  un metodo dentro) y se cambiaron 2; en disco se editaron 3 `.st` y se creo
  uno sin POU. La reimportacion hizo exactamente lo de la tabla: sobrescribio
  el cambiado solo en CODESYS, borro los 2 huerfanos sin tocar (y la carpeta
  del metodo, que quedo vacia), conservo el editado solo en disco sin avisar,
  y aviso sin tocar nada del conflicto, del huerfano editado y del creado a
  mano. El dialogo de sincronizar marcaba despues justo esos 4. Tambien se
  probo la primera importacion sobre una carpeta sin registro (no toco nada
  distinto) y que los bytes que escribe son identicos a los de la version
  anterior (incluidos caracteres no ASCII como el "distinto de").
