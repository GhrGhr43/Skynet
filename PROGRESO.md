# PROGRESO del proyecto Skynet

## Comparación rápida de caché Q8/Q4 (2026-10-12)
- A petición de Daniel, comparación temporal en el mismo Qwen GSQ-RCO IQ3_S, Vulkan, contexto 64K,
  MTP activo, visión CPU, temperatura 0 y semilla 42. Ambas cachés K/V usan el formato probado.
  Calentamiento de 32 tokens por formato; dos textos idénticos y 256 tokens generados por muestra.
- Q8: 14,67 tok/s con texto corto; 13,54 tok/s con 5.244 tokens de código. Lectura del código: 16,48 s;
  petición completa: 35,37 s. Q4: 44,12 y 44,39 tok/s; lectura del código 6,96 s; petición 12,77 s.
  Media de generación: Q8 14,11 frente a Q4 44,26 tok/s (3,14 veces). Dos muestras, sin evaluar calidad.
- Memoria del proceso tras calentamiento: Q8 12,455 GiB dedicados + 1,363 compartidos; Q4 12,353 + 1,201.
  Son contadores del proceso completo, no el tamaño aislado de KV ni una medición de máxima ocupación.
- Un primer intento se interrumpió por lector de contadores de Windows PowerShell incompatible;
  se restauró FP16 y se repitió completo con PowerShell 7. Solo la segunda ejecución aporta resultados.
- FP16/64K/MTP restaurados automáticamente; `data/personalizacion.json` intacto. Sin cambios al código
  de producción. Evidencia y respuestas: `data/pruebas/pi/comparacion-kv/resultado.json`.

## Pi como motor de producción y extras configurables (2026-10-12, D27)
- Diseño autorizado por Daniel. Backup solo local: rama `SKynet-Old-v0.2`, commit `067ea44`.
  Estado personal consistente (SQLite incluido) en `data/backups/old-v0.2-20261012`.
  Rama de trabajo `codex/pi-motor`; no se ha publicado nada a GitHub.
- Producción usa exclusivamente RPC de Pi 1.1.0: herramientas read/bash/edit/write originales,
  prompt nativo, transcript JSONL estable por chat/proyecto y compactación oficial. Sin ContextBuilder,
  GUIDE, historial duplicado, plan obligatorio, verificador externo, checkpoints, propuestas ni scheduler.
  El ejecutor anterior se conserva solo para fixtures guionizadas de regresión, fuera de producción.
- Opciones en `data/personalizacion.json`: harness separado del modelo, herramientas nativas,
  MCP global y por servidor (alta/baja/activación, stdio/HTTP, campos avanzados JSON), skills explícitas,
  modelos compatibles con OpenAI, contexto, MTP y visión CPU/GPU. Pi RPC es el adaptador implementado;
  otros protocolos requieren adaptadores, no funcionan por registrar un nombre de ejecutable.
- MCP oficial de Pi, con `tool_search` y exposición diferida. Apagados no se conectan ni ofrecen esquemas;
  la sesión conserva historial anterior. Se evita descubrir settings/extensiones/MCP de `.pi` externos.
  Internet controla búsqueda y navegador; privacidad alta bloquea ambos. Visión/sistema se seleccionan aparte.
- Memoria opcional, apagada inicialmente: las dos preferencias anteriores se importan pendientes.
  Solo entra memoria aprobada. Cada entrada se aprueba/descarta por ID; sin lotes ni permiso «todas».
  La herramienta solicita aprobación incluso con «Sin preguntar». No genera propuestas de skills.
- Caché KV cuantizada retirada. Modelo real reiniciado con FP16 por defecto, 64K, MTP y proyector CPU.
  Prueba corta de 192 tokens, mismo texto/MTP: 7,41 tok/s con 64K y 19,93 con 32K.
  Una muestra por configuración, no benchmark universal. 64K restaurado; opciones personales intactas.
  Recomendar probar 32K/48K sin cuantización y comparar MTP on/off. Visión CPU configurable/recomendada.
- Hermes retirado de perfiles, interfaz, adaptador y scripts del proyecto; archivos respaldados localmente.
  LiteLLM queda solo como dependencia de desarrollo del ejecutor histórico; Pi llama al proveedor directamente.
  Sin cambios de migraciones SQLite ni modificaciones a agente-godot o PiLocal original del usuario.
- Interfaz web preparada en 8765 y nuevo `Abrir Skynet.cmd`. Fuentes del móvil actualizadas (harness,
  configuración, memoria/MCP); APK instalada pendiente de recompilar. El backend móvil ya ejecuta Pi.
