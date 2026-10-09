# Skynet móvil 0.2: manejar Skynet del PC desde el móvil

## 1. PC: aplicar `skynet-v5-movil.zip`
Descomprímelo encima de `C:\Skynet` (reemplaza archivos). Incluye todo lo de v4 (permisos y nube) más el acceso
desde el móvil, así que no hace falta aplicar v4 antes. Luego `.\skynet web` como siempre.

## 2. Tailscale (una vez): ver `ACCESO-MOVIL.md`
Tailscale en PC y móvil con la misma cuenta, MagicDNS + HTTPS activados, y en el PC: `tailscale serve --bg 8765`.

## 3. Móvil: instalar `Skynet-movil-0.2.apk`
Se instala encima de la 0.1 (misma firma). Toca **Demo** › **Conectar con mi PC** › escanea el QR de
**Configuración › Dispositivos › Añadir móvil** en el PC.

## Archivos
- `skynet-v5-movil.zip`: cambios para `C:\Skynet` (y `skynet-v5-movil-sobre-v4.patch`, solo lo nuevo sobre v4).
- `skynet-movil-codigo.zip`: código de la app (`www` + `android/build.sh`).
- `firma/`: clave de firma del APK; úsala siempre para que las versiones se actualicen sin desinstalar.
