$ErrorActionPreference = 'Stop'
$raizSkynet = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pythonSkynet = Join-Path $raizSkynet '.venv\Scripts\python.exe'
Push-Location $raizSkynet
try {
    & $pythonSkynet -c "from skynet.config import load_settings; from skynet.engines import load_engines; s=load_settings(); print(load_engines(s.engines,s.logs_dir,s.home).start('local'))"
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo encender el modelo. Revisa data/logs/local.log.' }
    $estadoSkynet = $null
    try { $estadoSkynet = Invoke-RestMethod 'http://127.0.0.1:8765/api/estado' -TimeoutSec 2 } catch {}
    if (-not $estadoSkynet) {
        Start-Process -FilePath $pythonSkynet -ArgumentList @('-m','skynet.cli','web','--no-abrir') -WorkingDirectory $raizSkynet -WindowStyle Hidden -RedirectStandardOutput (Join-Path $raizSkynet 'data\logs\web-pi.stdout.log') -RedirectStandardError (Join-Path $raizSkynet 'data\logs\web-pi.stderr.log')
        for ($intentoSkynet = 0; $intentoSkynet -lt 60; $intentoSkynet++) {
            Start-Sleep -Seconds 1
            try { $estadoSkynet = Invoke-RestMethod 'http://127.0.0.1:8765/api/estado' -TimeoutSec 2; break } catch {}
        }
    }
    if (-not $estadoSkynet) { throw 'La web no ha arrancado. Revisa data/logs/web-pi.stderr.log.' }
    Start-Process 'http://127.0.0.1:8765'
} finally { Pop-Location }
