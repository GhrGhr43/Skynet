# Skynet

Agente personal: un chat local al que dices «haz X» y que decide contexto, herramientas y
modelo. Detrás hay un Core pequeño y estable (Personal Agent OS) al que se enchufan
herramientas (servidores MCP), agentes y modelos sin reescribirlo.

- Diseño: [docs/DISENO-MVP.md](docs/DISENO-MVP.md)
- Decisiones y desviaciones: [docs/DECISIONES.md](docs/DECISIONES.md)
- Estado del proyecto y siguientes pasos: [PROGRESO.md](PROGRESO.md)

## Uso rápido

```powershell
cd C:\Skynet
.\.venv\Scripts\Activate.ps1      # o usa .\.venv\Scripts\skynet.exe directamente
skynet doctor                     # comprueba LM Studio, git, repos y servidores MCP
skynet demo                       # crea el repo de prueba data\sandbox\demo
skynet                            # abre el chat
```

O, con interfaz gráfica, `skynet web` (o `.\skynet web` desde `C:\Skynet`): abre
`http://127.0.0.1:8765` en el navegador. Ver [Interfaz web](#interfaz-web).

En el chat:

| Escribe | Qué pasa |
|---|---|
| `implementa slug en textos.py` | Tarea nueva sobre el repo elegido. Skynet lee, edita y prueba con herramientas MCP; al final pasa el verificador. |
| `continúa` (o `continúa: y añade tests`) | Retoma la última tarea sin terminar, aunque hayas cerrado Skynet. |
| `/largo 2 haz que pasen todos los tests` | Tarea larga en segundo plano con el modelo local: iteraciones verificadas, commit si avanza, rollback si empeora y `PROGRESO.md` en el repo. |
| `/estado 3`, `/parar 3`, `/tareas` | Seguir o parar tareas. |
| `/log` o `/log 3` | Herramientas usadas, decisión de permisos, modelo, tokens y coste. |
| `/repo demo`, `/repos` | Elegir repo autorizado. `/repo ninguno` = conversación sin herramientas. |
| `/modelo local\|cloud\|auto`, `/privado` | Forzar modelo o exigir privacidad (solo local). |
| `/buscar parser toml` | Busca en el historial de todas las tareas (pasos y eventos); 10 resultados por relevancia. |
| `/skills`, `/skill escribir-tests añade tests a textos.py` | Lista las skills o lanza una tarea siguiendo una ([Skills](#skills)). |

Fuera del chat: `skynet log [--tarea N]`, `skynet tareas`, `skynet estado N`,
`skynet largo --repo demo --horas 1 "objetivo"`.

Cuando una acción es de riesgo (comando fuera de la lista blanca, acción privilegiada o
destructiva), Skynet pregunta: `s` (sí), `n` (no) o `t` (sí a esa herramienta durante la tarea).

### Skills

Una skill es una carpeta `skills/<nombre>/SKILL.md` en el formato de
[agentskills.io](https://agentskills.io): frontmatter con `name` (igual que la carpeta;
minúsculas, números y guiones) y `description`, y debajo las instrucciones en Markdown.
Skynet solo pone en el contexto la lista de nombres y descripciones; el cuerpo entra cuando
pides `/skill <nombre> <tarea>` (y sigue entrando si dices «continúa»). Ejemplo:
[skills/escribir-tests](skills/escribir-tests/SKILL.md). `/skills` muestra cuántas veces se ha
usado cada una y cuántas pasó el verificador.

Cuando una tarea pasa el verificador tras 3 o más pasos, Skynet **propone** una skill nueva y
datos para su memoria en `skills\_propuestas\`. Nada se activa sin ti: `/propuestas`,
`/aprobar <nombre>` (te pide confirmación) o `/rechazar <nombre>` (`memoria` = los añadidos de
memoria). La memoria curada son `memoria\MEMORY.md` (hechos del entorno) y `memoria\USER.md`
(tus preferencias), de 2 KB como mucho cada una; siempre van en el contexto y puedes editarlas
a mano. Las herramientas del agente no pueden escribir en `skills\` ni en `memoria\`.

## Interfaz web

```powershell
cd C:\Skynet
.\skynet web                 # abre el navegador; Ctrl+C en la ventana para cerrar
.\skynet web --puerto 9000 --no-abrir
```

Es el mismo Skynet que el chat de terminal (mismo Coordinator, permisos, tareas y registro),
con todo visible sin saberse comandos:

- **Centro:** la nebulosa es Skynet. Reacciona al cursor y su color dice qué hace: blanco
  azulado en espera, azul pensando, violeta usando herramientas, turquesa verificando, ámbar
  cuando te necesita, verde hecho, rojo si algo falla. Cada tarea larga en marcha es una luz
  en órbita.
- **Abajo:** escribe lo que quieras; las sugerencias cambian según el estado (continuar la
  tarea pendiente, tarea larga...). El botón cuadrado detiene la tarea (queda pausada).
- **Izquierda:** Tareas (continuar, parar, descartar, pasos, consumo, PROGRESO.md), Tarea
  larga (formulario), Registro y consumo, Modelos y repos (repo, modelo, privacidad, reglas
  del router, calidad visual), Diagnóstico y Qué puede hacer Skynet.
- **Permisos:** las acciones de riesgo salen en un diálogo: Permitir (`S`), Denegar (`N`) o
  Permitir en toda la tarea (`T`).
- `Ctrl+K` abre todas las acciones con buscador. Los comandos `/` siguen funcionando.

Solo escucha en `127.0.0.1` y rechaza peticiones de otras webs (comprueba Host y Origin).
Sin dependencias nuevas: usa Starlette y uvicorn, que ya instala el SDK de MCP; Three.js va
incluido en `skynet/web/static/vendor` (funciona sin internet). Calidad visual automática
según la GPU; se puede forzar con `?calidad=baja|media|alta|ultra` o en Modelos y repos, y
`?fps` muestra los fotogramas por segundo.

## Configuración (`config/`)

| Archivo | Para qué |
|---|---|
| `repos.toml` | Repos autorizados (fuera de ellos no se lee ni escribe nada), su verificador, privacidad y agente. |
| `permisos.toml` | Nivel de cada herramienta y lista blanca de comandos. |
| `router.toml` | Perfiles de modelo (local LM Studio, cloud Anthropic), reglas por capacidades y presupuesto mensual. |
| `skynet.toml` | Rutas, límites del agente y de las tareas largas, y servidores MCP. |

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
skynet/          Core
  coordinator.py   chat -> tareas, comandos, «continúa»
  store.py         task store + audit log (SQLite, data/skynet.db)
  gate.py          permission gate
  audit.py         eventos de auditoría
  context.py       context builder (git + archivos de estado, sin vector DB)
  skills.py        skills de solo lectura (skills/<nombre>/SKILL.md)
  propuestas.py    propuestas de skill y memoria, /aprobar y /rechazar
  router.py        model router (LiteLLM) con presupuesto
  agent.py         bucle modelo <-> herramientas
  scheduler.py     tareas largas verificadas (sin LLM en el control)
  verifier.py      verificador objetivo
  toolhub.py       cliente MCP
  runtime.py       ensamblaje de las piezas
  cli.py, views.py interfaz de terminal
  web/             interfaz web: server.py (HTTP + SSE) y static/ (Three.js, sin build)
skynet_tools/    servidores MCP propios (workspace, coding_agent)
config/          configuración TOML
skills/          skills (formato agentskills.io); _propuestas/ = borradores sin aprobar
memoria/         memoria curada (MEMORY.md, USER.md)
tests/           pytest (LLM guionizado + MCP real); tests/test_lmstudio.py usa el modelo real
data/            base de datos, logs y sandbox (ignorado por git)
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:SKYNET_TEST_LMSTUDIO = "1"; .\.venv\Scripts\python.exe -m pytest -q -m lmstudio   # con LM Studio abierto
```
