# Skynet: qué lo frena frente a OpenClaw y plan de recorte

Fecha: 2026-10-09. Estado: **pendiente de tu OK**. Basado en el código de Skynet (rama del rediseño + fase 1)
y en el código actual de OpenClaw (`src/agents/system-prompt*.ts`) y Hermes Agent (`agent/prompt_builder.py`,
`agent/background_review.py`), clonados hoy.

## El concepto (corrígelo si no es así)
Skynet = **un solo agente tipo OpenClaw, tuyo**: hablas con él como en un chat y hace cosas en tu PC con
herramientas (archivos, comandos, web, repos). Local primero, nube si la eliges. **Aprende como Hermes**:
guarda recuerdos y recetas (skills) mientras trabaja y los usa solo cuando vienen al caso. Permisos seguros
sin estorbar. Personalizable: añadir herramientas = añadir un MCP.

Lo que se construyó de más venía del «MVP» de las instrucciones iniciales: cada mensaje es una **tarea de
código** en SQLite con repo, verificador, commits y tareas largas. Eso sirve para programar, pero hoy se aplica
también a un «hola».

## Qué pasa al decir «hola» (medido)
Con un repo elegido (el «demo» de tu captura) y el modo «Ver y editar»:
1. Se crea una **tarea** en SQLite y un paso.
2. Se arrancan **2 servidores MCP** (workspace + sistema): **~2,3 s** en la nube, en cada mensaje.
3. Al modelo le llegan ~3.000 tokens (tu captura: 3.001):
   - ~1.550 de **15 esquemas de herramientas** (la mitad del total),
   - ~350 de prompt de «agente de programación» y modo de permisos,
   - ~1.000 de **contexto del repo**: «Objetivo de la tarea: hola», PROGRESO.md, git status, commits,
     lista de archivos, verificador, memoria y catálogo de skills.
4. Razona en nivel «medio» (hasta 4.096 tokens de pensar) aunque sea un saludo.
5. Resultado: el modelo ve un informe del repo y lo comenta («la tarea 5 ya está completada...»).
   La tarea 64 falló porque el motor local estaba apagado (error de conexión, no del modelo).

OpenClaw y Hermes no hacen eso: el mensaje es un **turno de una conversación** (con el historial real),
el contexto de trabajo va aparte con la orden «úsalo sin comentarlo», y Hermes abre su prompt con «ajusta
la longitud al peso de la petición». También mandan muchas herramientas (OpenClaw más que Skynet), pero
con modelos grandes en la nube; en un modelo local de 3B activos cada token de prompt pesa más.

## Desglose: cuánto frena cada pieza
| Pieza | Inteligencia | Velocidad | Propuesta |
|---|---|---|---|
| Cada mensaje es una «tarea» con contexto del repo | **Alta**: le hace hablar de lo que no le preguntas | Media (~1.000 tokens) | **Quitar** en chat: conversación normal; el repo es una línea («carpeta activa: demo») y lee lo que necesite con herramientas |
| Historial = solo 3 intercambios recortados a 300/500 caracteres dentro del mensaje | **Alta**: no recuerda la conversación | Baja | Historial real de la sesión (el rediseño ya guarda sesiones) + la ventana de la fase 1 |
| Razonamiento «medio» siempre | Baja | **Alta**: hasta 4.096 tokens a ~35 tok/s | Auto de verdad: mensaje corto sin acción = sin pensar; tareas = medio |
| Servidores MCP arrancados en cada mensaje | Ninguna | **Media**: ~2,3 s por mensaje | Mantenerlos vivos durante la sesión |
| 15 esquemas de herramientas siempre | Media en local | Media (~1.550 tokens) | Juntar git_status/diff/log en una; las de `sistema` solo si el modo lo permite (hecho) |
| Aprendizaje: solo propone tras tarea verificada de 3+ pasos y pide `/aprobar` | **Alta a largo plazo**: casi nunca aprende | Ninguna | Como Hermes: herramientas `memoria` y `skill` que el modelo usa al trabajar + repaso en segundo plano cada ~10 turnos; tú apruebas con la tarjeta discreta |
| Skills: el modelo ve la lista pero no puede abrirlas | Media | Ninguna | Herramienta para leer una skill cuando venga al caso (como OpenClaw y Hermes) |
| Permission gate y modos | Ninguna (no van al prompt salvo ~100 tokens) | Ninguna | Mantener |
| Auditoría, coste, router de modelos | Ninguna (fuera del prompt) | Ninguna | Mantener |
| Verificador y commits | Ninguna en chat (solo corre si cambian archivos) | Ninguna | Mantener para código |
| Tareas largas, agente-godot, móvil, web | Ninguna salvo que las uses | Ninguna | Mantener, opcionales |
| Motor apagado al escribir | — | Falla la tarea | Encenderlo solo o avisar sin crear tarea fallida |

Resumen: lo que más le quita inteligencia es **tratar cada mensaje como tarea de código** y **no tener
memoria de la conversación**. Lo que más le quita velocidad es **pensar siempre** y **arrancar los MCP en
cada mensaje**. La seguridad, la auditoría y el verificador casi no cuestan nada.

## Plan de recorte (orden)
1. **Conversación primero**: mensaje = turno de sesión con historial real; contexto del repo fuera del mensaje
   (una línea y herramientas para leer). Tarea en SQLite solo cuando el modelo edita o ejecuta algo.
   Toca `coordinator.py`/sesiones: lo coordino con el hilo del rediseño, que es dueño de esa parte.
2. **Auto de verdad** en razonamiento y **MCP vivos** por sesión.
3. **Aprende como Hermes**: herramientas de memoria y skills + repaso en segundo plano; aprobación con la
   tarjeta discreta que ya existe (`/api/aprendizaje`).
4. Medir: «hola» < 900 tokens, sin pensar, < 3 s con el motor encendido; y el bench agéntico antes/después.

Ya hecho (pequeño, en el PR #1): el prompt pide ajustar la respuesta al peso de la petición y no comentar
el contexto del repo si no se pide.
