# Usar Skynet desde el móvil (por Tailscale)

Skynet sigue escuchando solo en `127.0.0.1`. El móvil llega por **Tailscale**, una red privada entre tus
dispositivos: nada queda abierto a internet y no hay que tocar el router. Además, cada móvil necesita **su propia
llave**, que se consigue escaneando un QR en el PC y se puede quitar cuando quieras.

## Una sola vez

1. **PC**: instala Tailscale para Windows (https://tailscale.com/download) y entra con tu cuenta.
2. **Móvil**: instala Tailscale desde Play Store y entra con **la misma cuenta**.
3. En https://login.tailscale.com/admin/dns activa **MagicDNS** y **HTTPS Certificates**.
4. En el PC, en una terminal: `tailscale serve --bg 8765`
   Publica Skynet en `https://<tu-pc>.<tu-red>.ts.net` **solo dentro de tu red de Tailscale**. Con `--bg` se queda
   puesto aunque reinicies. Para quitarlo: `tailscale serve reset`.
5. Abre Skynet en el PC (`.\skynet web`) › **Configuración › Dispositivos › Añadir móvil**. Sale un QR.
6. En la app Skynet del móvil: toca **Demo** (arriba) › **Conectar con mi PC** › escanea el QR.

Listo: la app ya maneja Skynet del PC (chat, permisos, tareas, registro, modelos). Para usarla fuera de casa solo
hace falta que Tailscale esté activado en el móvil y Skynet abierto en el PC.

## Seguridad

- **Nunca uses `tailscale funnel`**: publicaría Skynet en internet. Skynet lo detecta y rechaza esas peticiones,
  y el Diagnóstico lo marca en rojo.
- Solo entra lo que viene de una IP de Tailscale, con Host `*.ts.net` y con la llave de un dispositivo emparejado.
- El QR vale **10 minutos y un solo uso**. Las llaves se guardan como hash en `data/dispositivos.json`.
- Desde el móvil **no** se puede: añadir repos, activar «Sin preguntar» ni gestionar dispositivos. Lo arriesgado
  te sigue pidiendo confirmación, ahora también en el móvil.
- Todo queda en el registro: emparejados, mensajes enviados desde el móvil, permisos respondidos e intentos rechazados.
- ¿Móvil perdido? En el PC: Configuración › Dispositivos › **Quitar**. Deja de entrar al momento.

## Dar acceso a otra persona

1. En la consola de Tailscale, **Share** tu PC con su cuenta (o invítala a tu red).
2. Que instale la app Skynet y Tailscale, y empareja su móvil con un QR nuevo.
3. Opcional, para limitar por cuenta, en `config/skynet.local.toml`:

```toml
[acceso]
usuarios_tailscale = ["tu-correo@gmail.com", "su-correo@gmail.com"]
```

## Opciones (`config/skynet.local.toml`, todas opcionales)

```toml
[acceso]
url = "https://mi-pc.tail1234.ts.net"     # si no se detecta sola con el CLI de Tailscale
origenes = ["https://app.skynet.local"]    # orígenes web permitidos (la app Android)
usuarios_tailscale = []                    # vacío = cualquier cuenta de tu red (con llave)
```
