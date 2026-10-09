# Skynet: qué copiar de Hermes Agent y OpenClaw (propuesta, sin código)

Fecha: 2026-10-07. Estado: **pendiente de tu OK**.

## Resumen de los dos repos
- **Hermes Agent (Nous Research)**: su punto fuerte es el "bucle de aprendizaje": crea *skills* (recetas en Markdown, estándar agentskills.io) tras tareas complejas, las mejora al usarlas, guarda memoria curada (MEMORY.md + USER.md con límite de tamaño), y busca en conversaciones pasadas con SQLite FTS5.
- **OpenClaw**: pasarela de agente personal multi-canal (Telegram, WhatsApp...). Lo útil para Skynet es su postura de seguridad: los mensajes entrantes son no fiables, emparejamiento de remitentes, sandbox opcional para herramientas. Sus skills de terceros (ClawHub) son un riesgo y van contra tus no-objetivos.

## Ideas a adoptar (en orden de valor/coste)
1. **Skills como memoria de procedimientos** (Hermes). Carpeta `C:\Skynet\skills\<nombre>\SKILL.md`. Al modelo solo le llega nombre + descripción de cada skill (pocas líneas); el cuerpo se carga solo si la usa. Encaja con eficiencia de tokens. Se usan con `/skill` en el chat.
2. **Búsqueda en el historial con FTS5** (Hermes). Tabla virtual FTS5 sobre `steps` y `events` que ya existen; `/buscar texto`. Es SQLite puro, sin base vectorial. El Context builder puede añadir 2-3 resultados relevantes a la tarea.
3. **Automejora verificada** (Hermes, adaptado a tu principio 7). Diferencia clave: en Hermes el agente decide si una skill es buena; en Skynet lo decide el verificador.
   - Tras una tarea que **pasó el verificador** y tuvo varios pasos, Skynet redacta una skill candidata en `skills\_propuestas\`.
   - Tabla nueva `skill_uses(skill, version, task_id, verifier_ok)`: tasa de éxito objetiva por versión.
   - Si una skill falla N veces, Skynet propone un parche (nueva versión); si la nueva versión rinde peor que la anterior, vuelve a la anterior sola (git).
   - Promover una propuesta a skill activa = acción PRIVILEGED: te la enseña y pide OK.
4. **Memoria curada con tope** (Hermes): `MEMORY.md` (hechos del entorno) y `USER.md` (tus preferencias), máx. ~2 KB cada una, que siempre van al contexto. Cambios propuestos por Skynet al final de una tarea, con OK.
5. **"Permitir siempre" con patrones** (Hermes/OpenClaw): cuando apruebas un comando, opción de guardar el patrón en `config/permisos.toml`. Menos preguntas sin abrir agujeros.
6. **Servidor web solo en 127.0.0.1 y entradas no fiables** (OpenClaw): contenido de repos, webs o ficheros nunca puede cambiar permisos ni memoria por sí solo.

## Lo que NO propongo copiar
- Canales de mensajería, hub de skills de terceros, backends Docker/Modal/SSH, modelado de usuario con Honcho. Más superficie de ataque y fuera del MVP.
- Que Skynet edite su propio Core (gate, audit, router) de forma autónoma. Si algún día se automejora el código de Skynet, sería en rama aparte, con tests y tu OK para fusionar.

## Cómo encaja en el código actual
- `context.py`: añade lista de skills (nombre+descripción), MEMORY.md/USER.md y resultados FTS5.
- `store.py`: tablas `skill_uses` y `steps_fts` (migración aditiva, no rompe nada).
- `coordinator.py`: al cerrar una tarea verificada, paso "proponer skill/memoria"; comandos `/skill`, `/buscar`, `/memoria`.
- `gate.py`: escribir en `skills\` activas, `MEMORY.md` o `permisos.toml` = PRIVILEGED.
- Web: un panel "Aprendizaje" con propuestas pendientes de aprobar (después).

## Decisiones caras de cambiar
- **Formato de skill**: adoptar el estándar agentskills.io (SKILL.md con frontmatter). Recomiendo sí: compatible con Hermes, Claude Code y OpenClaw.
- **Esquema SQLite** (`skill_uses`, FTS5): aditivo, pero define cómo se mide el éxito para siempre.
- **Quién aprueba**: propongo que todo aprendizaje pase por tu OK al principio; se puede relajar después por tipo.

## Riesgos de seguridad
- **Envenenamiento de memoria/skills**: un README malicioso en un repo puede inducir una skill o memoria dañina. Mitigación: aprobación humana + skills sin scripts ejecutables (solo texto) en esta fase.
- **Skills con código**: si más adelante llevan scripts, se ejecutan con el nivel EXECUTE del gate, nunca saltándolo.
- **Deriva**: una skill "mejorada" peor que la original. Mitigación: versiones en git y vuelta atrás automática por tasa de éxito.

## Fases propuestas
1. FTS5 + skills manuales de solo lectura (pequeño).
2. Propuestas de skill/memoria tras tareas verificadas, con tu OK.
3. Métricas por versión y parches automáticos con vuelta atrás.
