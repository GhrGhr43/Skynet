# Muestra qué motores de IA están encendidos, cuánta memoria usan y la VRAM ocupada.
# Opcional: pararlos todos. Lanzar con motores.cmd (doble clic).
$puertos = @{ 8090 = "Skynet (motor local)"; 8091 = "Comparador"; 1234 = "LM Studio (servidor)"; 20128 = "OmniRoute" }
Write-Host "`n=== Motores de IA encendidos ===`n" -ForegroundColor Cyan
$procs = Get-Process llama-server, lms, "LM Studio", *strata* -ErrorAction SilentlyContinue
if ($procs) {
    $procs | Select-Object Name, Id, @{n = 'RAM GB'; e = { [math]::Round($_.WorkingSet64 / 1GB, 1) } } | Format-Table -AutoSize
} else { Write-Host "Ningun motor encendido." -ForegroundColor Green }

Write-Host "Puertos en uso:" -ForegroundColor Cyan
foreach ($p in $puertos.Keys | Sort-Object) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { Write-Host ("  {0,-6} {1}  (proceso {2})" -f $p, $puertos[$p], (Get-Process -Id $c.OwningProcess).Name) -ForegroundColor Yellow }
}
try {
    $vram = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction Stop).CounterSamples |
        Measure-Object CookedValue -Maximum
    $gb = [math]::Round($vram.Maximum / 1GB, 1)
    $color = if ($gb -gt 3) { "Yellow" } else { "Green" }
    Write-Host "`nVRAM en uso: $gb GB de 16 (con todo apagado ronda 1-2 GB)" -ForegroundColor $color
} catch { Write-Host "`nNo pude leer la VRAM." }

if ($procs) {
    $r = Read-Host "`nParar todos los motores? (s/n)"
    if ($r -eq "s") {
        $procs | Where-Object { $_.Name -ne "LM Studio" } | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Host "Parados. (LM Studio no se cierra: expulsa sus modelos con Eject.)" -ForegroundColor Green
    }
}
