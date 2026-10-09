# Skynet más listo con el modelo local (propuesta)

Fecha: 2026-10-09. Estado: **pendiente de tu OK**.
Revisado sobre el código real de C:\Skynet (agent.py, context.py, router.py, skills.py, config), solo lectura.

## Respuesta corta
Hoy Skynet funciona con el local, pero no está optimizado para él: trata igual a un modelo de 3B activos
con 32K de contexto que a uno cloud de 1M. Lo que más le quita inteligencia al local no es el modelo,
es lo que le mandamos.

## Qué frena al local hoy (comprobado en el código)
1. **El contexto se llena y nadie lo vacía.** `agent.py` añade cada resultado de herramienta (hasta 6000
   caracteres) al historial y nunca recorta. Con 32K y `max_tokens = 8192` reservados para la salida,
   a los 12-20 turnos el modelo trabaja con el contexto lleno: se olvida del objetivo o falla.
2. **Ve todas las herramientas siempre.** `hub.openai_tools()` manda todos los esquemas en cada turno.
   Cada esquema son tokens y una opción más para equivocarse.
3. **Sin parámetros de muestreo.** No se manda temperatura/top_p/top_k: llama-server usa los suyos
   (temperatura 0.8), no los que recomienda Qwen para uso agéntico.
4. **Las skills solo se usan si escribes `/skill`.** El modelo ve el catálogo (`context.py`), pero se le
   dice que solo tú puedes cargarlas y no tiene forma de leer una, así que lo aprendido casi nunca se usa.
5. **Solo aprende de los éxitos** (tarea verificada de 3+ pasos). Tus correcciones y los fallos que
   luego se arreglan, que es donde más se aprende, se pierden.
6. **Empieza medio a ciegas en cada repo**: ve la lista de archivos (200 primeros) pero no qué hay dentro,
   así que gasta turnos leyendo para orientarse.
7. **Un JSON mal formado en una llamada cuesta un turno entero** (frecuente en modelos locales).

## Propuesta

### Fase 1. Bucle pensado para el local (lo que más se nota)
- **Gestor de contexto** con presupuesto por modelo: las salidas viejas de herramientas se quedan en
  una línea ("leído foo.py, 240 líneas"); al pasar del 70 % se resume el tramo medio con el propio
  modelo y se conservan objetivo, plan y últimos turnos. (Es lo que hace Hermes, "context compression".)
- **Herramientas justas**: solo las del modo y la tarea (repo: 6-8). Las de `sistema.*` solo en modo total.
- **Prefijo estable**: system prompt + memoria + índice de skills congelados al empezar la sesión, para
  que llama-server reutilice la caché y responda antes (Hermes congela la memoria por lo mismo).
- **Muestreo por perfil** en `router.toml` (`temperatura`, `top_p`, `top_k`, `presence_penalty`) con los
  valores recomendados por Qwen; salida de 4096 tokens en pasos con herramientas.
- **Reparar JSON** de llamadas con la librería `json-repair` antes de devolver error.
- Probar en tu PC si el 35B-A3B cabe con 48-64K de contexto (medido con el comparador, no supuesto).

### Fase 2. Que use lo que sabe
- **Skills automáticas** (divulgación progresiva de Hermes): una línea por skill en el prompt
  (nombre + cuándo usarla) y una herramienta `ver_skill` que carga el cuerpo solo si la necesita.
  `/skill` sigue existiendo para forzarla.
- **Mapa del repo** (árbol + firmas de funciones con `ast`/regex, sin LLM, como Aider) en el contexto
  inicial, con tope de tokens.
- **Plan corto** (3-6 pasos) en el primer turno, guardado en la tarea y reinyectado: un modelo pequeño
  se pierde mucho menos así. Sobrevive al reinicio porque va en SQLite.

### Fase 3. Aprender mejor (Hermes, con tu verificador)
- **Aprender de fallos y correcciones**: si corriges a Skynet o el verificador falla y luego pasa,
  propone una nota de memoria o un parche a la skill usada ("la vez anterior falló por X").
- **Parches de skill con versión y vuelta atrás** por tasa de éxito del verificador (la fase 3 que ya
  estaba aprobada en PROPUESTA-AUTOMEJORA).
- **Banco antes/después**: `.\skynet bench` con 10 tareas fijas (las 6 del bench agéntico + 4 nuevas)
  sin aprendizaje y con él, en tu modelo local. Da un número objetivo: "con skills 8/10, sin 6/10".
  Sirve también para medir la fase 1. En la nube no hay GPU, así que la medición real es en tu PC.
- Nunca toca el Core: solo skills y memoria, y siempre con tu OK.

### Aprobar mejoras (discreto)
Backend en este hilo; la interfaz la monta el hilo del rediseño para no pisarnos.
- `GET /api/aprendizaje`: propuestas pendientes con una línea de resumen, de qué tarea salen, si pasó
  el verificador y una vista previa (o diff si es un parche).
- `POST /api/aprendizaje/<id>` con `aprobar | descartar | editar`; aprobar sigue pasando por el gate.
- En la UI: un punto pequeño con el número junto a Configuración; al tocarlo, tarjetas con
  Aprobar / Descartar / Ver. Nada de avisos que interrumpan el chat. También en el móvil.
- Las propuestas caducan a los 14 días para que no se acumulen.

## Qué quitaría
- Mandar todas las herramientas siempre.
- Razonamiento "medio" fijo en charla simple: en Auto, chat corto = bajo, código = medio.
- El tope de 8192 tokens de salida en pasos con herramientas.

## Cloud
Todo esto también ayuda a los modelos en línea; el presupuesto de contexto es por perfil, así que
un cloud con contexto grande casi no recorta.

## Decisiones caras de cambiar
- **Formato de la API de aprendizaje**: es el contrato con la UI y el móvil.
- **Qué se resume y qué no** en el gestor de contexto: define qué recuerda el modelo en tareas largas.

## Cómo se comprueba
Tests en la nube con un modelo simulado (recortes, resumen, JSON roto, skills automáticas) y el banco
antes/después en tu PC con el modelo local. Entrega como siempre: rama en git + zip, sin tocar tu PC.
