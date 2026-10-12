$ErrorActionPreference = 'Stop'
$raizPi = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pythonPi = Join-Path $raizPi '.venv\Scripts\python.exe'
Push-Location $raizPi
try {
    & $pythonPi (Join-Path $PSScriptRoot 'preparar.py')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar el modelo local.' }
    $servidorPi = $null
    try { $servidorPi = Invoke-RestMethod 'http://127.0.0.1:8765/api/estado' -TimeoutSec 2 } catch {}
    if (-not $servidorPi) {
        Start-Process -FilePath $pythonPi -ArgumentList @('-m','skynet.cli','web','--no-abrir') -WorkingDirectory $raizPi -WindowStyle Hidden -RedirectStandardOutput (Join-Path $raizPi 'data\logs\web-pi.stdout.log') -RedirectStandardError (Join-Path $raizPi 'data\logs\web-pi.stderr.log')
        for ($intentoPi = 0; $intentoPi -lt 60; $intentoPi++) {
            Start-Sleep -Seconds 1
            try { $servidorPi = Invoke-RestMethod 'http://127.0.0.1:8765/api/estado' -TimeoutSec 2; break } catch {}
        }
    }
    if (-not $servidorPi) { throw 'Skynet no ha arrancado. Mira data/logs/web-pi.stderr.log.' }
    if ($servidorPi.ocupado) { throw 'Skynet está trabajando. Pulsa Detener o espera antes de cambiar a Pi.' }
    $ajustesPi = @{ repo='prueba-pi'; modelo='local' } | ConvertTo-Json
    Invoke-RestMethod 'http://127.0.0.1:8765/api/ajustes' -Method Post -ContentType 'application/json' -Body $ajustesPi | Out-Null
    Start-Process 'http://127.0.0.1:8765'
} finally { Pop-Location }