- Validación: suite completa **232 pasan, 1 excluido** (37 avisos de dependencias). Pi + Qwen reales:
  tarea 202, 4 llamadas, 2 archivos Python, 8 comprobaciones correctas. Archivos en
  `C:/Git/PiLocal/proyectos/motor-integrado`; evidencia `data/pruebas/agua/motor-nativo.json`.
- Tests con Pi instalado/proveedor simulado/MCP real: descubrir y ejecutar herramienta, apagar extras,
  preservar conversación y aprobar solo una memoria. Revisión Playwright de configuración a 1440/768/390,
  sin errores JS; mutaciones simuladas para no aprobar memoria real. Se corrigió el refresco que borraba
  cambios aún no guardados. Evidencias UI y velocidad en `data/pruebas/pi`.
- Doctor: Pi, modelo local, SQLite, git y acceso móvil correctos; referencias antiguas a carpetas inexistentes
  `age-of-empires-3d`, `colonia-atlas` y `prueba-pi`. El lanzador de pruebas crea esta última cuando se usa.
- Siguiente: Daniel compara tareas reales en chats nuevos, mismo modelo/razonamiento y extras apagados;
  probar MTP y contexto. No se promete una mejora universal de calidad por adoptar el harness.

## Auditoría del contexto Pi y propuesta de simplificación (2026-10-11)
- Sesiones reales comparadas: Pi consola ofrece read/bash/edit/write (4 herramientas, esquemas ~3.092
  caracteres); tarea 196 integrada ofrece 27 (workspace, sistema/Steam, navegador, visión e internas;
  esquemas ~11.479 caracteres). No son solo diferencias de interfaz o transporte.
- Pi genera reglas específicas al reconocer sus herramientas originales. En integrado esas reglas quedan
  reducidas a brevedad y rutas, más GUIDE propio; se pierden instrucciones de edición agrupada. workspace
  edit_file hace una sustitución por llamada frente al contrato original de Pi con varias ediciones.
- Primera llamada real del agua: 3.086 entrada en consola y 5.139 integrada. Contexto inicial integrado
  3.413 caracteres con objetivo, verificador, memoria/preferencias, catálogo skills y plan solicitado;
  segunda petición 4.974 caracteres suma instrucciones, resumen del paso y PLAN a la sesión Pi ya conservada.
  Once imágenes en historial integrado. No se añade el SYSTEM_CODER completo: PiAgent ignora ese parámetro.
- Propuesta, sin implementar: adoptar Pi oficial como motor; preservar herramientas/contratos originales,
  permisos compatibles en su frontera y cargar extras por tarea. Una autoridad de sesión/compactación;
  evaluación funcional externa por objetivo, sin exigir tests Python estructurales a toda web ni reescritura
  del prompt/bucle por defecto. Comparar batería de tareas y medir éxito/tiempo, no prometer superioridad universal.

## Comparación Pi consola frente a Pi dentro de Skynet (2026-10-11)
- Resultado Pi nativo en `C:/Git/PiLocal/proyectos/prueba/index.html`: sesión 16:22:35.380–16:34:40.039 UTC,
  724,659 s (12 min 5 s), 31 llamadas, 39 herramientas, 680.384 entrada + 25.652 salida.
- Resultado Pi integrado, tarea 196 (no confundir con 195, bucle Skynet): 18:54:50–19:26:12 UTC,
  1.882 s (31 min 22 s), 56 llamadas, 77 herramientas, 1.673.474 entrada + 38.108 salida. Dos bloques.
  13 comprobaciones de navegador, plan y verificador Python con siete tests básicos de estructura/sintaxis.
- Comprobación externa con misma versión Three.js, navegador y viewport: ambos cargan sin errores, clic,
  reinicio, toque sintético y resize 390/768/1440. Las superficies del agua se renderizan en ambos resultados.
  Ambos pierden el rastro del cursor si los eventos tienen desplazamientos pequeños: actualizan la referencia
  de movimiento aunque no alcancen el umbral. Pi nativo no acota la amplitud tras clics repetidos; integrado
  limita a 32 ondas, pero omite el factor de decaimiento temporal en la altura y su derivada analítica es inexacta.
- Valoración visual de las capturas: ondas más suaves en Pi nativo; integrado muestra crestas más picudas.
  Comparación concreta, sin afirmar superioridad general. Entornos no idénticos: integrado reutiliza carpeta
  con restos del intento 195 y herramientas/verificación distintas. No es una medida aislada del coste del puente.
- Evidencias: `data/pruebas/agua/tiempos.json` y `comparacion-pi/resultado.json`, capturas y copias de originales.
  No se modificaron los HTML ni configuración/runtime de los agentes. Las pruebas usan instrumentación efímera
  solo en respuestas del navegador y una dependencia pública servida desde caché controlada para ambos.

