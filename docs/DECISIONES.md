# Decisiones (ADR) del MVP

Cada decisión indica si es **cara de cambiar** (afecta a datos guardados o a contratos) o barata.

## D1. Python para el Core — cara
Python 3.14 en `.venv`. El SDK oficial de MCP y LiteLLM son Python. Aprobado por defecto
el 2026-10-07 (Daniel no contestó; el coordinador eligió el valor recomendado del diseño).

## D2. Herramientas = servidores MCP — cara
El Core solo habla MCP (`jarvis/toolhub.py`). Las herramientas propias están en
`jarvis_tools/` como servidores MCP independientes que se lanzan por stdio:
- `workspace`: archivos, búsqueda, git y comandos dentro de un único repo.
- `coding_agent`: envuelve agente-godot (noche.ps1) sin modificarlo.

Desviación del diseño: la carpeta se llama `jarvis_tools/` y no `mcp/`, porque una carpeta
`mcp` en la raíz taparía el paquete `mcp` del SDK al ejecutar desde `C:\Skynet`.

SDK MCP 2.x: `FastMCP` pasó a llamarse `MCPServer` (`mcp.server.mcpserver`). El cliente usa
`ClientSession` + `stdio_client` (con el stderr de cada servidor a `data/logs/mcp-<nombre>.log`).

Añadir una herramienta: escribir un servidor MCP (propio o de terceros), declararlo en
`config/jarvis.toml` bajo `[mcp.<nombre>]`, darle nivel a sus herramientas en
`config/permisos.toml` y añadir su nombre a `herramientas` del repo en `config/repos.toml`.

## D3. LiteLLM como librería — barata
`jarvis/router.py` llama `litellm.acompletion`. Coste: si el perfil del modelo trae precios
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

Cambios futuros: añadir una entrada a `MIGRATIONS` en `jarvis/store.py`; nunca editar la v1.

## D5. agente-godot como proceso externo — barata
`coding_agent.start_task(repo, horas)` lanza `sistema\noche.ps1 -Juego <repo> -Horas <h>` y
el Scheduler lo vigila sin LLM. El trabajo lo define el `PLAN.md` del juego, como siempre.
Para usarlo: añadir el juego a `repos.toml` con `agente = "agente-godot"` y
`herramientas = ["coding_agent"]`, y lanzar `/largo <horas> <objetivo>` desde el chat.
No se ha tocado nada de agente-godot.

## D6. Chat en terminal — barata
`jarvis` abre el chat. Cada mensaje es una tarea nueva; «continúa» retoma la última sin
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
el fallo se anota en `.jarvis/tarea-N/ERRORES.md`. La tarea solo es `hecha` si el verificador
está en verde **y** el agente escribe `OBJETIVO_CUMPLIDO`. Se para con: límite de horas o de
iteraciones, el mismo fallo N veces seguidas, N iteraciones sin cambios, o `/parar`.

## D9. Interfaz web local — barata
`jarvis web` sirve una página en `127.0.0.1:8765` con el **mismo** Coordinator que el chat de
terminal (`jarvis/web/server.py`): la web es otra UI del Protocol `UI`, no un segundo camino de
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
  estructurados (`jarvis doctor` imprime lo mismo que antes).
