# Decisiones (ADR) del MVP

## D27. Pi oficial como único motor de producción (2026-10-12)
- Daniel autoriza sustituir el bucle propio tras comparar tareas reales, retirar Hermes, caché cuantizada,
  propuestas y verificación impuesta; mantener MTP, opciones configurables y aprobar memoria individual.
  Esta decisión sustituye D26 para la ejecución actual; las anteriores describen versiones históricas.
- Se reutiliza Pi 1.1.0 mediante RPC y extensiones oficiales. Conserva read/bash/edit/write, sus contratos,
  prompt, sesión y compactación. Skynet no construye un bucle de razonamiento ni impone planes, checkpoints
  o un verificador universal. Los límites antiguos quedan fuera de producción; fixtures antiguas los prueban.
- **Contrato caro de cambiar:** motores registrados deben hablar Pi RPC y admitir las opciones de arranque
  del adaptador actual. Otro harness necesita adaptador. Registro persistente separado de modelos; añadir un
  ejecutable desconocido no equivale a integrar su protocolo. No se cambia el esquema SQLite publicado.
- **Autoridad de sesión:** JSONL de Pi con UUID estable por chat/proyecto; SQLite mantiene tareas, consumo y
  auditoría para interfaz. El mensaje se transmite sin reconstruir contexto propio o duplicar historial.
  Se reutilizan ajustes de muestreo/contexto/modelo. Compactación original con 64K, reserva adaptada bajo 36K.
- **Permisos caros de cambiar:** extensión tool_call consulta el gate existente antes de ejecutar originales
  y MCP. Puente loopback efímero con token, rechazo de Origin y límites de tamaño. No es un sandbox del SO;
  el control de bash no inspecciona de forma completa los efectos indirectos de programas. No se promete esa
  protección. Memoria siempre solicita aprobación por entrada incluso con «Sin preguntar».
- **Extras:** configuración explícita de MCP global/por servidor, herramientas nativas, skills y memoria.
  MCP oficial con descubrimiento diferido; apagados no conectan ni registran herramientas. No se descubren
  MCP ni extensiones de otras instalaciones/proyectos. Las instrucciones AGENTS habituales de Pi permanecen.
  Internet controla búsqueda y navegador; privacidad alta evita ambos. Un historial previo puede conservar
  resultados y nombres antiguos aunque un extra esté apagado; no quedan ejecutables ni declaraciones activas.
- **Memoria:** dos entradas antiguas importadas pendientes, sin autoaprobar ni fusionar lotes. Estado JSON
  local y auditado por ID. Solo entradas aprobadas se añaden al prompt si memoria está activa (máximo 4K chars).
  Sin propuestas de skills o memoria por completar tareas. No se publica estado personal ni credenciales.
- **Modelo:** endpoint compatible con OpenAI separado del harness. Caché KV sin cuantización, MTP mantenido,
  contexto configurable y visión CPU/GPU. No se exige Qwen ni 64K. CPU recomendada para margen de VRAM.
  Una medición corta con MTP/FP16 da 7,41 tok/s a 64K y 19,93 a 32K; se restaura 64K y se recomienda comparar.
- **Respaldo y distribución:** backup local `SKynet-Old-v0.2` (`067ea44`) y estado consistente en data/backups.
  Trabajo en `codex/pi-motor`, sin push por decisión expresa de Daniel. Hermes fuera del proyecto activo;
  historial de decisiones y fixtures se conserva. LiteLLM fuera de producción, solo en dependencias dev.

## D15. Búsqueda web opcional y ligera (2026-10-09)
Pedido por Daniel: búsqueda en internet con interruptor en la UI, evitando cargar varios MCP
de navegador. Servidor propio `skynet_tools/internet.py` sobre DDGS 9.x y httpx: dos herramientas,
`internet.buscar` y `internet.leer`, resultados limitados a 5 extractos y 5.000 caracteres por página.
El Core solo lo conecta si `capacidades.internet` está activado; no cambia la selección del modelo.
Apagado al arrancar; al retomar una tarea se respeta el interruptor actual. Funciona sin repo y en
Solo repo: consultar una web no concede acceso a archivos o ejecución de programas.

Política (cara de cambiar): el gate exige habilitación explícita además del nivel READ. Privacidad
alta (incluida la del repo) y tareas largas deshabilitan el MCP. Lectura HTTP/HTTPS pública, sin
credenciales, proxies de entorno, archivos, red local ni puertos internos; cada redirección se valida.
No usa cookies del navegador ni ejecuta JavaScript. El prompt manda comprobar datos desconocidos,
citar fuentes e ignorar instrucciones externas. Estas instrucciones no hacen infalible al modelo.

Contrato MCP (ampliación, nombres a mantener): `internet.buscar(query)` y `internet.leer(url)`.
Sin migraciones SQLite: el interruptor de la tarea se guarda en el JSON de capacidades existente.
Barato de cambiar: proveedor de búsqueda o extracción. DDGS no necesita claves, pero depende de
buscadores públicos y sus límites. No se promete latencia cero: apagado no añade proceso ni esquemas;
activado añade dos esquemas pequeños, arranque MCP y las llamadas de red solo cuando se usan.

Cada decisión indica si es **cara de cambiar** (afecta a datos guardados o a contratos) o barata.

## D1. Python para el Core — cara
Python 3.14 en `.venv`. El SDK oficial de MCP y LiteLLM son Python. Aprobado por defecto
el 2026-10-07 (Daniel no contestó; el coordinador eligió el valor recomendado del diseño).