## Comparación del agua: diagnóstico de tarea 195 (2026-10-11)
- Coder con bucle Skynet y modelo local; repo `pi-smoke` (verificador Python, no específico para esta web).
  Dos bloques de 30 turnos; 973.884 tokens de entrada acumulados y 25.665 de salida. No son un solo contexto.
  Primer bloque creó `index.html`; el segundo solo modificó auxiliares en `.skynet/`, sin avance del HTML.
- El navegador aislado bloqueó el CDN de Three.js. El agente gastó llamadas creando copias alternativas
  locales/incrustadas y no llegó a corregir el HTML original. No es un diagnóstico de Coder apagado o falta de RAM.
- Comprobación externa sin modificar originales: CDN satisfecho con la copia exacta de Three.js ya descargada.
  Skynet tiene error de compilación GLSL: `vUv` usada pero no declarada en fragment shader; agua no renderizada.
  Pi independiente carga sin errores, responde al clic, reinicia alturas a cero y no desborda a 390 px.
  No se ha hecho una evaluación exhaustiva de todos los requisitos de ambos resultados.
- Evidencias y capturas en `data/pruebas/agua/`; sin cambios de runtime, permisos ni archivos de los resultados.
  Propuesta: revisión de dependencias públicas mediante caché controlada para el navegador aislado y errores
  accionables, verificador de WebGL/interacciones y repetición de la comparación; diseño pendiente de aprobación.

## Diagnóstico de conversación y contrato del agente (2026-10-11, diseño pendiente)
- Informe: `reports/Diagnóstico del agente Skynet.md`; notas en `research_notes/Diagnóstico del agente Skynet/`.
- Sesión 32, tareas 180–185: tras Detener, el historial excluye el trabajo sin respuesta final; primera llamada
  posterior con 3.289 tokens de entrada. No se demuestra agotamiento de 64K ni falta de memoria gráfica.
- Repo elegido `ecosistema-simulador` registrado en el chat, pero esas tareas tienen repo NULL:
  Coder apagado oculta identidad; crear_proyecto no vincula tarea. Falta reloj vivo en el contexto auditado.
- Propuesta P0: identidad proyecto/sesión durable, transcript y checkpoint de interrupción, reanudación por chat
  y fecha/hora/zona por turno. P1: calidad comprobada, permisos efectivos y protección de cambios simultáneos.
  P2: comparar loop propio y adaptador Pi existente con la misma aceptación; sin migración total por intuición.
- Al investigar había desfase entre Pi implementado y documentación; D26 se actualizó por otro trabajo durante
  la auditoría. Este diagnóstico no hizo esa integración ni sus pruebas ni modificó los cambios preexistentes.
- Comprobaciones de auditoría: Store/Verifier/Memoria 14 pasan y 1 excluido; suite completa y doctor inconclusos
  por temporales del entorno/esperas sin resultado final. No se da el estado actual por aprobado con ese subconjunto.
- Solo notas/informe/progreso; sin cambios de runtime, configuración, SQLite ni proyectos externos.
  Siguiente paso: acordar con Daniel el diseño del contrato P0 y sus pruebas antes de implementar algo grande.

Última actualización: 2026-10-11 (Pi oficial como alternativa Coder, D26).

## Pi preparado para pruebas con el modelo local (2026-10-11, D26)
- Instalado Pi 1.1.0 (`@earendil-works/pi-coding-agent`) en `herramientas/pi`, sin instalación global.
  Integración por RPC y extensión oficiales: Pi lleva el bucle; las herramientas pasan por MCP y el gate
  de Skynet. Herramientas propias de Pi desactivadas para conservar los permisos y la auditoría.
- Mismo endpoint llama.cpp, pesos Qwen locales, visión y contexto 64K; configuración en `data/pi/agent`.
  Pi llama directamente al endpoint. LiteLLM se conserva para el motor habitual de Skynet.
  Sesiones Pi en `data/pi/sessions`, vinculadas al ID de tarea; capabilities JSON recuerda el motor sin migración.
- Selector web `+ > Agente para programar > Pi/Skynet`; terminal `/coder pi` y `/coder skynet`.
  `Probar Pi.cmd` reutiliza/enciende el modelo y la web, elige repo `prueba-pi` y abre el navegador.
  Disponible para Coder local con repo; el arranque habitual sigue usando Skynet. APK sin cambios.
