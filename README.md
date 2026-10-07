# JARVIS

Agente personal: un chat local al que dices «haz X» y que decide contexto, herramientas y
modelo. Detrás hay un Core pequeño y estable (Personal Agent OS) al que se enchufan
herramientas (servidores MCP), agentes y modelos sin reescribirlo.

- Diseño: [docs/DISENO-MVP.md](docs/DISENO-MVP.md)
- Decisiones y desviaciones: [docs/DECISIONES.md](docs/DECISIONES.md)
- Estado del proyecto y siguientes pasos: [PROGRESO.md](PROGRESO.md)

## Uso rápido

```powershell
cd C:\Skynet
.\.venv\Scripts\Activate.ps1      # o usa .\.venv\Scripts\jarvis.exe directamente
jarvis doctor                     # comprueba LM Studio, git, repos y servidores MCP
jarvis demo                       # crea el repo de prueba data\sandbox\demo
jarvis                            # abre el chat
```

O, con interfaz gráfica, `jarvis web` (o `.\jarvis web` desde `C:\Skynet`): abre
`http://127.0.0.1:8765` en el navegador. Ver [Interfaz web](#interfaz-web).

En el chat:

| Escribe | Qué pasa |
|---|---|
| `implementa slug en textos.py` | Tarea nueva sobre el repo elegido. JARVIS lee, edita y prueba con herramientas MCP; al final pasa el verificador. |
| `continúa` (o `continúa: y añade tests`) | Retoma la última tarea sin terminar, aunque hayas cerrado JARVIS. |
| `/largo 2 haz que pasen todos los tests` | Tarea larga en segundo plano con el modelo local: iteraciones verificadas, commit si avanza, rollback si empeora y `PROGRESO.md` en el repo. |
| `/estado 3`, `/parar 3`, `/tareas` | Seguir o parar tareas. |
| `/log` o `/log 3` | Herramientas usadas, decisión de permisos, modelo, tokens y coste. |
| `/repo demo`, `/repos` | Elegir repo autorizado. `/repo ninguno` = conversación sin herramientas. |
| `/modelo local\|cloud\|auto`, `/privado` | Forzar modelo o exigir privacidad (solo local). |

Fuera del chat: `jarvis log [--tarea N]`, `jarvis tareas`, `jarvis estado N`,
`jarvis largo --repo demo --horas 1 "objetivo"`.

Cuando una acción es de riesgo (comando fuera de la lista blanca, acción privilegiada o
destructiva), JARVIS pregunta: `s` (sí), `n` (no) o `t` (sí a esa herramienta durante la tarea).

## Interfaz web

```powershell
cd C:\Skynet
.\jarvis web                 # abre el navegador; Ctrl+C en la ventana para cerrar
.\jarvis web --puerto 9000 --no-abrir
```

Es el mismo JARVIS que el chat de terminal (mismo Coordinator, permisos, tareas y registro),
con todo visible sin saberse comandos:

- **Centro:** la nebulosa es JARVIS. Reacciona al cursor y su color dice qué hace: blanco
  azulado en espera, azul pensando, violeta usando herramientas, turquesa verificando, ámbar
  cuando te necesita, verde hecho, rojo si algo falla. Cada tarea larga en marcha es una luz
  en órbita.
- **Abajo:** escribe lo que quieras; las sugerencias cambian según el estado (continuar la
  tarea pendiente, tarea larga...). El botón cuadrado detiene la tarea (queda pausada).
- **Izquierda:** Tareas (continuar, parar, descartar, pasos, consumo, PROGRESO.md), Tarea
  larga (formulario), Registro y consumo, Modelos y repos (repo, modelo, privacidad, reglas
  del router, calidad visual), Diagnóstico y Qué puede hacer JARVIS.
- **Permisos:** las acciones de riesgo salen en un diálogo: Permitir (`S`), Denegar (`N`) o
  Permitir en toda la tarea (`T`).
- `Ctrl+K` abre todas las acciones con buscador. Los comandos `/` siguen funcionando.

Solo escucha en `127.0.0.1` y rechaza peticiones de otras webs (comprueba Host y Origin).
Sin dependencias nuevas: usa Starlette y uvicorn, que ya instala el SDK de MCP; Three.js va
incluido en `jarvis/web/static/vendor` (funciona sin internet). Calidad visual automática
según la GPU; se puede forzar con `?calidad=baja|media|alta|ultra` o en Modelos y repos, y
`?fps` muestra los fotogramas por segundo.

## Configuración (`config/`)

| Archivo | Para qué |
|---|---|
| `repos.toml` | Repos autorizados (fuera de ellos no se lee ni escribe nada), su verificador, privacidad y agente. |
| `permisos.toml` | Nivel de cada herramienta y lista blanca de comandos. |
| `router.toml` | Perfiles de modelo (local LM Studio, cloud Anthropic), reglas por capacidades y presupuesto mensual. |
| `jarvis.toml` | Rutas, límites del agente y de las tareas largas, y servidores MCP. |

Para cambios personales sin tocar los archivos versionados, crea `config/<nombre>.local.toml`
(se mezcla encima y git lo ignora).

**Activar el modelo cloud:** define `ANTHROPIC_API_KEY` en tu entorno y pon
`mensual_eur` > 0 en `router.toml`. Sin eso, todo va al modelo local.

**Añadir un repo tuyo:**

```toml
[repos.mi-web]
ruta = "C:/Users/HACHO/Documents/mi-web"
verificador = "npm test"
herramientas = ["workspace"]
```

**Usar agente-godot como programador de un juego:**

```toml
[repos.feudo]
ruta = "C:/Users/HACHO/Documents/agente-godot/juegos/feudo"
agente = "agente-godot"
herramientas = ["coding_agent"]
```

y en el chat `/repo feudo` y `/largo 3 avanza el PLAN.md`.

## Estructura

```
jarvis/          Core
  coordinator.py   chat -> tareas, comandos, «continúa»
  store.py         task store + audit log (SQLite, data/jarvis.db)
  gate.py          permission gate
  audit.py         eventos de auditoría
  context.py       context builder (git + archivos de estado, sin vector DB)
  router.py        model router (LiteLLM) con presupuesto
  agent.py         bucle modelo <-> herramientas
  scheduler.py     tareas largas verificadas (sin LLM en el control)
  verifier.py      verificador objetivo
  toolhub.py       cliente MCP
  runtime.py       ensamblaje de las piezas
  cli.py, views.py interfaz de terminal
  web/             interfaz web: server.py (HTTP + SSE) y static/ (Three.js, sin build)
jarvis_tools/    servidores MCP propios (workspace, coding_agent)
config/          configuración TOML
tests/           pytest (LLM guionizado + MCP real); tests/test_lmstudio.py usa el modelo real
data/            base de datos, logs y sandbox (ignorado por git)
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:JARVIS_TEST_LMSTUDIO = "1"; .\.venv\Scripts\python.exe -m pytest -q -m lmstudio   # con LM Studio abierto
```
