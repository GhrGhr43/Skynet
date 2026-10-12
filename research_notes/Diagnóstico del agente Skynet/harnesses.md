# Contexto, memoria y ejecución en otros harnesses

## ¿Qué contrato mantienen con la sesión y el proyecto?

### Takeaway
Codex, Claude Code, Pi y Hermes documentan una sesión duradera con identidad y directorio de trabajo, de la que reconstruyen el contexto. El proyecto seleccionado y lo ocurrido en una tarea interrumpida pertenecen a ese contrato de sesión: no deben depender de que el modelo los memorice como preferencias.

### Cited Findings
- **Fecha de esta investigación: 11 de octubre de 2026; referencia de la petición: 16:47, Europe/Madrid.** Se han buscado y abierto páginas oficiales durante esta sesión. Los enlaces a documentación viva y a ramas `main` no son snapshots históricos: describen lo servido al consultar, no garantizan que una versión instalada ayer tenga esas funciones. No se han tomado etiquetas del buscador como fechas de lanzamiento.
- **Codex:** `resume --last` busca por directorio actual; si el directorio guardado difiere, pide elegir, con opción de configuración. `--cd` tiene precedencia. Ofrece proveedor local LM Studio/Ollama mediante `--oss`; esto documenta integración, no igual calidad con cualquier modelo. — [Referencia CLI oficial](https://learn.chatgpt.com/docs/cli/reference).
- **Codex:** AGENTS se descubre desde raíz del proyecto hasta directorio actual, concatenando instrucciones, además de ámbito personal; el límite documentado es 32 KiB por defecto. — [Instrucciones AGENTS oficiales](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
- **Codex app-server:** define `thread/start`, `thread/resume`, `turn/start`, cwd y permisos. Devuelve las fuentes de instrucciones cargadas; las aprobaciones llevan threadId y turnId. Al bifurcar una ejecución activa documenta un marcador de interrupción. Es evidencia de contrato explícito, no recomendación de integrar toda la API en Skynet ahora. — [App Server oficial](https://learn.chatgpt.com/docs/app-server).
- **Claude Code:** guarda localmente cada mensaje, uso de herramienta y resultado en JSONL; continuar usa el mismo ID, bifurcar crea otro. Sesiones ligadas al directorio; el modelo consulta archivos y estado Git actuales. Sus fases reunir contexto, actuar y verificar componen el mismo loop en sus interfaces. — [Cómo funciona Claude Code](https://code.claude.com/docs/en/how-claude-code-works).
- **Pi:** registra respuestas, herramientas, resultados, cambios de modelo y compactions. La rama activa alimenta la siguiente solicitud; las interfaces interactiva, JSON, RPC y SDK usan los mismos mecanismos. — [How Pi Works, repo oficial](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/how-pi-works.md).
- **Pi:** `--continue` retoma la última sesión del cwd, organiza JSONL por directorio y conserva entradas originales al compactar. — [Sessions, repo oficial](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md).
- **Hermes:** SQLite contiene sesión, snapshot del prompt, mensajes completos, llamadas y resultados; permite buscar entre sesiones. Resume puede restaurar el directorio, y `--in` permite fijarlo. La propia documentación distingue bytes guardados y contenido enviado en cada turno. — [Sessions oficial](https://hermes-agent.nousresearch.com/docs/user-guide/sessions).
- **Skynet local:** D17 separa conversación sin contexto del repo de Coder con contexto, herramientas y verificador. D19 añade un agente externo que recibe conversación sin prompt/herramientas/gate de Skynet, mientras Coder/tareas largas usan loop local. — [DECISIONES.md](C:/Git/Skynet/docs/DECISIONES.md:232), [README.md](C:/Git/Skynet/README.md:127).

### Inferences
- Proyecto seleccionado debe ser un dato pequeño explícito de sesión enviado siempre: identidad, ruta, ejecución host/contenedor, instrucciones aplicables, capacidades activas y tarea actual. Estar en conversación puede evitar explorar el repo o cargar todos los schemas; no justifica ocultar qué repo está seleccionado.
- Separar **identidad de proyecto** de **carga costosa de contenido y herramientas** permite ahorrar tokens sin romper las referencias del usuario a «este repo». El patrón no exige cargar un informe Git y 15 herramientas para saludar.
- Si una tarea se detiene tras editar archivos, la siguiente petición necesita su objetivo, estado detenido y últimas acciones verificadas. Guardar solo parejas user/assistant con respuesta final deja un agujero precisamente cuando hace falta retomar.
- Más ventana o un nuevo modelo no recuperan información que el harness nunca envía. La verificación del auditor local (tarea 180 pausada, Coder off y repos NULL en 180–185 pese a selector) apunta al contrato de contexto. Esa evidencia la aporta el auditor; este investigador no ha interrogado la SQLite.
- Reloj y zona horaria son estado vivo obtenido del equipo, no un recuerdo estable en USER.md. Renovarlo en cada turno evita convertir «hoy» de ayer en la fecha actual. Ninguna fuente anterior prueba por sí sola una política exacta de inyección horaria de todos los productos.

### Gaps
- No se ha probado aquí qué hace cada versión instalada de los productos en este PC ni que una interrupción conserva todo proceso del sistema: persistir transcript y controlar procesos son problemas distintos.
- Para una comparación fiable falta ejecutar el mismo objetivo, modelo, presupuesto, permisos y verificador en varios harnesses. Documentación de arquitectura no establece rendimiento relativo.

## ¿Cómo separan memoria estable, historial y compaction?

### Takeaway
Recordar preferencias del usuario, reanudar un trabajo y aliviar la ventana son tres funciones distintas. La prioridad en Skynet es restaurar el estado operativo y el transcript; una memoria global más grande no sustituye eso.

### Cited Findings
- **Claude:** distingue instrucciones personales/proyecto de auto memory por repositorio, compartida entre worktrees. MEMORY.md es índice y hay archivos por tema; carga solo el principio del índice y puede consultar los demás. Advierte que instrucciones son contexto, no enforcement. — [Memory oficial](https://code.claude.com/docs/en/memory).
- **Claude:** recorta salidas antiguas y resume después; admite que se pueden perder instrucciones antiguas y recomienda archivos persistentes. — [Cómo funciona Claude Code](https://code.claude.com/docs/en/how-claude-code-works).
- **Codex:** documenta compaction automática y `/compact`, y diferencia quedarse en la misma conversación coherente de bifurcarla cuando cambia el trabajo. — [Best practices oficial](https://learn.chatgpt.com/docs/learn/best-practices).
- **Pi:** compaction guarda resumen estructurado, mantiene mensajes recientes y entradas originales; distingue resumen de rama de compaction. Su formato conserva objetivo, restricciones, progreso, decisiones, siguientes pasos y archivos leídos/modificados. — [Compaction, repo oficial](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md).
- **Pi:** los context files se descubren en ámbito personal, cwd y padres; no son los mismos que la configuración `.pi`. — [Configuration, repo oficial](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md).
- **Hermes:** dispone de MEMORY.md/USER.md limitados, write approval opcional, compresión configurable con LLM y salidas grandes volcadas a disco con preview/ruta; usa también engine de contexto extensible. La página de configuración y la de sesiones discrepan sobre compaction in-place frente a nueva sesión de continuación: no asegurar ese detalle sin fijar versión/código. — [Configuration oficial](https://hermes-agent.nousresearch.com/docs/user-guide/configuration), [Sessions oficial](https://hermes-agent.nousresearch.com/docs/user-guide/sessions).
- **Skynet:** D16 recorta resultados y reduce intercambios viejos a nombres de herramientas y primera línea, sin LLM; D20 añade escritura de preferencias/hechos globales en dos archivos de 2 KB. D23 introduce PLAN.md y bloques nuevos para tareas grandes. — [D16](C:/Git/Skynet/docs/DECISIONES.md:218), [D20](C:/Git/Skynet/docs/DECISIONES.md:279), [D23](C:/Git/Skynet/docs/DECISIONES.md:354).

### Inferences
- Un resumen operativo útil requiere **objetivo, restricciones, decisiones confirmadas, archivos modificados, pruebas, fallo pendiente y siguiente acción**. La primera línea de un resultado puede omitir el porqué y la ubicación exacta del trabajo.
- Reutilizar el esquema de checkpoint de Pi es más barato que inventar otra memoria vectorial: guardar estado estructurado más transcript original, y recuperar excerpts al necesitarlo. LLM summarization mejora capacidad de síntesis pero tiene coste/latencia y es falible; validar sus campos críticos contra estado determinista.
- Mantener tres ámbitos explícitos: preferencias personales persistentes; memoria de proyecto; estado/historial de sesión. Límites de 2 KB globales no explican olvidar el repo seleccionado ahora; aumentarlos como primera reparación sería atacar el síntoma equivocado.
- El proyecto puede mantener contexto breve y schemas descubiertos bajo demanda. La carga selectiva debe preservar identidad/instrucciones esenciales y permitir inspección cuando cambia el tipo de tarea, sin hacer que un switch manual decida si el agente sabe dónde está.

### Gaps
- No se ha medido precisión o coste de compaction con el modelo local de Daniel. No trasladar defaults numéricos de otros harnesses sin medir entradas reales.
- No se han encontrado en estas páginas pruebas de que memoria estable garantiza recordar cualquier conversación. Todas las estrategias tienen límites.

## ¿Qué reutilizar y qué decisiones causarán problemas?

### Takeaway
La experiencia «agente de PC» es viable como software: exige un loop coherente, contexto y permisos consistentes y verificación real. Igualar resultados de Claude/Codex con el modelo local no está probado; sustituir el harness tampoco garantiza arreglarlo.

### Cited Findings
- **Separación API/harness:** la documentación de OpenAI distingue Responses (la aplicación construye su agente y estado), Agents SDK (runner en la aplicación) y Agents API (harness gestionado). Pagar una API de modelo no implica obtener automáticamente sesiones, permisos o herramientas de Codex. — [Agents oficial](https://developers.openai.com/api/docs/guides/agents).
- **Pi:** ofrece modo RPC y SDK TypeScript; soporta Windows y requiere Node 22.19+ en documentación consultada. Se declara minimalista y extensible. — [README oficial](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md).
- **Pi:** project trust regula recursos del proyecto, pero las herramientas/extensiones usan los permisos OS del proceso. No es sandbox. — [How Pi Works](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/how-pi-works.md), [Índice/security del repo oficial](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/index.md).
- **Hermes:** documentación consultada publica Windows nativo, PowerShell/install.ps1 y MSIX; Windows 10/11 aparece como Tier 1, con restricciones de versión/arquitectura para opcionales. No se ha instalado ni probado. — [Installation](https://hermes-agent.nousresearch.com/docs/getting-started/installation), [Platform Support](https://hermes-agent.nousresearch.com/docs/getting-started/platform-support), [Windows Native](https://hermes-agent.nousresearch.com/docs/user-guide/windows-native).
- **OpenCode:** Build habilita herramientas, Plan restringe ediciones/ejecución, compaction automática es un agente oculto y hay permisos por herramienta/modelo; el proyecto no desaparece al cambiar de modo. — [Agents oficial](https://opencode.ai/docs/agents/), [Permissions oficial](https://opencode.ai/docs/permissions/).
- **Comparativa local:** una ejecución por tarea, siete tareas de banco y cinco de calidad, muestra pequeña reconocida. Hermes v0.21.6 en Linux/Docker; velocidades/empate documentados solo para esos casos. El propio test de renombrar resultó demasiado estricto. — [COMPARATIVA-HERMES.md](C:/Git/Skynet/docs/COMPARATIVA-HERMES.md:1).
- **Skynet:** Core Python pequeño, tools MCP y SQLite son decisiones explícitas; D19 cambia no solo modelo, sino cerebro, memoria y política de permisos para Hermes, mientras Coder y tareas largas fuerzan loop local. — [DECISIONES.md](C:/Git/Skynet/docs/DECISIONES.md:25), [D19](C:/Git/Skynet/docs/DECISIONES.md:258).

### Inferences
- Conservar Python, MCP, SQLite y herramientas Windows del proyecto tiene sentido. Reparar **SessionContext** y replay antes de cambiar motor permite aislar fallos del harness, del modelo y de la aplicación.
- Mantener un loop propio no es inviable, pero supone hacerse cargo de replay, cancelación, compaction, consistencia de tool calls, procesamientos largos, permisos y errores. El «Core debe crecer poco» necesita aceptar que gestión de sesión es responsabilidad central; convertirla en un MCP no elimina esa obligación.
- Si se evalúa Pi posteriormente, integrarlo por proceso RPC permite no reescribir Python, pero hace falta preservar los permisos/gate y los MCP existentes. Dos bucles activos, ambos decidiendo herramientas/aprobaciones y ambos con memoria propia, producen estados divergentes. En una tarea debe haber un dueño del loop y un contrato de sesión.
- Hermes ofrece más de un harness de programación y puede ser una buena alternativa, pero el contenedor Linux usado por Skynet no es automáticamente acceso al escritorio Windows: rutas, shells, procesos, ventanas y ejecución de juegos necesitan integración host explícita. Soporte nativo documentado merece ensayo futuro; no prueba arreglados los problemas de rutas de la versión medida ayer.
- La decisión cara es identidad persistente de sesión/workspace, formato de replay/checkpoint y ámbito de autorización; cambiar la etiqueta del modelo o subir memoria son decisiones menores que no reparan un contrato roto.
- Seleccionar «Nube» y pasar silenciosamente a local al entrar en Coder acopla capacidad/modelo/harness. Debe hacerse visible y, en futuro diseño aprobado, separar proveedor del modelo de dueño del loop. Aumentar calidad de modelo podría mejorar razonamiento, pero sigue sin ver datos omitidos.
- «Tests en verde» y «trabajó una hora» no son criterios suficientes de aceptación para un juego. Debería comprobar comportamiento de requisitos, interacciones, persistencia, errores y apariencia. Pruebas guiadas/arreglos hechos por Codex son evidencia de implementación, no de autonomía de Skynet.
- La conclusión local «el bucle no es peor» es demasiado general para la muestra: sostiene que resolvió bien tareas pequeñas bajo ese modelo, no conversaciones largas, cambios de modo, interrupciones, controles de PC o el objetivo complejo de Daniel. Mantener el loop provisionalmente es compatible con reconocerlo.
- Una evaluación comparativa futura debe incluir tarea pausada y retomada, cambio de repo, reabrir sesión, memoria por proyecto, error de herramienta, saturación de contexto, solicitud sobre juego y verificación independiente. Aplicar el mismo modelo/permisos/presupuesto y varias ejecuciones; no instalar/reemplazar nada como consecuencia automática de este informe.

### Gaps
- No hay prueba comparable de Pi frente a Skynet con el objetivo del usuario; no recomiendo migración total basándome en la documentación.
- No está verificada la equivalencia de nivel de resultados con modelos comerciales, ni autonomía visual para jugar. No afirmar que más herramientas, cron, memoria o subagentes la garantiza.
- No se ha hecho un análisis de licencias o de compatibilidad de versiones suficientemente detallado para aprobar una integración; requeriría diseño y OK de Daniel conforme AGENTS.