- Pruebas reales sin corregir manualmente el código generado: tarea 186, función Python y ocho tests;
  tarea 187, contador HTML con persistencia, botones y revisión de captura. Ambas HECHAS.
  Resultado visible en `proyectos/prueba-pi/index.html`; evidencias en `data/pruebas/pi/`.
  Comprobación independiente de botones, recarga, tres anchos y selector Pi/Skynet: todo OK, sin errores JS.
- Batería completa: 227 pasan, 1 omitido; tras los últimos ajustes, 21 tests Pi/web pasan.
  Incluye permisos reales, autenticación del puente, cancelación, imágenes y plan pendiente.
  Doctor conserva el aviso previo por el repo inexistente `age-of-empires-3d`; modelo/MCP disponibles.
  Falta una comparación de rendimiento y calidad con Skynet en tareas equivalentes; no se afirma superioridad.

## Estudio previo de Pi como motor agéntico (2026-10-11)
- Revisados código actual de Skynet y documentación oficial actual de Pi (repo redirige a earendil-works/pi).
  Pi permite SDK TypeScript, RPC y MCP; no incorpora los modos de permisos de Skynet.
- Tokenizador del Qwen local: plantilla SYSTEM_CHAT 112 tokens, SYSTEM_CODER 340 y SMALL_CALLS 109;
  no son el prompt completo: faltan sustituciones, memoria, herramientas, contexto e historial.
  Tarea 179: primera llamada 5.250 tokens de entrada; máximo 38.900, media 17.616 en 278 llamadas.
- Recomendación aceptada e implementada arriba: probar Pi integrado por RPC como alternativa Coder, conservando
  interfaz, tareas, verificador y permisos de Skynet; un único bucle agéntico por ejecución. Comparar
  mismas tareas/modelo/ajustes, caché fría y caliente, éxito sin intervención y tiempo total.
  LiteLLM sigue siendo el SDK del router habitual.

## Peticiones grandes sin repetir «continúa» (2026-10-11, D23)
- Implementada recuperación acotada de respuestas cortadas, JSON inválido y cortes de conexión: no ejecuta
  ni conserva llamadas incompletas en el historial. JSON reparable se normaliza antes de conservarlo.
- Coder pide construir esqueleto y ampliar con pequeñas ediciones. Plan en `.skynet/tarea-N/PLAN.md`, leído
  al reanudar; las casillas pendientes impiden aceptar un cierre prematuro del modelo.
  Tras cinco lecturas seguidas se orienta al siguiente cambio concreto, sin bloquear lecturas necesarias.
  Lecturas/verificador se pueden repetir después de editar; sin cambios sigue la protección contra bucles.
- Hasta cuatro bloques adicionales si agotó turnos y modificó código; dos reparaciones de verificador.
  Cada paso queda guardado, Detener conserva los archivos, consumo acumulado entre bloques. Configurable.
- Verificación también en repos sin Git cuando hubo escritura. Sin migración SQLite.
- Nuevo MCP `navegador.comprobar_html`: Chrome aislado, HTML del repo, sin red/perfil personal; acciones,
  errores JS, desbordamiento y captura opcional. Probado por MCP real, incluidas imágenes y errores.
  Las capturas de páginas con errores también llegan al modelo; identifica los elementos que desbordan.
- Batería final: 220 tests pasan y 1 omitido; sintaxis JS de web/móvil/navegador comprobada.
  Doctor: modelo y MCP OK; registro local antiguo `age-of-empires-3d` apunta a una carpeta inexistente.
- Capacidad práctica con el modelo real: Gini (20 comprobaciones, 43,5 s) y cruce de órdenes
  (31 comprobaciones, 90,6 s), ambos hechos con verificador externo fuera del repo. No equivalen a un IQ.
- Simulador original construido por el propio modelo, HTML de ~37 KB, controles y cuatro canvas;
  corrigió desbordamiento móvil y lógica económica. Verificador reforzado pasa: conserva dinero/recurso,
  órdenes repetidas comparten saldo/inventario, ignora agentes eliminados, extinción y 1200 pasos.
  Pruebas y archivos aislados en `data/pruebas/incremental/`; no se modifica el repo personal `prueba`.

## Velocidad del chat en vivo (2026-10-11, D24)
- Web y fuentes del móvil actualizan cada segundo con diferencias del contador nativo `/slots` de llama.cpp.
  Incluye razonamiento/argumentos y tareas largas; cero sin generación o conexión, sin retener la media.
  La media histórica queda solo en el pie. Motor incompatible muestra cero; eventos sin persistencia SQLite.
