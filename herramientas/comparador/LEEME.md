# Comparador de modelos locales

Compara los modelos que tienes en LM Studio (y otros servidores con API OpenAI) pasando la misma
batería de pruebas, y te da un perfil por capacidades en un informe HTML.

## Uso
1. Apaga el motor local de Skynet y descarga los modelos de LM Studio (la GPU tiene que estar libre).
   No hace falta abrir LM Studio: el comparador encuentra todos los GGUF de `.lmstudio\models` y de
   `C:\Strata\Strata-data\models` y los arranca uno a uno con el llama-server Vulkan que trae LM Studio.
2. Doble clic en `comparar.cmd` (menú para elegir modelos, modo rápido), o en una terminal:
   - `python -m comparador listar`
   - `python -m comparador ejecutar -m modeloA,modeloB --modo completo`
   - `python -m comparador ejecutar --modo especialidad --categorias autonomo,herramientas -n 3`
3. El informe se abre solo (`resultados\*.html`; los datos en `.json`).

Ajustes con los que arranca cada modelo (los del benchmark de Skynet, sin tocar voltajes ni relojes):
Flash Attention, KV cache q8_0, 32K de contexto; MTP en los Qwen densos (si el GGUF no lo trae, reintenta
sin él); expertos en la RAM en los MoE (`--n-cpu-moe`); y si hay un `mmproj-*.gguf` en la carpeta del
modelo, se carga y el modelo puede ver imágenes. El informe guarda los flags usados y el tiempo de arranque.

**Qwen3.8 Flash Next (Strata) sin Strata:** experimental. Son 58 GB y tu PC tiene 48 entre VRAM y RAM, así
que una parte se lee del disco: irá lento, y si el llama.cpp de LM Studio no reconoce su cuantización
(GSQ-RCO) saldrá «no arrancó» con el error en `resultados\logs`.

Si el servidor de LM Studio está encendido, sus modelos también salen (con el prefijo `lmstudio:`).

Solo usa la librería estándar de Python (3.12+). Las pruebas de código ejecutan lo que escribe el
modelo dentro de carpetas temporales; el agente solo puede lanzar `python`/`pytest`.

## Qué mide (29 pruebas, 13 capacidades)
| Capacidad | Pruebas | Cómo se puntúa |
|---|---|---|
| Programador asistente | función con casos límite, algoritmo de agenda, escribir tests, revisar código | tests ocultos; los tests del modelo deben pillar una versión con fallo |
| Programador autónomo | 6 tareas de varios pasos en un repo (bug en 2 módulos, refactor, CLI, logs, caché desde especificación, algoritmo que se cuelga) | mismo bucle y herramientas para todos; tests ocultos al final |
| Depuración | arreglar con traza y segundo intento, bucle infinito | tests; acertar al 2.º intento vale 0,7 |
| Uso de herramientas | elegir herramienta y argumentos, fecha relativa, preguntar si falta un dato, encadenar con el resultado | llamadas correctas y no inventar |
| Instrucciones | JSON con restricciones, formato con varias reglas | condiciones cumplidas |
| Razonamiento | 4 problemas de lógica y cálculo | respuesta exacta |
| Contexto largo | dato en ~4K, datos cruzados en ~16K y ~28K tokens | respuesta correcta |
| Fiabilidad | dato ausente, premisa falsa, instrucciones metidas en un documento | no inventa, no obedece al documento |
| Español | traducción técnica, correcciones sucesivas | términos y restricciones |
| Imágenes | contar y ubicar formas | JSON exacto; «no compatible» si el modelo no admite imágenes |
| Rendimiento | primer token, tok/s corto y con 8K, prefill, VRAM | medido (VRAM con el contador de Windows) |
| Generación de imágenes | — | «no compatible»: necesita un modelo de difusión |
| Control del PC | — | «no probado»: necesita una máquina virtual restaurable |

Modo rápido: 13 pruebas (una o dos por capacidad). Completo: todas. Especialidad: las categorías que elijas.
`-n` repite cada prueba y el informe muestra el rango.

## Antes de construirlo
Herramientas que ya existen y por qué no bastan solas: promptfoo (bueno para prompts, sin bucle
agéntico con verificador), Inspect AI (potente, pero hay que montar todo a mano), OpenCompass y
lm-evaluation-harness (benchmarks académicos en inglés, pesados en Windows). Esto reutiliza las
tareas agénticas de Skynet (`bench\agentico_tareas.py`) y deja sitio para enchufar esos motores.

## Probarlo sin GPU
`python tests\servidor_simulado.py` arranca un servidor falso en el 1234 con un modelo `listo` y otro
`tonto`; `python -m pytest -q tests` comprueba que el primero saca 100 % y el segundo casi 0.