## D2. Herramientas = servidores MCP — cara
El Core solo habla MCP (`skynet/toolhub.py`). Las herramientas propias están en
`skynet_tools/` como servidores MCP independientes que se lanzan por stdio:
- `workspace`: archivos, búsqueda, git y comandos dentro de un único repo.
- `coding_agent`: envuelve agente-godot (noche.ps1) sin modificarlo.

Desviación del diseño: la carpeta se llama `skynet_tools/` y no `mcp/`, porque una carpeta
`mcp` en la raíz taparía el paquete `mcp` del SDK al ejecutar desde `C:\Skynet`.

SDK MCP 2.x: `FastMCP` pasó a llamarse `MCPServer` (`mcp.server.mcpserver`). El cliente usa
`ClientSession` + `stdio_client` (con el stderr de cada servidor a `data/logs/mcp-<nombre>.log`).

Añadir una herramienta: escribir un servidor MCP (propio o de terceros), declararlo en
`config/skynet.toml` bajo `[mcp.<nombre>]`, darle nivel a sus herramientas en
`config/permisos.toml` y añadir su nombre a `herramientas` del repo en `config/repos.toml`.

## D3. LiteLLM como librería — barata
`skynet/router.py` llama `litellm.acompletion`. Coste: si el perfil del modelo trae precios
en `router.toml` se usan esos; si no, `litellm.completion_cost`. LiteLLM da USD; se pasa a €
con `moneda_usd_eur`.

Modelo cloud por defecto: `anthropic/claude-opus-5-5` (4 $ / 20 $ por millón de tokens),
**desactivado** hasta que haya `ANTHROPIC_API_KEY` y `presupuesto.mensual_eur > 0`.

## D4. Esquema SQLite — cara
Tablas `tasks`, `steps`, `events` del diseño, versión 1 (`PRAGMA user_version`). Columnas
añadidas al diseño para no tener que migrar pronto:
- `tasks.capabilities_json` (capacidades pedidas al router y permisos preaprobados),
  `result_summary`, `pid` y `heartbeat_at` (para saber si un runner sigue vivo).
- `steps.status` (`completado`, `ok`, `avance`, `revertida`, `sin_cambios`, `interrumpido`...).

Cambios futuros: añadir una entrada a `MIGRATIONS` en `skynet/store.py`; nunca editar la v1.

## D5. agente-godot como proceso externo — barata
`coding_agent.start_task(repo, horas)` lanza `sistema\noche.ps1 -Juego <repo> -Horas <h>` y
el Scheduler lo vigila sin LLM. El trabajo lo define el `PLAN.md` del juego, como siempre.
Para usarlo: añadir el juego a `repos.toml` con `agente = "agente-godot"` y
`herramientas = ["coding_agent"]`, y lanzar `/largo <horas> <objetivo>` desde el chat.
No se ha tocado nada de agente-godot.

## D6. Chat en terminal — barata
`skynet` abre el chat. Cada mensaje es una tarea nueva; «continúa» retoma la última sin
terminar. Las tareas de chat no hacen commit: dejan los cambios para que los revises
(el verificador sí se ejecuta y decide si la tarea queda `hecha` o `fallida`).

## D7. Permisos — cara (es la política de seguridad)
- Niveles por herramienta en `config/permisos.toml`; herramienta desconocida = PRIVILEGED.
- Cualquier argumento de ruta debe caer dentro del repo autorizado y fuera de `.git`
  (lo comprueban el gate y, otra vez, el propio servidor).
