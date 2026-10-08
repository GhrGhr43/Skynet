# PROGRESO del proyecto Skynet

Última actualización: 2026-10-08 (automejora fase 2: propuestas y memoria, Claude).

## Estado: MVP implementado

| Punto del MVP | Estado | Dónde |
|---|---|---|
| 1. Tarea de código sobre repo autorizado, herramientas MCP, confirmación de riesgo, tarea en SQLite | Hecho | `coordinator.py`, `agent.py`, `gate.py`, `skynet_tools/workspace.py` |
| 2. Cerrar, abrir y «continúa» | Hecho | `Coordinator.resume`, `context.py` (incluye lo que hizo un paso cortado) |
| 3. Log de herramientas, modelo, tokens y coste | Hecho | `skynet log`, `/log`, tabla `events` |
| 4. Modelo local o cloud según política | Hecho (cloud desactivado hasta poner clave y presupuesto) | `router.py`, `config/router.toml` |
| 5. Tarea de N horas con modelo local, bucle verificado, commits y PROGRESO.md | Hecho | `scheduler.py`, `/largo`, `skynet largo` |

Verificación: 78 tests (`pytest -q`) con LLM guionizado y servidores MCP reales, 1 test de
integración con LM Studio (`-m lmstudio`), y pruebas manuales con Qwen 3.8 27B (abajo).

## Interfaz web (2026-10-07)
`skynet web` abre una interfaz gráfica local (ver README y D9 en docs/DECISIONES.md): nebulosa
3D en GPU que reacciona al cursor y cambia de color según el estado, chat, diálogo de permisos,
tareas, tarea larga, registro, modelos/repos, diagnóstico y ayuda. Probada en la nube con
Chromium (sin GPU real) y 10 tests nuevos en `tests/test_web.py`. **Falta probarla en el PC de
Daniel** (rendimiento real en la RX 9070 XT, calidad «ultra»).

## Motores locales (2026-10-08)
LM Studio (Qwen 27B) y Strata (Qwen3.8-Flash-Next Coder, C:Strata) se encienden y apagan desde
Ajustes de la web (`skynet/engines.py`, `[motores.*]` en config/skynet.toml). Comparten GPU: encender
uno apaga el otro. Probado en el PC: LM Studio carga en ~2 min, Strata en ~2 min.

## Automejora, fase 1 (2026-10-08)
- `/buscar <texto>`: búsqueda FTS5 en pasos y eventos de todas las tareas (esquema v2, ver D10).
  La base real de Daniel ya migró a v2 y se rellenó el índice con el historial existente.
- Skills de solo lectura en `skills/<nombre>/SKILL.md` (formato agentskills.io): el contexto
  lleva el catálogo; `/skills` las lista y `/skill <nombre> <tarea>` carga una. Ejemplo:
  `escribir-tests`. Skynet no escribe skills todavía (fase 2, pendiente de OK).
- 13 tests nuevos (`tests/test_busqueda.py`, `tests/test_skills.py`).
- Falta: probar `/skill` con el modelo local real y exponer la búsqueda en la web (hoy se usa
  escribiendo `/buscar` en su chat).

## Automejora, fase 2 (2026-10-08)
- Tras una tarea verificada con 3 o más pasos, Skynet propone una skill y añadidos de memoria en
  `skills\_propuestas\` (D11). `/propuestas`, `/aprobar <nombre>` (PRIVILEGED, auditado) y
  `/rechazar <nombre>`. El gate deniega escribir en `skills\` y `memoria\` fuera de /aprobar.
- Memoria curada `memoria\MEMORY.md` y `memoria\USER.md` (2 KB cada una), siempre en el contexto.
- Tabla `skill_uses` (esquema v3; la base real ya migró): `/skills` muestra la tasa de éxito.
- Web: botón «Propuestas N» en la cabecera cuando hay pendientes.
- 9 tests nuevos (`tests/test_propuestas.py`), con LLM guionizado.
- Falta: ver qué propuestas redacta Qwen de verdad (quizá haya que afinar el prompt de
  `propuestas.py`) y decidir si la redacción va en segundo plano: hoy el chat espera a que
  termine (una llamada más al modelo). Fase 3 (parches automáticos de skills) sin empezar.

## Decisiones tomadas por defecto (Daniel puede cambiarlas)
- Python para el Core.
- Cloud = Anthropic vía LiteLLM (`claude-opus-5-5`), desactivado: `presupuesto.mensual_eur = 0`
  y sin `ANTHROPIC_API_KEY`.
- El programador sirve para cualquier repo; el verificador se configura por repo.

## Pruebas con el modelo real (2026-10-07, Qwen 3.8 27B en LM Studio, repo demo)
- Tarea de chat «implementa es_palindromo»: leyó, editó, pasó pytest; verificador OK. 4 llamadas,
  8.968 + 3.135 tokens, unos 3 minutos. Todo visible en `skynet log`.
- Cierre a mitad: se mató el proceso tras las primeras lecturas; «continúa» retomó la misma
  tarea (el contexto incluyó lo que el paso cortado llegó a hacer) y la terminó con verificador OK.
- Tarea larga `skynet largo --repo demo --horas 0.5`: verificador inicial 1 de 3 tests;
  iteración 1 aceptada como avance (2 de 3), iteración 2 en verde con OBJETIVO_CUMPLIDO.
  Commits por iteración y `PROGRESO.md` en el repo.
- `/largo` desde el chat lanza el runner en segundo plano (sobrevive al chat) y deja log en
  `data/logs/tarea-N.log`.

Ritmo observado: 10 s a 2,5 min por llamada al modelo, según cuánto razone.

## Lecciones ya incorporadas
- El agente local editaba `PROGRESO.md` por su cuenta: ahora el gate lo protege en tareas largas.
- «Todos los tests en verde» como único criterio impedía avanzar por pasos: ahora una
  iteración se acepta si no empeora (ver D8 en docs/DECISIONES.md).
- Un runner muerto parecía vivo hasta 3 minutos: ahora se comprueba también su pid.

## Siguientes pasos propuestos
1. Daniel: elegir presupuesto cloud y poner la clave si quiere usarlo.
2. Añadir sus repos reales a `config/repos.toml` (y un juego de agente-godot con `agente = "agente-godot"`)
   y probar `/largo` con agente-godot (no probado aún con un juego real para no gastar GPU sin permiso).
3. Escalado automático local → cloud cuando el local falle N veces la misma iteración (el router
   ya lo permite con `reasoning = "alto"`; falta la regla en el Scheduler).
4. Servidores MCP de terceros (p. ej. serena) declarados en `config/skynet.toml`.
5. Separar en agente-godot lo genérico de lo específico de Godot (propuesta para su
   `MEJORAS-HERRAMIENTA.md`, sin tocarlo sin OK).
