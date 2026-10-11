# Avvia Cheatsheet Viewer senza lasciare aperta una console.
# Alla prima esecuzione crea .venv e installa le dipendenze.
# Gli errori compaiono in una finestra di messaggio.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvPythonW = Join-Path $root ".venv\Scripts\pythonw.exe"

function Show-Error([string]$message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message, "Cheatsheet Viewer", "OK", "Error") | Out-Null
    exit 1
}

try {
    if (-not (Test-Path -LiteralPath $venvPythonW)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Creazione del venv fallita. Python e' installato e nel PATH?" }
        & $venvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "Installazione delle dipendenze fallita." }
    }
    $cfgPath = Join-Path $root "config.json"
    if (-not (Test-Path -LiteralPath $cfgPath)) {
        Copy-Item -LiteralPath (Join-Path $root "config.example.json") -Destination $cfgPath
    }
} catch {
    Show-Error $_.Exception.Message
}

# pythonw non apre una console: il programma parte e lo script termina.
Start-Process -FilePath $venvPythonW -ArgumentList "cheatsheet.py" -WorkingDirectory $root