- EXECUTE: lista blanca por prefijo de palabras; un comando con `& | ; > < ` % $(` siempre pregunta.
- Respuestas: `s`, `n` o `t` (sí para esa herramienta el resto de la tarea; nunca para DESTRUCTIVE).
- Sin humano (tareas largas) «preguntar» = denegar. Al lanzar `/largo` se preaprueban solo las
  herramientas que necesita el runner de agente-godot (`coding_agent.start_task/stop_task`).

## D8. Aceptación de iteraciones en tareas largas — barata
Una iteración se **acepta** (commit) si el verificador pasa o si no empeora respecto a la
última aceptada: mismos o más tests en verde y mismos o menos fallos (cuentas sacadas de la
salida de pytest/jest/unittest). Si empeora, `git reset --hard` + `git clean` al checkpoint y
el fallo se anota en `.skynet/tarea-N/ERRORES.md`. La tarea solo es `hecha` si el verificador
está en verde **y** el agente escribe `OBJETIVO_CUMPLIDO`. Se para con: límite de horas o de
iteraciones, el mismo fallo N veces seguidas, N iteraciones sin cambios, o `/parar`.

## D9. Interfaz web local — barata
`skynet web` sirve una página en `127.0.0.1:8765` con el **mismo** Coordinator que el chat de
terminal (`skynet/web/server.py`): la web es otra UI del Protocol `UI`, no un segundo camino de
ejecución. Lo único que cambia es cómo pregunta (`WebCoordinator._make_asker` manda los datos del
permiso estructurados para el diálogo).
- **HTTP + Server-Sent Events** en vez de WebSocket: Starlette y uvicorn ya llegan con el SDK de
  MCP y uvicorn no trae WebSocket sin instalar algo más. Cero dependencias nuevas.
- **Seguridad:** solo `127.0.0.1`; se comprueba `Host` (contra DNS rebinding) y `Origin` + JSON
  en los POST (contra CSRF desde otra web abierta). El Markdown de las respuestas se escapa
  siempre (un texto malicioso en un repo no puede ejecutar código en la página).
- **Una tarea a la vez**, como en la terminal; «Detener» cancela el paso (queda `pausada`).
- **3D:** Three.js r180 en WebGL2, vendorizado (sin CDN ni Node). La nebulosa se simula en la
  GPU (GPUComputationRenderer: muelle hacia la forma de reposo + curl noise + fuerzas del cursor).
  WebGPU descartado por ahora: aún falla en algunos drivers. Si más adelante se pasa a
  Unreal/Unity, la API HTTP + SSE les sirve igual.
- Cambios en el Core: el verificador del chat corre en un hilo (no congela la web),
  `Coordinator.resume` acepta una tarea concreta y `cli.doctor_checks()` devuelve los checks
  estructurados (`skynet doctor` imprime lo mismo que antes).

## D10. Búsqueda en el historial y skills de solo lectura — barata (salvo el índice: v2 del esquema)
Fase 1 de la propuesta de automejora. Sin dependencias nuevas.
- **Búsqueda:** migración v2 de `skynet/store.py`, aditiva: tabla virtual FTS5 `historial_fts`
  (tokenizer `unicode61 remove_diacritics 2`: «accion» encuentra «acción») sobre
  `steps.input_summary/output_summary` y `events.tool/detail_json`, mantenida con triggers y
  rellenada con lo que ya había. `rowid` = 2·id en pasos y 2·id+1 en eventos, así los triggers
  borran por rowid sin columnas extra. Si el SQLite no trae FTS5, la migración no crea nada y
  `Store.search` usa LIKE. Las palabras del usuario van entre comillas: nunca se interpretan
  como sintaxis FTS. `MIGRATIONS` admite ahora funciones además de SQL (los triggers llevan `;`).
  `/buscar <texto>` devuelve los 10 más relevantes.
- **Skills:** `skills/<nombre>/SKILL.md` con el formato de agentskills.io (estándar abierto que
  ya usan otros agentes: una skill escrita para ellos sirve aquí). Frontmatter leído con un
  parser mínimo (sin PyYAML). Divulgación progresiva: el Context builder solo añade nombre +
  descripción (tope 2.000 caracteres, prioridad baja); el cuerpo (tope 12.000) entra con
  `/skill <nombre> <tarea>`, que guarda el nombre en `tasks.capabilities_json` para que
  «continúa» lo vuelva a cargar. Se leen del disco en cada paso. Skynet no escribe skills en
  esta fase: crearlas o mejorarlas sola sería la fase 2 y necesita OK.

## D11. Propuestas de skill y memoria curada — cara en dos puntos (esquema v3 y política de permisos)
Fase 2 de la propuesta de automejora. Sin dependencias nuevas (`skynet/propuestas.py`).
- **Cuándo:** al cerrar una tarea con el verificador en verde y 3 o más pasos (chat o tarea
  larga). El modelo que el router elige para la tarea redacta, sin herramientas y con contexto
  mínimo (objetivo, resumen de los últimos 8 pasos, verificador), una skill candidata y hasta 3
  hechos para la memoria. Si falla, se anota un evento `error` y la tarea no se ve afectada.
- **Dónde:** `skills/_propuestas/<nombre>/SKILL.md` + `ORIGEN.md` (de qué tarea sale, fecha y
  modelo) y `skills/_propuestas/memoria.md`. Solo texto: Skynet escribe únicamente esos archivos.
  Un nombre ya usado recibe sufijo (`-2`); nunca se pisa nada. Carpeta ignorada por git.
- **Memoria curada:** `memoria/MEMORY.md` (hechos del entorno) y `memoria/USER.md`
  (preferencias), con tope de 2.048 bytes cada una. Entran siempre en el contexto (prioridad
  alta). Aprobar un añadido que pase del tope se rechaza entero: hay que recortar a mano.
- **Revisión:** `/propuestas`, `/aprobar <nombre>` y `/rechazar <nombre>` (`memoria` = los
  añadidos de memoria). Aprobar pasa por el gate como `skynet.aprobar` = PRIVILEGED (pregunta
  siempre y queda en el audit log como `permission` + `propuesta`). Los nombres se validan
  (sin `../`). **Política nueva del gate:** cualquier herramienta que no sea de lectura y apunte
  a `skills/` o `memoria/` de Skynet se deniega, aunque C:\Skynet sea un repo autorizado.
- **skill_uses (migración v3, aditiva):** una fila por tarea lanzada con `/skill` (versión =
  8 primeros caracteres del SHA-1 de SKILL.md); el resultado del verificador se actualiza al
  cerrar cada paso de la tarea. `/skills` muestra usos y tasa de verificador OK (solo cuentan
  los usos que llegaron a pasar por el verificador). Los parches automáticos son la fase 3.
- **Web:** `/api/estado` devuelve `propuestas` (número pendiente) y la cabecera muestra un botón
  «Propuestas N» que lanza `/propuestas`; aprobar y rechazar se escriben en el chat.

## D12. Modelo local único: Qwen3.8-27B UD-IQ3_XXS en llama-server (2026-10-08)
Aprobado por Daniel tras el benchmark de `bench/resultados.md` (A 27B Q4_K_M, B Strata,
C 27B IQ3_XXS, D 35B-A3B). C ganó: ~45 tok/s de generación, ~710 tok/s de prefill, 100 % en las
10 tareas, cabe entero en los 16 GB. El Q4_K_M no cabe (9–12 tok/s) y Strata sacó 90 % y tarda
~80 s en arrancar. Por decisión de Daniel, Strata y el Q4_K_M salen de las opciones de Skynet
(los archivos y C:\Strata no se tocan).
- **Motor `llamacpp`** (`skynet/engines.py`): lanza el `llama-server.exe` Vulkan que trae LM Studio
  con los flags de `[motores.local]` (FA on, KV q8_0, 32K, `--spec-type draft-mtp`), porque
  `lms load` no expone FA ni el tipo de KV. Puerto 8090, alias `local`; se apaga matando el
  llama-server de ese puerto. Log en `data/logs/local.log`.
- **Cara de cambiar:** poco. El perfil sigue llamándose `local` (router, reglas y tests igual);
  volver a LM Studio es cambiar `[motores.local]` a `tipo = "lmstudio"` y el perfil del router.
  La ruta del runtime (`vulkan-avx2-2.54.0`) se rompe si LM Studio borra esa versión.

## D13. OmniRoute como pasarela cloud opcional (2026-10-08)
Pedido por Daniel. OmniRoute (npm `omniroute`, fijado a 3.8.51, MIT) instalado en local en
`vendor/omniroute` (ignorado por git), sin `-g`. npm 11 no ejecutó sus scripts de instalación y
funciona igual.
- **Motor `proceso`** (`skynet/engines.py`), genérico: ejecutable + args + env, `salud` (URL que
  dice `{"status": "ok"}`) y `firma` para apagarlo (mata los procesos cuya línea de comandos la
  lleva). `gpu = false`: convive con el motor local en vez de apagarlo. llama-server comparte el
  lanzador (`_spawn`); su log pasa a `data/logs/<motor>.log`.
- **Seguro por configuración** (`[motores.omniroute].env`): escucha solo en 127.0.0.1 (por
  defecto Next escucharía en 0.0.0.0), datos y claves cifradas en `data/omniroute`, sin TLS
  fingerprint, `OPENCODE_SYNTHESIZE_CLI_HEADERS=false` y `OPENCODE_FREE_TIER_REQUEST_CONTRACT=off`
  (por defecto OmniRoute se hace pasar por el CLI de OpenCode para usar su free tier, que según
  OpenCode solo vale desde OpenCode). Contraseña del panel en `data/omniroute/dashboard-password.txt`.
- **Proveedores:** ninguno de momento. OpenCode Free queda fuera (403: "solo desde OpenCode").
  No se copió ninguna clave existente (Gemini) a OmniRoute sin preguntar.
- **Perfil `omniroute`** (router.toml): `openai/skynet`, es decir, un combo "skynet" que hay que
  crear con los proveedores aprobados; se evita `auto` porque trae OpenCode precableado. No
  privado: con privacidad alta el router usa siempre `local`. No está en ninguna regla, solo se
  usa si se elige en Ajustes. Coste 0: si se le meten claves de pago, Skynet no contará ese gasto.
- **Cara de cambiar:** poco; quitar el motor y el perfil lo deja como estaba.

## D14. Modos de permisos por modelo y nube con confirmación (2026-10-08)
- **Cuatro modos por modelo** (`skynet/modos.py`, guardados en `data/permisos_modelos.json`):
  Solo repo (por defecto), Ver mi PC (leer todo el PC), Ver y editar (además escribir en la
  carpeta de usuario) y Control total (además ejecutar PowerShell y abrir programas o enlaces,
  p. ej. `steam://install/<AppID>`). Se cambian en Ajustes, junto al cuadro de texto o con `/permisos`.
- **Siempre se pregunta**, en cualquier modo y sin «sí a toda la tarea»: administrador
  (runas, sudo, HKLM, servicios, apagar...), carpetas del sistema (Windows, Program Files,
  ProgramData), la carpeta de Skynet, borrar (delete_file, rm/del/Remove-Item) y secretos
  (.ssh, .env, Login Data, cookies, *.pem, data/omniroute...).
- **Herramienta nueva `sistema`** (`skynet_tools/sistema.py`): solo se arranca si el modelo del
  paso tiene un modo distinto de Solo repo; el gate (no el servidor) decide qué se permite.
  En Control total también se relaja la lista blanca de comandos del repo (salvo lo de arriba).
- **Tareas largas: siempre Solo repo** (nadie delante para confirmar).
- **Nube desactivada por defecto:** el modelo seleccionado al arrancar es `local` y los perfiles
  no privados no se usan hasta activarlos con confirmación (Ajustes, `/modelo`, `/nube`). La
  activación dura lo que la sesión de Skynet; el router cae al local si no lo están. Un modo
  fuerte (Ver y editar, Control total) en un modelo en la nube muestra un aviso antes.
- **Cara de cambiar:** poco. Lo caro es la política: qué cuenta como «siempre se pregunta»
  (patrones en `gate.py`). Son listas negras: útiles para avisar, no una barrera infalible.

## D15. Acceso desde el móvil por Tailscale y llave por dispositivo (2026-10-08)
- **Camino privado con Tailscale Serve**, no puertos abiertos ni túnel público: la web sigue escuchando solo
  en 127.0.0.1 y `tailscale serve --bg 8765` la publica solo dentro de la red de Tailscale (HTTPS válido).
- **Llave por dispositivo** encima de Tailscale: se empareja con un QR del PC (código de 10 min y un uso) que el
  móvil cambia por una llave propia; se guarda solo su hash (`data/dispositivos.json`); se quita una a una.
- Remoto exige IP de Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48), Host `*.ts.net`, origen de la app y llave.
  Funnel (internet público) se rechaza siempre. Desde el móvil no se añaden repos, no se activa «Sin preguntar»
  ni se gestionan dispositivos. Emparejados, mensajes, permisos respondidos y rechazos van al registro.
