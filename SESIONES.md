# Sesiones de trabajo

Resumen breve de lo que se avanzo en cada sesion, de la mas reciente a la
mas antigua. El detalle tecnico esta en `README.md` y en el historial de git.

## 2026-09-25 — v1.00

- La herramienta ya se usa en el trabajo diario: se considera madura y pasa
  a la version 1.00.
- Confirmado y documentado que los `.md` (y cualquier archivo que no sea
  `.st`) de la carpeta de trabajo no se sincronizan ni se borran.
- Quitados de README y SESIONES los nombres de proyectos y rutas locales
  (el repo es publico).

## 2026-09-25 — v0.02

- **Sincronizar eligiendo archivos:** al pulsar Sincronizar en la GUI se abre
  un dialogo con el arbol de `.st` y casillas por archivo y carpeta. Vienen
  marcados los modificados o nuevos desde la ultima importacion/sincronizacion.
- **Registro de cambios** (`estado_sincronizacion.json`, no versionado): hash
  MD5 de cada `.st` tal como quedo en la ultima importacion/sincronizacion.
  Lo escribe el script dentro de CODESYS y lo lee la GUI.
- **Importar sin perder trabajo local:** ya no pisa `.st` con cambios tuyos
  (avisa si hay conflicto), y borra los `.st` cuyo POU se elimino en CODESYS
  solo si no se tocaron.
- **Acceso directo "PyCodesys" en el escritorio** (`pyw.exe`, sin consola,
  con el icono de CODESYS).
- Todo probado contra copias de una libreria real.
- Se empieza este archivo.

## 2026-09-23 — v0.01

*(Reconstruida a partir del commit.)*

- Soporte de librerias (`.library`): sincronizar y compilar pasan a ser
  acciones separadas, porque una libreria no tiene aplicacion activa que
  compilar.
- Los `.st` se leen y escriben en UTF-8 (fallaba con el `≠` de una libreria real).
- El proyecto y la carpeta de `.st` elegidos se guardan en
  `rutas_codesys.json`, en la raiz del repo, y la carpeta de `.st` pasa a
  ser configurable.

## 2026-09-22 — v0.0

*(Reconstruida a partir de los commits.)*

- Integracion inicial VSCode <-> CODESYS V3.5 SP14: ejecutar scripts
  IronPython con `--runscript`/`--noUI`, a traves del wrapper
  `run-codesys-script.ps1` (necesario por como CODESYS lee `--profile`).
- Importar POUs a `.st` y sincronizarlos de vuelta, compilar, tareas de VSCode
  y la GUI en Tkinter (`gui_codesys.py`).

## Pendiente / ideas

- Crear en CODESYS los POUs nuevos a partir de un `.st` (hoy hay que crearlos
  a mano en la IDE).
- Probar "Compilar" con un error real de compilacion (solo se ha visto con
  warnings).
- La tarea de VSCode "Sincronizar" sube siempre todos los `.st`; la
  seleccion solo esta en la GUI.