- Contraste con generación real: muestras entre ~15 y 28 tok/s en el primer ensayo; tarea larga en la web
  activa entre ~24 y 33 tok/s en ocho muestras, sin estimar caracteres.
  Chrome verifica reposo, cambios, que usage no sobrescriba la velocidad, silencio, desconexión y Detener.
- APK aún pendiente de recompilar. Servidor activo actualizado en reposo, sesión 30 y opciones restauradas;
  modelo continuó encendido. Medidor en la versión activa verificado con Chrome.

## Prueba de una hora con una petición (2026-10-11, terminada, D25)
- Daniel pide una web compleja con al menos una hora de trabajo, guardada en el PC, y apagar al terminar.
- Tarea 179: Colonia Atlas, ocho pantallas, mapa, construcciones, población, tecnología, misiones, mercado,
  persistencia y análisis. Única petición en `data/pruebas/hora/prompt.txt`; proyecto en `proyectos/colonia-atlas`.
- Terminada como HECHA a las 09:27:44: 5.019,71 segundos de trabajo medido (83,66 minutos), 12 iteraciones.
  El modelo local escribió y corrigió el HTML; Codex reparó Skynet y mantuvo el verificador externo.
  Mismo objetivo inicial en todas las reanudaciones, sin añadir peticiones humanas al proyecto.
  Comprobación independiente final: 120 casos pasan, cero fallan. Capturas finales de escritorio/móvil
  revisadas, sin errores JS ni desbordamiento. Resultado y pruebas en `data/pruebas/hora/`.
  Para verla después del apagado: doble clic en `proyectos/colonia-atlas/index.html`, sin Internet.
- Verificador externo progresivo ampliado de 57 a 120 casos: lógica, botones reales, restauración,
  investigación/misiones y las ocho pantallas a 390/768/1440 px. El modelo no puede cambiar los tests.
  Al ampliar se reanuda la misma tarea para tomar una nueva referencia; conserva objetivo y tiempo acumulado.
  Bloques de tarea larga ampliados a 40 turnos: con 20 el diagnóstico consumía casi todo el bloque
  y provocaba volver a leer el contexto. Límites de tiempo/errores y verificaciones siguen activos.
- Duración mínima explícita en capabilities JSON, sin migración: `min_trabajo_seg`, `trabajo_seg` acumulado.
  Cuenta llamadas al modelo y verificación, no pausas entre pasos; no puede cerrar antes del mínimo.
  Herramienta interna `tarea_larga` acepta `minutos_minimos` solo cuando Daniel lo pide. El tiempo máximo
  sigue siendo independiente. En una iteración larga el plan puede tener pendientes; cerrar toda la tarea
  sigue requiriendo el marcador de final y verificador en verde.

## Diagnóstico del simulador de ecosistema (2026-10-11)
- Revisadas las tareas 169, 170 y 171: la escritura del HTML agotó los 8.192 tokens de salida
  (`finish_reason = length`), dejó argumentos JSON incompletos y no llegó a ejecutar write_file.
  La tarea 171 tenía Coder activado; ese modo tampoco evitó la escritura completa en una llamada.
- El agente conservaba la llamada incompleta en el historial y pedía repetirla; la recuperación terminaba
  con HTTP 500 del motor al parsear argumentos. Faltaba manejo específico de salida agotada.
  El registro de la tarea 171 no muestra agotamiento del contexto de 64K ni error de memoria.
- Corrección implementada en D23: descartar llamadas truncadas antes de incorporarlas al historial,
  recuperación acotada y construcción por pequeñas ediciones con comprobaciones intermedias.
- El repo local `prueba` está vacío, sin Git ni verificador configurado. Para una aplicación HTML,
  la validación debe comprobar JavaScript y funcionamiento en navegador.

## Visión local, adjuntos y comprobación visual (2026-10-10, D22)
- Descargado y verificado el mmproj del repo GSQ-RCO (931 MB). Motor IQ3_S con MTP y 64K reconoce
  correctamente una imagen sintética; `/props` confirma visión. Archivo antiguo conservado (otra huella).
- Proyector en CPU (`vision_gpu = false`): en la comparación de respuestas de 128 tokens, ~23–33 tok/s
  frente a ~13 con visión en GPU; una imagen nueva de 800×500 tardó 6,28 s con 428 tokens de entrada.
  GPU a 64K llegó a ~16,4 GB de memoria dedicada total y ~1,6 GB compartida. Medidas puntuales, no universales.
- Web y `movil/www`: **+ > Adjuntar imágenes**, pegar o arrastrar, miniaturas, hasta 4 imágenes/5 MB,
  PNG/JPEG/WebP, resolución limitada a 1280 px y sin metadatos. Historial y Reintentar conservan referencias;
  archivos en data/imagenes, sin cambiar el esquema SQLite. Lectura remota con llave de dispositivo.