- **Cara de cambiar:** poco. Si un día se quiere sin Tailscale (p. ej. Cloudflare Access), basta con otra
  comprobación de origen en `Acceso` (web/server.py); las llaves por dispositivo siguen valiendo.

## D16. Bucle pensado para el modelo local (2026-10-09)
- **Ventana de contexto** (`ventana.py`, sin LLM): pasada la mitad del contexto del modelo, las salidas de
  herramientas antiguas (todas menos las 3 últimas) se quedan en una línea; si aún no cabe, los turnos del medio
  se cambian por un resumen (herramientas usadas + primera línea del resultado). Objetivo, contexto inicial y
  últimos 4 turnos no se tocan. `max_tokens` se ajusta para que prompt + salida nunca pasen del contexto.
  El contexto de cada perfil sale de `contexto_tokens` en router.toml o del `contexto` de su motor (32K local).
- **Llamadas rotas** (`llamadas.py`): JSON con comas finales, comillas simples, ```json o cortado se repara;
  una llamada escrita como texto (`<tool_call>` de Qwen) se ejecuta igual. Si `json-repair` está instalado se usa.
- **Herramientas por modo**: «Ver mi PC» solo ve leer/listar de `sistema`, «Ver y editar» además escribir;
  ejecutar, abrir e instalar solo en «Control total». Antes las veía todas y el gate las denegaba.
- **Muestreo por perfil** (`temperatura`, `top_p`, `top_k`, `min_p`, `presence_penalty`): el local usa los de Qwen
  para pensar/programar (0.6 / 0.95 / 20 / 0) en vez de la temperatura 0.8 de llama-server.
- **Cara de cambiar:** qué se conserva al resumir (decide qué recuerda en tareas largas). Umbrales en `ventana.py`.

## D17. Conversación primero; Coder como interruptor (2026-10-09)
- Pedido por Daniel tras comparar con OpenClaw: un «hola» con repo elegido recibía ~3.000 tokens (informe del
  repo + 15 herramientas), razonaba en «medio» y arrancaba 2 servidores MCP; contestaba sobre el repo.
- **Por defecto, cada mensaje es un turno de conversación**: el mensaje tal cual, el historial de la sesión como
  turnos user/assistant de verdad (antes, 3 pares recortados dentro del mensaje), memoria y skills en el system
  prompt, sin herramientas de repo, sin verificador ni commits. Razonamiento Auto = bajo. Internet y los modos
  de permisos siguen añadiendo sus herramientas como antes.
- **Coder** (interruptor, apagado al arrancar; `/coder on|off`, `POST /api/ajustes {coder}`, `snapshot.coder`):
  el comportamiento anterior sobre el repo elegido (contexto del repo, workspace, verificador, commits,
  propuestas). Necesita repo; quitar el repo lo apaga. Retomar una tarea de código lo activa.
- Medido en la nube con LLM guionizado: «hola» ≈ 125 tokens en «Solo repo» y ≈ 750 en «Ver y editar» (5
  herramientas de `sistema`), frente a ~3.000.
- Pendiente: mantener vivos los servidores MCP durante la sesión (hoy ~1,2 s por mensaje con `sistema`).
- **Cara de cambiar:** poco; la tarea en SQLite se sigue creando (registro y consumo) aunque sea conversación.

## D18. Instalar juegos de Steam sin pulsar nada (2026-10-09)
- Daniel: al pedir instalar un juego, Steam se abría con el diálogo «Instalar» esperando un clic.
- `sistema.instalar_steam` (EXECUTE, solo en «Control total»; con «Sin preguntar» no pregunta) ahora escribe
  `steamapps/appmanifest_<AppID>.acf` con StateFlags 1026 en la biblioteca principal y reinicia Steam
  (`steam.exe -shutdown` y `-silent`), que al leerlo descarga el juego. Comprueba que empieza (manifiesto
  actualizado o carpeta `downloading/<AppID>`). Lógica en `skynet_tools/steam.py`.
- No reinicia Steam si hay un juego abierto (RunningAppID): deja el juego en cola para el próximo arranque.
- Si no empieza (p. ej. juego gratis sin licencia en la cuenta), borra el manifiesto y usa el plan B de
  antes: `steam://install` + Intro en el diálogo. Descartado steamcmd: pide usuario, contraseña y Steam Guard.
