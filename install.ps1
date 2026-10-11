# Prima installazione di Cheatsheet Viewer.
# Controlla Python, crea .venv, installa le dipendenze e verifica config.json.
# Non avvia il programma: per quello usa avvia.bat o avvia.ps1.
# Uso: powershell -ExecutionPolicy Bypass -File install.ps1 [-NoPause]
param([switch]$NoPause)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$failed = $false

function Step([string]$text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Ok([string]$text) { Write-Host "   OK: $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "   ATTENZIONE: $text" -ForegroundColor Yellow }

try {
    Step "1. Controllo Python"
    $pyVersion = python --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python non trovato nel PATH. Installalo da python.org e spunta 'Add python.exe to PATH'."
    }
    Ok $pyVersion

    Step "2. Ambiente virtuale (.venv)"
    if (Test-Path -LiteralPath $venvPython) {
        Ok "gia' presente, lo riuso"
    } else {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "creazione del venv fallita" }
        Ok "creato"
    }

    Step "3. Dipendenze"
    & $venvPython -m pip install --upgrade pip -q
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "installazione delle dipendenze fallita (controlla la connessione)" }
    & $venvPython -c "import webview, markdown, psutil, yaml"
    if ($LASTEXITCODE -ne 0) { throw "import delle dipendenze fallito" }
    Ok "pywebview, markdown, psutil, pyyaml installati"

    Step "4. Configurazione (config.json)"
    $cfgPath = Join-Path $root "config.json"
    if (-not (Test-Path -LiteralPath $cfgPath)) {
        Copy-Item -LiteralPath (Join-Path $root "config.example.json") -Destination $cfgPath
        Ok "config.json creato da config.example.json"
    }
    $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Ok "config.json valido"

    if ($cfg.vault) {
        if ($cfg.vault -like "*<utente>*") {
            Warn "imposta il percorso del tuo vault nella voce 'vault' di config.json."
        } elseif (Test-Path -LiteralPath $cfg.vault -PathType Container) {
            Ok "vault trovato: $($cfg.vault)"
        } else {
            Warn "vault non trovato: $($cfg.vault). Correggi la voce 'vault' in config.json."
        }
    } else {
        Warn "nessun vault configurato: verranno usate solo le voci di 'apps'."
    }

    foreach ($app in $cfg.apps.PSObject.Properties) {
        if (-not (Test-Path -LiteralPath (Join-Path $root $app.Value))) {
            Warn "guida mancante per $($app.Name): $($app.Value)"
        }
    }
}
catch {
    $failed = $true
    Write-Host "`nERRORE: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
if ($failed) {
    Write-Host "Installazione NON completata." -ForegroundColor Red
} else {
    Write-Host "Installazione completata. Avvia il programma con avvia.bat o avvia.ps1." -ForegroundColor Green
}
if (-not $NoPause) { Read-Host "Premi Invio per chiudere" | Out-Null }
exit ([int]$failed)
