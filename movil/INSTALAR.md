# Skynet móvil 0.7: manejar Skynet del PC desde el móvil

Novedades de la 0.7: al abrir solo está la nebulosa, limpia. Un toque abre el chat; si la mantienes
pulsada brotan tus apps (cada una una pequeña nebulosa con su red de plexo) y aparecen las estrellas.
Arrastrar el dedo juega con la nebulosa y «atrás» vuelve al inicio. El pie de cada respuesta muestra
minutos y horas.

## 1. PC: Skynet al día
El acceso desde el móvil ya está en `main`. Abre `.\skynet web` como siempre.

## 2. Tailscale (una vez): ver `ACCESO-MOVIL.md`
Tailscale en PC y móvil con la misma cuenta, MagicDNS + HTTPS activados, y en el PC: `tailscale serve --bg 8765`.

## 3. Móvil: instalar `Skynet-movil-0.7.apk`
Se instala encima de las anteriores (misma firma) y conserva el emparejado. Toca **Demo** › **Conectar con mi PC** › escanea el QR de
**Configuración › Dispositivos › Añadir móvil** en el PC.

## Archivos
- Código de la app: `movil/www` (interfaz) y `movil/android` (`build.sh` genera el APK).
- La clave de firma no está en el repo; úsala siempre para que las versiones se actualicen sin desinstalar.