- Sin probar aún en Windows real; tests con una biblioteca de Steam simulada.

## D19. Dos cerebros: el bucle de Skynet y Hermes Agent (2026-10-10)
- Tras la comparativa (docs/COMPARATIVA-HERMES.md): con el modelo local el bucle de Skynet empata en calidad y
  es ~6-7 veces más rápido; Hermes aprende (memoria y skills) y trae herramientas que Skynet no tiene. Daniel
  elige la opción A: Skynet sigue siendo el cerebro por defecto y Hermes un cerebro elegible.
- **Hermes es la única vía a modelos en línea.** Fuera de la config Gemini, OmniRoute y Anthropic directo
  (perfiles, regla de razonamiento alto y motor). Quedan `local` (igual que antes), `hermes` (Hermes con el modelo
  local, privado) y `hermes-nube` (Hermes con el proveedor de [motores.hermes].env; no privado: se activa con
  confirmación). Un solo Hermes con dos alias de modelo (`model_routes`): misma memoria y skills.
- **Perfil `agente = true`:** Skynet le pasa la conversación (historial como turnos) sin herramientas, sin su
  prompt y sin gate; Hermes usa las suyas. Coder y `/largo` van siempre con el bucle de Skynet (el router cae a
  `local`). `motor` enlaza un perfil con su motor; `api_key_archivo` lee la clave que crea el motor.
- **Motor `hermes`** (tipo proceso + nuevo campo `parar`; `{python}` en la config): `skynet_tools/hermes_motor.py`
  arranca la imagen `skynet/hermes` (contenedor `skynet-hermes`, solo 127.0.0.1:8642) y mezcla en su config.yaml
  solo nuestras claves (modelo, rutas, terminal, aprobaciones). Datos de Hermes en `%USERPROFILE%\.hermes-skynet`.
