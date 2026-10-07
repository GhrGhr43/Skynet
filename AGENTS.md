# Instrucciones para agentes que trabajen en este repo

Proyecto: Skynet, el agente personal de Daniel (Windows, Python). Lee primero
[PROGRESO.md](PROGRESO.md) (estado y siguientes pasos), [README.md](README.md) (uso) y
[docs/DECISIONES.md](docs/DECISIONES.md) (por qué está hecho así).

Reglas del proyecto:
- Antes de implementar algo grande, propón el diseño y espera el OK de Daniel.
- Señala las decisiones caras de cambiar (esquema SQLite, contratos MCP, política de permisos).
- Reutiliza antes que construir (MCP, LiteLLM, LM Studio, SQLite, git).
- El Core (`skynet/`) debe crecer poco: herramientas nuevas = servidores MCP (`skynet_tools/`
  o de terceros) declarados en `config/`.
- Nunca edites una migración ya publicada de `skynet/store.py`; añade una nueva.
- No modifiques agente-godot (`C:\Users\HACHO\Documents\agente-godot`); las mejoras se
  proponen en su `MEJORAS-HERRAMIENTA.md`.

Comprobar antes de dar algo por bueno:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\skynet.exe doctor
```
Escribe código y comentarios en el mismo estilo (español, comentarios breves con el porqué).
Al terminar una sesión de trabajo, actualiza PROGRESO.md.
