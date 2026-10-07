# PROGRESO del proyecto JARVIS

Última actualización: 2026-10-07 (sesión inicial, Claude).

## Estado: MVP implementado

| Punto del MVP | Estado | Dónde |
|---|---|---|
| 1. Tarea de código sobre repo autorizado, herramientas MCP, confirmación de riesgo, tarea en SQLite | Hecho | `coordinator.py`, `agent.py`, `gate.py`, `jarvis_tools/workspace.py` |
| 2. Cerrar, abrir y «continúa» | Hecho | `Coordinator.resume`, `context.py` (incluye lo que hizo un paso cortado) |
| 3. Log de herramientas, modelo, tokens y coste | Hecho | `jarvis log`, `/log`, tabla `events` |
| 4. Modelo local o cloud según política | Hecho (cloud desactivado hasta poner clave y presupuesto) | `router.py`, `config/router.toml` |
| 5. Tarea de N horas con modelo local, bucle verificado, commits y PROGRESO.md | Hecho | `scheduler.py`, `/largo`, `jarvis largo` |

Verificación: 36 tests (`pytest -q`) con LLM guionizado y servidores MCP reales, más
pruebas manuales con Qwen 3.8 27B en LM Studio (ver «Pruebas con el modelo real»).

## Decisiones tomadas por defecto (Daniel puede cambiarlas)
- Python para el Core.
- Cloud = Anthropic vía LiteLLM (`claude-opus-5-5`), desactivado: `presupuesto.mensual_eur = 0`
  y sin `ANTHROPIC_API_KEY`.
- El programador sirve para cualquier repo; el verificador se configura por repo.

## Pruebas con el modelo real
(se completa abajo)

## Siguientes pasos propuestos
1. Daniel: elegir presupuesto cloud y poner la clave si quiere usarlo.
2. Añadir sus repos reales a `config/repos.toml` (y un juego de agente-godot con `agente = "agente-godot"`)
   y probar `/largo` con agente-godot (no probado aún con un juego real para no gastar GPU sin permiso).
3. Escalado automático local → cloud cuando el local falle N veces la misma iteración (el router
   ya lo permite con `reasoning = "alto"`; falta la regla en el Scheduler).
4. Servidores MCP de terceros (p. ej. serena) declarados en `config/jarvis.toml`.
5. Separar en agente-godot lo genérico de lo específico de Godot (propuesta para su
   `MEJORAS-HERRAMIENTA.md`, sin tocarlo sin OK).