- **Política (cara de cambiar):** por decisión de Daniel, Hermes ve toda su carpeta de usuario y C:\Git y ejecuta
  sin preguntar dentro del contenedor. Se tapan con carpetas vacías AppData, .ssh, credenciales de nube y Docker,
  .gnupg y los datos de Hermes (una web podría inyectarle órdenes de leerlos). Los permisos de Skynet (modos,
  gate) no se aplican a lo que haga Hermes: la barrera es el contenedor.
- **Cara de cambiar:** el campo `agente` del perfil (contrato con el router y la web) y la política de carpetas.
  Barato: imagen, puerto y alias.

## D20. Memoria que escribe el modelo, al estilo Hermes (2026-10-10)
- La comparativa mostró que Skynet no recordaba nada entre sesiones (la memoria solo cambiaba con /aprobar tras
  tareas verificadas largas). Ahora el modelo tiene la herramienta `memoria` (guardar, reemplazar, quitar) sobre
  `memoria/USER.md` (preferencias) y `memoria/MEMORY.md` (entorno), que ya entran siempre en el contexto.
- **Sin preguntar, como Hermes**; cada cambio queda en el registro (evento `memoria`). Tope de 2 KB por archivo
  (al llenarse, el modelo debe fusionar o quitar), rechaza lo que parece un secreto y solo toca líneas «- texto»
  (lo escrito a mano se conserva). No se ofrece en tareas largas (nadie delante: riesgo de recuerdos inyectados
  por un repo o una web) ni a agentes externos. /propuestas y /aprobar siguen igual.
- **Desviación de D2:** es una herramienta interna del Core, no un servidor MCP: escribe el estado del propio
  Skynet (como propuestas.py) y un servidor MCP añadiría ~1 s de arranque a cada mensaje del chat.
- **Cara de cambiar:** que escriba sin preguntar (política). Barato: tope, nombres de archivo y prompt.
- Ese mismo día: motor local por defecto Qwen3.8-27B GSQ-RCO IQ3_S con MTP a 64K y caché q4 (lo mínimo que pide
  Hermes; mismos aciertos y más rápido en la comparativa) y fuera del código el motor Strata y
  `razonamiento_por_tokens` (solo lo usaba Strata).

## D21. Todo hablando, Control total sin preguntas de más e interfaz simplificada (2026-10-10)
Pedido por Daniel: que lo que le pide a Claude lo pueda pedir igual a Skynet, sin comandos ni permisos molestos.
- **Herramientas internas** (`skynet/internas.py`, como la memoria de D20): `crear_proyecto` (carpeta junto a
  Skynet o en `[general] proyectos`, git, test mínimo y repo autorizado), `tarea_larga` (en **minutos**, sobre un
  repo con verificador; sustituye a `/largo` y a su pestaña) y `ver_skill` (el modelo carga la skill que encaja;
  `/skill` queda como atajo). Las dos primeras piden confirmación con el diálogo de siempre.
- **Instrucciones:** `memoria/SKYNET.md` (las escribe Daniel, como un CLAUDE.md personal) va siempre en el
  contexto; en Coder se añade el `AGENTS.md` o `CLAUDE.md` del repo (tope de 4.000 caracteres cada uno).
- **PC:** `sistema.buscar_archivo` sobre un índice de nombres de `C:` (`skynet_tools/indice.py`, SQLite FTS5 con
  trigramas en data/indice.db; con Program Files, sin Windows, ProgramData, AppData ni ruido de SDKs; ~1 M de
  archivos en ~10 s, búsquedas de 1 ms; se rehace aparte si tiene más de 12 h). `sistema.desinstalar_steam`
  (cierra Steam, quita manifiesto y carpeta dentro de su biblioteca, vuelve a abrirlo; nunca con un juego abierto).
  Para programas, el prompt de Control total indica `winget`.
- **Política (cara de cambiar):** en Control total ya no se pregunta por mirar las carpetas del sistema (antes, cualquier
  comando que nombrara Program Files preguntaba, p. ej. al buscar Steam); se pregunta si el comando las **cambia**
  (`_MODIFY_RE` en gate.py), además de administrador, borrar y secretos. En Control total también se escribe fuera de la
  carpeta de usuario sin preguntar (salvo sistema y Skynet). `desinstalar_steam` es EXECUTE (reversible: se vuelve
  a descargar). El diálogo de permisos muestra el comando entero (`comando_completo`).
- **Sin modo automático de modelos:** fuera la opción «Automático», `/modelo auto` y las reglas de router.toml; el
  modelo es el que eliges (local por defecto). Se mantiene «Auto» en el nivel de razonamiento.
- **Interfaz:** barra lateral con Uso (antes Registro) y Estado (antes Diagnóstico); fuera Tareas, Tarea larga,
  «Qué puede hacer» y el botón de acciones de arriba (Ctrl+K sigue). Pie de cada respuesta: tokens, tokens/s y estado,
  con **Reintentar** si falla o queda a medias (evento `fin`; retoma la misma tarea). Cursores nuevos (flecha de
  navegación; la de enlaces en azul de acento). Arreglado el salto de scroll en Configuración: al redibujar se
  cerraba «Avanzado».

## D22. Visión local, adjuntos y capturas puntuales (2026-10-10)
Pedido por Daniel al continuar el plan de Claude: activar visión, adjuntar/pegar imágenes y mirar capturas;
evaluar después la comprobación autónoma de juegos y tareas visuales.
- **Modelo:** mismo GSQ-RCO IQ3_S con MTP y 64K. Descargado `mmproj-Qwen3.8-27B-BF16.gguf` del
  [repositorio GSQ-RCO](https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF/tree/main): 931.146.528 bytes,
  SHA256 `13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16`. El de lmstudio-community
  tiene otra huella y tamaño; se conserva y no se asume intercambiable. `/props` confirma `vision=true`.