- MCP `vision`: mirar imágenes del repo y capturar ventana activa/por título o escritorio. Solo bucle local;
  capturas con Ver mi PC o más, nunca en tareas largas. Herramientas ofrecidas en Coder/peticiones visuales,
  con instrucciones para comprobar juegos/interfaces tras cambios y junto con tests/errores.
- Verificado: 185 tests pasan, 1 omitido (integración optativa), doctor OK; MCP → LiteLLM → modelo real
  identificó cuadrado rojo y círculo azul (1 herramienta, 1.726 tokens, 14,33 s del modelo en 2 llamadas).
  Interfaz: adjuntar, enviar, recuperar historial tras recargar y 390 px, sin errores JS ni desbordamiento.
- Pendiente: comprobar capturas con un juego real (pueden fallar ventanas minimizadas/protegidas), recompilar
  APK y decidir si las tareas largas deben poder capturar una ventana autorizada; hoy conservan Solo repo.

## Todo hablando y Control total sin preguntas de más (2026-10-10 noche, D21)
- Se pide hablando: crear proyectos, tareas largas (en minutos), cargar skills, buscar archivos de todo el PC (índice de
  nombres de C:, 1 ms) y desinstalar juegos de Steam sin clics; programas con winget. `/largo` y su pestaña, fuera.
- Control total pregunta solo lo delicado (cambiar sistema, borrar, administrador, secretos); el diálogo enseña el
  comando entero. Sin modo automático de modelos. `memoria/SKYNET.md` + AGENTS.md/CLAUDE.md del repo en el contexto.
- Web: Uso y Estado; pie con tokens, tok/s, estado y Reintentar; cursores nuevos; arreglado el salto de scroll en
  Configuración. Móvil (`movil/www`) con lo mismo y solo el modelo local; **falta compilar la APK en la nube**.
- Limpieza: fuera `herramientas/comparador` y tres propuestas ya hechas; data/ sin restos (a la Papelera).
- Probado con el modelo real: busca PEAK.exe en 9 s, guarda una preferencia en 4 s, llama a crear_proyecto
  directamente con su confirmación. Tests: 177 (todos pasan).
- Siguiente: probar en el PC desinstalar e instalar un juego pequeño de Steam y un programa con winget; propuestas
  para el móvil (correo, Drive, aprobar permisos) pendientes de que Daniel elija.

## Skynet contra Hermes y motores locales (2026-10-10)
- Informe: docs/COMPARATIVA-HERMES.md. Herramienta: `herramientas/bench-hermes/` (Hermes entero en Docker).
- Mismo modelo: calidad empatada en tareas de código; Skynet ~6-7 veces más rápido; Hermes gana en memoria
  entre sesiones (Skynet no deja al modelo escribir memoria).
- Motor elegido: Qwen3.8-27B GSQ-RCO IQ3_S (ISTA-DASLab, con MTP), 64K, caché q4: mismos aciertos y el más
  rápido. Descargado en `.lmstudio/models/ISTA-DASLab/`. El 35B-A3B a 64K va a 31 tok/s.
- Hermes instalado en `C:\Users\HACHO\.hermes` (fuera de AppData: la app de Claude virtualiza AppData) e
  imagen `skynet-bench/hermes` en Docker. Strata y el 27B Q4_K_M borrados por Daniel.
- OpenCode (3 tareas): 3/3, cerca de Skynet en las cortas y 5 veces más lento en planificador.
- **Opción A hecha (D19):** cerebros `local` (bucle de Skynet), `hermes` y `hermes-nube`; Gemini, OmniRoute y
  Anthropic fuera de la config (siguen como perfiles de prueba en tests/conftest.py). Motor `hermes` en Docker
  (`skynet_tools/hermes_motor.py`, imagen `skynet/hermes`), selector de la web con Local / Hermes / Nube.
  Tests con LLM guionizado; **falta probar en este PC** encender el motor hermes y chatear con él.
- Ojo: Docker Desktop hay que abrirlo desde Windows, no desde la app de Claude (virtualiza AppData y rompe
  su `engine.sock`).
- **Memoria automática (D20):** herramienta interna `memoria` (guardar, reemplazar, quitar en memoria/USER.md
  y MEMORY.md), sin preguntar, auditada, fuera de tareas largas. Probada con el modelo real: prueba de memoria
  OK en 27 s (Hermes 144 s).
- **Motor local por defecto:** GSQ-RCO IQ3_S con MTP, 64K, caché q4 (skynet.toml, modelos_locales y la
  selección de Ajustes). Comprobado en este PC: arranca con n_ctx 65536 y MTP.
