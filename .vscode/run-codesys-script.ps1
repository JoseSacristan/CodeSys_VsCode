<#
    Lanza CODESYS.exe con --runscript apuntando al script indicado.

    Existe porque CODESYS.exe espera el parametro --profile pegado con
    comillas justo despues del signo igual (--profile="Nombre con espacios"),
    y ni el "type": "shell" (PowerShell reescribe/quita las comillas) ni el
    "type": "process" (VSCode/Node cita el token completo, no solo el valor)
    de tasks.json de VSCode logran reproducir exactamente ese formato cuando
    el nombre del perfil tiene espacios. Aqui se construye el command line a
    mano, en una sola cadena, que es la unica forma verificada que CODESYS
    acepta en modo --noUI.
#>
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$ProfileName,
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [switch]$NoUI,
    [string]$ProjectPath
)

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    Write-Error "No se encuentra el script: $ScriptPath"
    exit 1
}

# gui_codesys.py usa Tkinter, que el IronPython embebido en CODESYS no tiene
# (comprobado: "No module named queue"/"Tkinter"). Si Ctrl+Shift+B se pulsa
# con ese archivo abierto, lanzarlo con el Python normal de la VM en vez de
# mandarlo a CODESYS, para que "ejecutar el archivo activo" funcione siempre
# sin tener que acordarse de usar una tarea distinta para este archivo.
if ((Split-Path -Leaf $ScriptPath) -eq "gui_codesys.py") {
    $proc = Start-Process -FilePath "py" -ArgumentList "`"$ScriptPath`"" -NoNewWindow -PassThru -Wait
    exit $proc.ExitCode
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Error "No se encuentra CODESYS.exe en: $ExePath (revisa codesys.exePath en .vscode/settings.json)"
    exit 1
}

if ($ProjectPath) {
    $env:CODESYS_PROJECT_PATH = $ProjectPath
}

$argStr = "--runscript=`"$ScriptPath`""
if ($NoUI) {
    $argStr += " --noUI"
}
$argStr += " --profile=`"$ProfileName`""

$proc = Start-Process -FilePath $ExePath -ArgumentList $argStr -NoNewWindow -PassThru -Wait
exit $proc.ExitCode