- **Memoria/rendimiento:** visión en GPU + 64K cargó, pero la memoria gráfica total observada de Windows fue
  ~16,4 GB dedicada y ~1,6 GB compartida (no son solo el modelo). Dos respuestas de 128 tokens generaron
  ~13 tok/s. Con el proyector en CPU: ~23–33 tok/s en esas respuestas y 6,28 s para la petición completa de
  una imagen nueva de 800×500 con 428 tokens de entrada; GPU dio 3,74 s en la primera prueba sin caché.
  No son un benchmark exhaustivo ni tiempos universales. `vision_gpu = false` conserva el modelo y el
  contexto; se aplica también al elegir otro modelo en Ajustes. Proyector en RAM, modelo de texto en GPU.
- **Transporte:** OpenAI/LiteLLM multimodal; `ToolHub` conserva `ImageContent` MCP y el agente coloca las
  imágenes en un mensaje de usuario después de todos los resultados de herramientas. Base64 nunca se recorta
  como texto ni se audita. Ventana estima tokens de imagen, con límite del motor de 1024 tokens por imagen.
- **Adjuntos:** hasta 4 PNG/JPEG/WebP y 5 MB por archivo; servidor valida píxeles, limita a 20 MP de entrada y
  1280 px de salida, convierte a JPEG sin metadatos. Archivos en `data/imagenes/<sha256>.jpg`. Historial y
  capabilities guardan referencias en sus JSON existentes: **sin migración SQLite**. Mismo acceso
  Host/Origin/Tailscale/llave en la lectura de imágenes; el móvil las pide con Authorization, fuera de /static.
- **MCP y política (cara de cambiar):** `skynet_tools/vision.py`, declarado en config. `leer_imagen(path)`
  queda en el repo en Solo repo; fuera sigue las reglas de lectura/secretos del gate. `capturar_pantalla`
  requiere Ver mi PC o superior, solo con el bucle local; ventana activa por defecto, título opcional para
  seleccionar una ventana sin cambiar el foco, escritorio completo con `ventana=false`. Como las demás
  lecturas del PC, no vuelve a preguntar. Las tareas largas mantienen Solo repo y no capturan el escritorio.
  Las capturas no se guardan automáticamente; los adjuntos sí, hasta que se eliminen sus archivos locales.
- **Revisión autónoma:** se ofrecen herramientas en Coder y peticiones visuales, no en saludos. El prompt pide
  inspeccionar después de cambios relevantes y al terminar, junto con tests y registros. Máximo 6 capturas
  con los mismos argumentos por paso. No es grabación ni un criterio automático de aprobación: una imagen
  no verifica jugabilidad ni garantiza que el modelo detecte todos los fallos. Abrir el juego necesita los
  permisos de ejecución correspondientes. Capturar una ventana minimizada o protegida puede fallar.
- **Fuera de alcance:** Hermes/Nube con adjuntos, permitir capturas de escritorio en tareas largas, controles
  de entrada para jugar automáticamente y cambios a agente-godot. Móvil actualizado en `movil/www`; APK pendiente.

## D23. Peticiones grandes mediante pequeñas ediciones y recuperación (2026-10-11)
- Daniel pide enviar un objetivo complejo completo y que Skynet avance por partes. El simulador agotaba
  los 8.192 tokens intentando escribir un HTML entero; sus argumentos incompletos quedaban en el historial
  y la recuperación terminaba en HTTP 500, incluso con Coder activado.
- **Antes de ejecutar o guardar en el historial:** descartar respuestas con `finish_reason=length`, validar
  todo el lote de llamadas y normalizar JSON reparable. Si el motor rechaza los argumentos antes de entregar
  una respuesta, tratar ese error concreto de formato como recuperable. Tres fallos consecutivos detienen
  el paso, conservando los cambios previos; no se completan cadenas de código truncadas artificialmente.
  Los cortes de conexión durante la respuesta siguen esa misma recuperación acotada; Detener no se reintenta.
- **Construcción:** esqueleto ejecutable y pequeñas sustituciones con workspace.edit_file; instrucciones
  de unos 4.000 caracteres de código por llamada. Plan en `.skynet/tarea-N/PLAN.md`, leído al reanudar; casillas
  pendientes impiden aceptar una respuesta final sin continuar. Es un plan del modelo, no una prueba de calidad.
  Tras varias lecturas seguidas sin editar ni comprobar, recuerda realizar un cambio concreto. No bloquea
  la inspección necesaria: evita consumir todo el paso recorriendo repetidamente un archivo largo.
  La detección de llamadas repetidas distingue versiones del repo: una edición permite releer y ejecutar
  otra vez el mismo verificador. Sin cambios conserva el límite de repeticiones; no cambia los permisos.
- **Continuación en Coder:** cada paso se persiste con las tablas existentes. Si agota sus turnos y ha escrito
  archivos fuera del estado `.skynet/`, hasta cuatro bloques más con contexto fresco y el mismo objetivo.
  Un verificador fallido devuelve el error al agente para hasta dos reparaciones; si no vuelve a editar,
  se detiene. Detener conserva su efecto y los cambios. Tokens y tiempo se suman entre los bloques.
- **Verificación:** también en repos sin Git cuando hubo escritura. Para HTML/JS se pide comprobar ejecución,
  interacciones y aspecto; el verificador debe medir la aplicación y no un test vacío.