- gpt-oss-20b probado y descartado: 3/10 y errores de formato harmony en llama-server (COMPARATIVA).
- Strata fuera del código (motor, carpeta de modelos y `razonamiento_por_tokens`). `vendor\omniroute` enviado a
  la Papelera (2,2 GB; Daniel la vacía). Queda `data\omniroute`.
- Móvil: `movil/www` con el selector Local / Hermes / Nube y versión 0.4 en el manifiesto. **Falta compilar la
  APK** donde estén las herramientas de Android y la clave de firma (no está en el repo).
- Siguiente: probar en este PC el motor hermes de punta a punta (necesita Docker abierto), compilar la APK 0.4
  y arreglar `tests/test_steam.py` (falla con «Edición» en Windows).

## Conversación primero y Coder aparte (2026-10-09, D17)
- Daniel: el modo por defecto debe ser rápido y listo como OpenClaw; lo pesado, en interruptores como Internet.
- Mensaje normal = turno de conversación con el historial real de la sesión, memoria/skills en el system prompt,
  sin contexto de repo ni verificador; razonamiento Auto bajo. «hola»: de ~3.000 a ~125 tokens (750 en
  «Ver y editar»).
- Coder (`/coder on|off`, `coder` en /api/ajustes y snapshot) recupera el modo programador sobre el repo.
  La UI del interruptor está en el PR #3 (caja de texto nueva).
- Siguiente: MCP vivos por sesión, aprendizaje estilo Hermes (herramientas de memoria y skills + repaso).

## Local más listo, fase 1 (2026-10-09)
- Propuesta aprobada por Daniel (ya cumplida; el documento se retiró). Fase 1 hecha en la nube (D16): ventana de
  contexto que recorta y resume (`ventana.py`), llamadas rotas reparadas (`llamadas.py`), herramientas de
  `sistema` según el modo y muestreo de Qwen en el perfil local.
- Verificado en la nube con LLM guionizado: 147 tests pasan (falla solo el de rutas de Windows en Linux).
  Falta medir en este PC con `bench\agentico.py -m local` antes y después.
- Siguiente: fase 2 (skills que el modelo carga solo, mapa del repo, plan corto) y fase 3 (aprender de
  fallos y correcciones). La UI y la API de aprobar propuestas las hace el rediseño (/api/aprendizaje):
  mantener compatibles `propuestas.list_proposals/approve/reject`.
## Rediseño web y sesiones (2026-10-09, PR #2)
- Barra lateral con sesiones al estilo Claude/Codex: nueva (Ctrl+Mayús+O), buscar, renombrar,
  borrar (archiva; tareas y registro se conservan). Ctrl+B la oculta. Tablas propias en
  `skynet/sesiones.py` (`CREATE TABLE IF NOT EXISTS`, sin migración del Store).
- El modelo recibe el hilo de la sesión abierta (`WebCoordinator._recent`), también tras reiniciar.
- Chat centrado, inicio con el compositor en medio, nebulosa atenuada al leer, panel a la derecha.
- Medidor de tokens: anillo en el compositor (contexto usado / ventana del modelo) con detalle
  de sesión y mes; sugiere sesión nueva cuando el contexto pesa. `agent.py` emite `usage`.
- Lo aprendido: punto con número junto a Configuración; tarjetas Aprobar/Descartar/Ver sobre
  `/api/aprendizaje`. Aprobar pasa por el gate como `/aprobar`.
- Verificado en la nube: 140 tests (el de `C:/Windows/system.ini` solo pasa en Windows) y capturas
  con Playwright. Falta probar en el PC de Daniel. El APK lleva su copia de la UI: no verá sesiones
  hasta recompilarlo.

## Búsqueda en internet (2026-10-09)
- Pedida por Daniel. Globo junto al chat, con estado resaltado y solo icono en móvil;
  `/internet on|off` en terminal. Apagada al arrancar. No carga herramientas ni servidor web
  cuando está apagada; activada añade solo búsqueda y lectura de páginas públicas (D15).
- MCP `internet` sobre DDGS 9.16 y httpx, instalado en `.venv`. Resultados breves con enlaces,
  sin navegador, claves API ni JavaScript. El modelo busca cuando necesita datos, no en cada turno.
- Privacidad alta (también por repo) y tareas largas bloquean estas herramientas. El gate exige
  activación explícita. Lectura excluye URLs locales, credenciales, archivos y redirecciones privadas.
  Al continuar una tarea se respeta el interruptor actual.
