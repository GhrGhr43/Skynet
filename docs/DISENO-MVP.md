# JARVIS: diseño del MVP (borrador para aprobar)

Fecha: 2026-10-07. Estado: **pendiente de tu OK**. No hay código escrito todavía.

## 1. Decisiones caras de cambiar (las que necesito que apruebes)

| # | Decisión | Propuesta | Por qué | Alternativa |
|---|---|---|---|---|
| D1 | Lenguaje del Core | **Python 3.12+** | Mejor SDK oficial de MCP, LiteLLM es Python, SQLite viene incluido | TypeScript (también tiene SDK MCP, pero LiteLLM no) |
| D2 | Protocolo de herramientas | **MCP** (cliente MCP dentro del Core) | Estándar; ya usas MCP (serena, blender) | Herramientas propias (rompe el principio 3) |
| D3 | Acceso a modelos | **LiteLLM** como librería | Un solo API para LM Studio, Anthropic, OpenAI; calcula coste por llamada | Llamar a cada API a mano |
| D4 | Esquema SQLite | Tablas `tasks`, `steps`, `events` (abajo) | Es la memoria de JARVIS; migrar luego es caro | — |
| D5 | Agente programador | **agente-godot como proceso externo** (PowerShell), envuelto como servidor MCP | Reutilizar sin reescribir; JARVIS no sabe de Godot | Reescribirlo en Python (mucho trabajo, sin ganancia ahora) |
| D6 | Interfaz | **Chat en terminal** (`jarvis` en PowerShell) | Mínimo; la UI web es no-objetivo | TUI con Textual más adelante, sin tocar el Core |

## 2. Qué se reutiliza (no se construye)

- **MCP SDK oficial (Python)**: conectar herramientas.
- **Servidores MCP existentes**: filesystem, git, serena (ya lo tienes), shell limitado.
- **LiteLLM**: router de modelos + cálculo de coste/tokens.
- **LM Studio**: modelo local (Qwen3.8 27B en tu 9070 XT, API compatible OpenAI en `localhost:1234`).
- **OpenCode + agente-godot**: el bucle de programación verificado que ya funciona (noche.ps1, historial, capacidades medidas, gasto).
- **SQLite** (módulo `sqlite3` de Python): task store y audit log.
- **git**: checkpoints, commit si pasa el verificador, rollback si falla.

## 3. Arquitectura

```
 Tú ──chat──> Coordinator ──> Task store (SQLite)
                 │   │
                 │   └──> Context builder (git, ripgrep, archivos de estado)
                 │
                 ├──> Model router (LiteLLM: local LM Studio | cloud)
                 │
                 └──> Permission gate ──> Cliente MCP ──> servidores MCP
                                                          ├ filesystem / git / shell
                                                          └ coding-agent (agente-godot)
 Todo paso ──> Audit log (SQLite: herramienta, modelo, tokens, coste, permiso)
 Scheduler (sin LLM) ──> lanza/vigila tareas largas, límites y reintentos
```

### Componentes

1. **Coordinator**: bucle de chat. Convierte el mensaje en tarea, elige agente, ejecuta pasos. "continúa" = reanudar la última tarea no terminada desde SQLite.
2. **Task store**: estados `pendiente → en_curso → esperando_permiso → hecha | fallida | pausada`.
3. **Permission gate**: cada herramienta MCP se declara con un nivel en `config/permisos.toml`:
   - READ: automático. WRITE: automático dentro del repo autorizado.
   - EXECUTE: automático solo si está en lista blanca (tests, build).
   - PRIVILEGED / DESTRUCTIVE: siempre pregunta en el chat y queda auditado.
   - Repos autorizados: lista explícita en la config. Fuera de ella, todo se deniega.
4. **Audit log**: tabla `events`. Comando `jarvis log` para verlo (tarea, herramienta, modelo, tokens, €).
5. **Context builder**: sin vector DB. Usa `git status/diff/log`, ripgrep, y los archivos de estado de la tarea (OBJETIVO, PROGRESO, ERRORES). Tope de tokens configurable.
6. **Model router**: los agentes piden capacidades, no modelos: `{privacy, coding, reasoning, cost}`. Política simple en `config/router.toml`, por ejemplo:
   - `privacy=alta` → siempre local.
   - tarea larga o barata → local.
   - `reasoning=alto` y presupuesto disponible → cloud.
   - Si el presupuesto mensual se agota → local.
7. **Scheduler**: tareas largas en iteraciones cortas, cada una con sesión nueva:
   `leer estado → 1 paso → verificador → commit si pasa / git reset si falla → actualizar PROGRESO.md`.
   Paradas: límite de horas, de iteraciones, y N errores iguales seguidos.

## 4. Esquema SQLite (D4)

```sql
tasks(id, parent_id, title, goal, repo, agent, status, created_at, updated_at,
      max_hours, max_iters, iters_done)
steps(id, task_id, n, kind, input_summary, output_summary, verifier_result,
      commit_sha, started_at, ended_at)
events(id, ts, task_id, step_id, type, tool, permission_level, decision,
       model, tokens_in, tokens_out, cost_eur, detail_json)
```

## 5. agente-godot como Coding Agent (D5)

- JARVIS no lo reescribe ni lo mueve. Un pequeño servidor MCP (`mcp-coding-agent`) expone:
  `start_task(repo, objetivo, horas)`, `status(task)`, `stop(task)`, `history(task)`.
- Por dentro llama a sus scripts PowerShell y lee su `HISTORIAL-LOCAL.csv` y gasto para volcarlos al audit log.
- Primer paso: separar en agente-godot lo genérico (bucle, verificador, historial) de lo específico de Godot. **Esto lo propondría en su `MEJORAS-HERRAMIENTA.md`, no lo cambio sin tu OK.**
- Pregunta abierta: ¿quieres que el programador sirva también para repos que no son Godot (Python, web)? Si sí, el verificador debe ser configurable por repo (`pytest`, `npm test`, `godot --headless`).

## 6. Estructura en C:\Skynet

```
C:\Skynet\
  jarvis\            código del Core (Python)
    coordinator.py  store.py  gate.py  audit.py  context.py  router.py  scheduler.py
  mcp\coding-agent\  adaptador de agente-godot
  config\            permisos.toml  router.toml  repos.toml
  data\jarvis.db     SQLite
  docs\              este diseño y decisiones (ADR)
  tests\
```

## 7. Plan por hitos (cada uno verificable)

1. Store + audit + chat mínimo con LM Studio (punto 3 del MVP).
2. Cliente MCP + permission gate sobre un repo autorizado (punto 1).
3. Reanudar con "continúa" (punto 2).
4. Router local/cloud con presupuesto (punto 4).
5. Scheduler + adaptador agente-godot: tarea de N horas con commits y PROGRESO.md (punto 5).

## 8. Datos que me faltan

- Presupuesto cloud al mes (€) y qué proveedor cloud (¿Anthropic API?).
- Horas por semana que le dedicas.
- ¿Python te vale?