- **Cara de cambiar:** ninguna migración SQLite. Límites
  `max_continuaciones` y `reparaciones_verificador` en `[agente]`; misma ruta de planes y estado de tareas.
- **Comprobación de webs:** nuevo MCP `navegador.comprobar_html`, permiso READ. Chrome efímero, sin red,
  WebSocket, WebRTC ni archivos fuera del repo. Hasta ocho clics/entradas y captura opcional por llamada.
  Se ofrece para objetivos HTML/web; requiere Node, Playwright y Chrome (en este PC están disponibles).
  Devuelve errores de ejecución, controles, desbordamiento y, con visión, imagen; no certifica lógica.
  Identifica elementos que exceden el ancho (excluye contenido recortado intencionadamente). Las capturas
  se envían al modelo aunque la comprobación encuentre errores: también sirven para diagnosticar el fallo.

## D24. Tokens por segundo en vivo (2026-10-11)
- El medidor del chat usa diferencias de `n_decoded` en `/slots` del motor llama.cpp seleccionado,
  con muestras cada segundo. Incluye razonamiento y argumentos generados; no estima tokens por caracteres
  ni conserva la media de la última respuesta. La lectura del prompt muestra cero tokens de generación.
- Sin generación, al perder conexión o sin contador compatible muestra cero. También observa las tareas
  largas del motor seleccionado: terminar el mensaje de lanzamiento no deja oculto su trabajo en segundo plano.
  Un endpoint no disponible nunca sustituye el dato con una velocidad inventada. El pie de una respuesta
  conserva su media histórica. Eventos efímeros: no se escriben cada segundo en SQLite.
- Web y fuentes del móvil sincronizadas; la APK instalada requiere recompilar para incorporar el cambio.

## D25. Duración mínima solo a petición explícita (2026-10-11)
- Daniel pide una prueba real de al menos una hora con un único objetivo, sin esperas vacías. Las tareas
  largas aceptan `minutos_minimos` opcional, validado contra el máximo. En capabilities JSON existentes
  se guardan `min_trabajo_seg` y `trabajo_seg`; no cambia SQLite ni se añade un permiso.
- Se acumula el tiempo del modelo y verificación por paso, incluso de intentos fallidos. No cuentan
  pausas entre pasos ni tiempo con la tarea parada. Completar exige además alcanzar el mínimo; los límites
  de errores, falta de avance, máximo y Detener siguen vigentes. No se falsea una hora mediante sleep.
- En tareas largas una fase puede acabar con pendientes en PLAN.md: el scheduler controla el objetivo
  completo y su verificador. La protección contra cierres con plan incompleto sigue activa en Coder normal.
  Configuración de tarea larga: 40 turnos por iteración, porque 20 consumían el bloque en releer/diagnosticar
  antes de poder aplicar varias correcciones. El contexto se recorta y los demás límites permanecen.

## D26. Pi oficial como alternativa al bucle Coder (2026-10-11)
- Daniel autoriza preparar Pi y el modelo local para probarlo dentro del proyecto. Se instala la versión
  1.1.0 de `@earendil-works/pi-coding-agent` en `herramientas/pi`, con lockfile y sin instalación global.
  [RPC](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/rpc.md) y
  [extensiones](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/extensions.md)
  oficiales; no se copia su bucle ni se añade un segundo agente dentro de Agent.run.
- Adaptador en `skynet_tools/pi_agent.py`, extensión en `herramientas/pi/puente.ts`. Pi decide y llama
  al endpoint local directamente; el adaptador reutiliza la ejecución MCP, gate, auditoría y verificador.
  Los comandos y herramientas de archivo incorporados en Pi se desactivan. La extensión recibe únicamente
  las herramientas que Skynet ofrece para esa tarea. Sin descubrimiento de proveedores, claves, extensiones,
  MCP o instrucciones externas del usuario; Skynet aporta contexto, memoria y skills existentes.
- **Contrato y permisos (caros de cambiar):** puente HTTP efímero ligado a 127.0.0.1, token aleatorio por
  ejecución y rechazo de Origin. Manifest y ejecución llevan autenticación; las imágenes viajan como bloques
  Pi y pasan por las restricciones actuales del gate. No hay un permiso nuevo ni cambios a SQLite.
- **Sesiones:** `capabilities.harness` en el JSON existente selecciona `pi` o `skynet`, conservado al
  reanudar. UUID estable por tarea enlaza las sesiones oficiales JSONL en `data/pi/sessions`; Pi lleva su
  historial y compactación. El adaptador espera `agent_settled`, registra uso incluyendo caché y, al parar,
  cierra el proceso Pi y sus conexiones. Se conserva la protección contra planes pendientes.
- **Modelo:** `data/pi/agent/models.json` y settings reproducen endpoint, contexto, salida, muestreo,
  razonamiento y visión del perfil local. Sin duplicar pesos ni lanzar otro servidor llama.cpp. LiteLLM
  sigue siendo útil para las llamadas habituales de Skynet; Pi usa su propio cliente de proveedor.
- **Interfaz:** selector Coder en web y `/coder pi|skynet` en terminal; `Probar Pi.cmd` prepara el repo
  aislado `prueba-pi` y reutiliza la web si ya está activa. El arranque general sigue usando Skynet.
  Alcance inicial: tareas Coder con repo y modelo local; móvil, nube y migración general quedan fuera.
- **Validación:** Pi y Qwen reales completan una función con ocho tests y una web con revisión de captura.
  Pruebas independientes comprueban controles, persistencia, tres anchos y cambio de motor. La comparación
  de calidad/latencia contra Skynet queda pendiente; estas pruebas demuestran funcionamiento, no superioridad.