- Verificado en este PC: 119 tests pasan, 1 omitido (LM Studio optativo); doctor OK (cloud sin
  clave figura desactivado). Modelo local real: buscó The Farmer Was Replaced y devolvió AppID
  2060160 con enlace oficial. 47,63 s total con razonamiento; una búsqueda directa tardó 1,71 s.
  UI comprobada en escritorio y 390 px: sin desbordamiento; botón enciende y apaga la búsqueda.
- Seguimiento: cursor nativo de flecha, mano y texto en blanco/azul, sin JS ni animaciones.
  Tras el aviso de Daniel en Edge, se versionaron los módulos/CSS y se fuerza su revalidación;
  el botón muestra «Internet activo» y un aviso de confirmación. Probado activar/desactivar en
  el navegador integrado y 58 tests de web/permisos. La pestaña real de Edge no está conectada
  a las herramientas; falta que Daniel confirme ahí tras recargar la página.
- Límites: buscadores externos pueden bloquear o limitar consultas; los datos enviados salen del
  PC. Activado hay coste de contexto, arranque MCP y red. No se han añadido MCP de navegador.

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

## Motor local (2026-10-08)
Único motor local: Qwen3.8-27B UD-IQ3_XXS en llama-server (Vulkan de LM Studio, FA, KV q8_0,
32K, MTP), elegido con el benchmark de `bench/` (ver D12). Se enciende y apaga en Ajustes
(`skynet/engines.py`, `[motores.local]`); carga en ~30 s. Strata y el 27B Q4_K_M ya no son
opciones (los modelos siguen en disco). Probado: doctor OK y `pytest -m lmstudio` pasa en 15 s
(~52 tok/s, aceptación MTP 68–86 %). El código del tipo `strata` sigue en engines.py, sin usar.

## OmniRoute (2026-10-08)
Pasarela cloud opcional (D13): motor `omniroute` (tipo `proceso`, no usa GPU) en Ajustes y perfil
`omniroute` (no privado). Instalado en `vendor/omniroute`; escucha solo en 127.0.0.1. Probado:
arranca y se apaga desde Skynet (~7–50 s), doctor lo ve, el router le llega. **Falta:** que
Daniel elija proveedores (claves API oficiales) y crear el combo "skynet" con ellos
(`omniroute combo create skynet --model <proveedor/modelo>` o en el panel http://127.0.0.1:20128).
Hasta entonces las llamadas fallan en local sin salir del PC.

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

## Modos de permisos y nube (2026-10-08, D14)
- Cuatro modos por modelo (Solo repo, Ver mi PC, Ver y editar, Control total) y herramienta
  `sistema` para todo el PC. Admin, sistema, borrar y secretos se preguntan siempre.
- Al arrancar solo el modelo local; la nube se activa con confirmación y un modo fuerte en la
  nube avisa. Probado en la nube (tests + Chromium headless); falta probar en el PC real.

## Lecciones ya incorporadas
- El agente local editaba `PROGRESO.md` por su cuenta: ahora el gate lo protege en tareas largas.
- «Todos los tests en verde» como único criterio impedía avanzar por pasos: ahora una
  iteración se acepta si no empeora (ver D8 en docs/DECISIONES.md).
- Un runner muerto parecía vivo hasta 3 minutos: ahora se comprueba también su pid.

## Acceso desde el móvil (2026-10-08)
- App Android Skynet 0.2 + llaves por dispositivo + Tailscale Serve. Guía: `docs/ACCESO-MOVIL.md`.
  Configuración › Dispositivos enseña el QR; el Diagnóstico revisa Tailscale (y avisa si Funnel está activo).
- 2026-10-09: app 0.3 con la interfaz actual de la web (sesiones, menú «+» con Internet y Modo coder,
  tok/s, selector de modelo local, aprendizaje). `movil/www` es una copia: al cambiar la web hay que
  pasar los cambios ahí y generar otro APK (misma firma).

## Siguientes pasos propuestos
1. Daniel: elegir presupuesto cloud y poner la clave si quiere usarlo.
2. Añadir sus repos reales a `config/repos.toml` (y un juego de agente-godot con `agente = "agente-godot"`)
   y probar `/largo` con agente-godot (no probado aún con un juego real para no gastar GPU sin permiso).
3. Escalado automático local → cloud cuando el local falle N veces la misma iteración (el router
   ya lo permite con `reasoning = "alto"`; falta la regla en el Scheduler).
4. Servidores MCP de terceros (p. ej. serena) declarados en `config/skynet.toml`.
5. Separar en agente-godot lo genérico de lo específico de Godot (propuesta para su
   `MEJORAS-HERRAMIENTA.md`, sin tocarlo sin OK).
