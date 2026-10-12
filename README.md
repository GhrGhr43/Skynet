# Skynet

Agente personal de Daniel en Windows. **Pi oficial es el motor**: conserva sus herramientas
`read`, `bash`, `edit`, `write`, sus instrucciones, sesiones y compactación. Skynet aporta
la interfaz web, acceso desde el móvil, selección del modelo local, permisos y registro.
No añade planes obligatorios, bloques de 30 turnos, verificadores automáticos ni propuestas de skills.

## Empezar

1. Doble clic en [Abrir Skynet.cmd](Abrir%20Skynet.cmd): enciende el modelo si hace falta y abre
   [el chat](http://127.0.0.1:8765).
2. Elige el proyecto con el selector de carpeta y envía el objetivo completo en un mensaje.
3. Para conversar sin herramientas de archivos, selecciona **Sin repo** y **Solo repo**.
4. Pulsa **Pi** bajo el chat, o **+ → Harness, herramientas y MCP**, para configurar capacidades.
5. **Detener** interrumpe el proceso y conserva avances. `continúa` retoma la última tarea
   pendiente del chat. Los mensajes siguientes reutilizan la sesión oficial de Pi.

[Probar Pi.cmd](Probar%20Pi.cmd) abre un proyecto de pruebas en
`C:\Git\Skynet\proyectos\prueba-pi`. Pi de consola en `C:\Git\PiLocal` sigue separado.
No hace falta abrir LM Studio ni descargar otra copia del modelo.

```powershell
cd C:\Git\Skynet
.\.venv\Scripts\skynet.exe
.\.venv\Scripts\skynet.exe web
.\.venv\Scripts\skynet.exe doctor
```

Comandos: `/repos`, `/repo nombre|ninguno`, `/modelo local|otro`,
`/razonamiento auto|rápido|medio|alto`, `/permisos`, `/internet on|off`, `/privado`,
`/tareas`, `/estado id`, `/log`, `/buscar texto` y `/ayuda`.
No hay un bucle Coder separado ni un scheduler que fuerce una duración mínima.

## Configuración

Las opciones personales se guardan localmente en `data/personalizacion.json`:

- **Harness:** Pi por defecto. Puedes registrar ejecutables compatibles con **Pi RPC y sus
  opciones de arranque**. Otros protocolos necesitan adaptadores; indicar un nombre de agente
  no lo integra automáticamente. Modelo y harness se eligen por separado.
- **Herramientas:** activa o desactiva las cuatro originales. Las llamadas pasan por permisos.
- **Modelo local:** contexto configurable, caché KV (FP16/Q8/Q4), MTP y visión en GPU/CPU. Apaga y
  enciende el motor tras cambiar estas opciones. En este PC Daniel ha elegido Q4 para ambas cachés K/V.
  MTP permanece activado; compara el mismo prompt con MTP activado y desactivado.
- **Otros modelos:** en «Más modelos y harnesses», registra un endpoint compatible con OpenAI:
  `{"otro":{"id":"modelo-servido","api_base":"http://127.0.0.1:1234/v1","privado":true,
  "contexto":16384,"max_tokens":4096,"razonamiento":null}}`.
  `razonamiento:null` sirve para modelos sin razonamiento explícito. Para proveedores externos
  usa `privado:false` y `api_key_env` si necesitan clave; no escribas la clave en el catálogo.
- **Skills:** lista explícita de rutas; Pi las carga con su mecanismo original, sin generar propuestas.

La compactación usa los valores de Pi con 64K. Para ventanas inferiores a 36K ajusta su reserva
proporcionalmente; sigue siendo la compactación de Pi, sin un bucle propio de Skynet.
En este PC, una prueba corta sin cuantización y con MTP activado dio 7,41 tok/s con 64K y 19,93 con 32K.
Después se comparó Q8/Q4 a 64K: medias de generación 14,11 y 44,26 tok/s respectivamente.
Daniel eligió Q4, manteniendo 64K y MTP. Son pruebas cortas de velocidad; no certifican calidad de código.

## MCP opcional

Apagado por defecto. Puedes añadir, eliminar y activar cada servidor `stdio` (ejecutable y argumentos)
o HTTP (URL), y apagar MCP entero. Un servidor apagado no se conecta ni registra herramientas.
Los activos usan el MCP oficial de Pi, con esquemas cargados bajo demanda mediante `tool_search`.

Catálogo inicial: búsqueda en internet, navegador local, visión, herramientas/índice del PC y
agente-godot. **Internet** controla búsqueda y navegador desde el chat. Visión y las demás herramientas
se activan por separado. El navegador comprueba HTML cuando el modelo lo decide; no es un verificador
automático. Mantiene su aislamiento de red: páginas con CDN pueden necesitar dependencias locales
para esa herramienta.

«Configuración avanzada de MCP (JSON)» permite editar `args`, `env`, `headers`, `cwd` y `exposure`.
Los placeholders `{repo}`, `{home}` y `{modo}` se resuelven por petición.
`exposure:deferred` es el valor inicial; también se admite `direct` o `hidden`.

## Memoria individual

Apagada por defecto. Solo se incorpora la memoria aprobada. Cada entrada tiene botones
**Aprobar esta entrada** y **Descartar**; no hay aprobación en lote. Si el modelo pide recordar algo,
se muestra esa entrada y necesita aprobación incluso con «Sin preguntar». Una negativa la deja
pendiente. Las antiguas preferencias se importan pendientes; los borradores no se activan.

Desactivar memoria retira la herramienta y su añadido de instrucciones; no borra mensajes antiguos.
Memoria, skills y extras activos añaden tokens. Apagados no se añaden al prompt, aunque se conserva
el historial previo. Para comparar rendimiento empieza chats nuevos con las mismas opciones.

## Permisos, imágenes y móvil

Modos por modelo: **Solo repo**, **Ver mi PC**, **Ver y editar**, **Control total**. Las llamadas
se revisan antes de ejecutarse. Las acciones que lo requieren piden confirmación y quedan registradas.
Este control **no es un sandbox del sistema operativo** ni garantiza inspeccionar todos los efectos
indirectos de un script ejecutado con bash.

Con un modelo compatible y su `mmproj`, adjunta, pega o arrastra PNG/JPEG/WebP al chat (hasta cuatro,
5 MB por imagen). MCP visión puede leer imágenes y capturar ventanas según permisos. Ayuda en juegos
e interfaces si modelo y herramienta tienen visión activa; no es una garantía de calidad visual.
El proyector en CPU es la opción inicial para dejar margen en los 16 GB de VRAM de este PC;
es configurable y no obligatorio.

`tok/s` muestra cada segundo la generación contada por llama.cpp y cero cuando está inactivo o no
hay un contador compatible. El pie conserva la media histórica de la respuesta. Skynet escucha
solo en `127.0.0.1`; el móvil usa acceso privado por Tailscale y llave del dispositivo. La APK
instalada necesita recompilar para incorporar cambios de interfaz; el backend ya utiliza Pi.
SQLite e historial se conservan sin modificar migraciones publicadas.

## Mantenimiento

| Archivo/carpeta | Uso |
|---|---|
| `config/router.toml` | Modelo local y perfiles base |
| `config/skynet.toml` | Motor local y catálogo inicial MCP |
| `config/repos.toml` | Proyectos autorizados |
| `config/permisos.toml` | Niveles y comandos permitidos |
| `skynet_tools/pi_agent.py` | Adaptador RPC, sin bucle propio |
| `herramientas/pi/puente.ts` | Extensión de permisos y memoria opcional |
| `skynet_tools/personalizacion.py` | Opciones persistentes y aprobación individual |
| `data/pi/sessions` | Sesiones JSONL originales de Pi |
| `data/skynet.db` | Tareas e historial consultable |

`config/*.local.toml`, estado, memoria y credenciales no se versionan. LiteLLM no interviene en
producción: Pi usa su cliente de proveedor. Se conserva en desarrollo para pruebas del ejecutor
histórico. LM Studio es otra capa: instala modelos y backends; Skynet puede arrancar su llama-server.

El ejecutor anterior queda fuera de producción, con fixtures de regresión existentes. Hermes se
retira de configuración, interfaz y adaptadores. Las decisiones antiguas permanecen como historial
en [docs/DECISIONES.md](docs/DECISIONES.md).

Backup **solo local**: rama `SKynet-Old-v0.2`, commit `067ea44`, estado personal en
`data/backups/old-v0.2-20261012`. Rama de trabajo: `codex/pi-motor`. No se publica a GitHub.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\skynet.exe doctor
```

Estado: [PROGRESO.md](PROGRESO.md). Integración: [herramientas/pi/README.md](herramientas/pi/README.md).
