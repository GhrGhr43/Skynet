# Skynet contra Hermes con el modelo local (2026-10-10)

Pregunta: ¿sirve algo de Skynet aparte de la interfaz, o es mejor usar Hermes como cerebro?
Y de paso: ¿qué motor local va mejor en este PC (RX 9070 XT 16 GB, 32 GB DDR5, 7800X3D)?

## Cómo se midió
- Herramienta: `herramientas/bench-hermes/comparar.py`. Mismo llama-server (64K, un slot, muestreo de Qwen
  por defecto en el servidor), mismas tareas, verificador oculto sin LLM. Tokens medidos en llama-server
  (`/metrics`), igual para los dos agentes.
- Skynet: su bucle actual (modo Coder sobre el repo; Internet activado en la tarea que lo pide).
- Hermes v0.21.6 tal cual, entero en Linux dentro de Docker (`docker/Dockerfile`: imagen oficial + ddgs,
  navegador y pytest). En Windows nativo sus herramientas de archivos traducen mal las rutas relativas con
  el backend Docker; en Linux es su plataforma recomendada. Perfil y memoria nuevos en cada tarea.
- Una ejecución por tarea: muestra pequeña, sirve para ver tendencias grandes, no diferencias de un acierto.

## Tareas
- Banco agéntico (7): factura, planificador, renombrar, cli_json, logs, cache_ttl (código con tests ocultos)
  y appids (buscar en Internet y citar fuentes).
- Calidad (5, `tareas_calidad.py`): regresión con git (hallar el commit culpable), optimizar sin cambiar el
  comportamiento (con trampa: elementos no hasheables y orden), cambio coherente en 4 archivos, CLI desde
  cero contra especificación, y memoria entre dos sesiones.

## Resultados

### Agentes (mismo modelo)
| | Skynet | Hermes |
|---|---|---|
| Banco agéntico, 27B UD-IQ3_XXS | 6/7 (*) | 7/7 |
| Calidad, GSQ-RCO IQ3_S | 4/5 (falla memoria) | 5/5 |
| Tiempo medio por tarea | ~51 s | ~355 s |
| Llamadas a herramientas por tarea | ~10 | ~25 |
| Tokens generados por tarea | ~2.100 | ~9.800 |

(*) «renombrar»: Skynet hace el cambio bien pero deja en el README una nota sobre el alias obsoleto y el test
oculto exige que el nombre viejo no aparezca. Es un test demasiado estricto, no un fallo real.

- **Calidad en tareas cerradas: empate.** Hermes escribe más tests y verifica más.
- **Velocidad: Skynet ~6-7 veces más rápido** con el modelo local. Hermes manda ~13K tokens de prompt base,
  hace más del doble de llamadas, razona mucho más y suma ~25 % de tiempo fuera del modelo (Docker).
- **Memoria: Hermes gana.** Guardó la preferencia en `USER.md` por su cuenta y la aplicó en una sesión nueva.
  Skynet no tiene forma de que el modelo escriba memoria (solo propuestas tras tareas verificadas largas).

### Motores (Skynet, banco agéntico, 64K)
| Motor | Aciertos | Tiempo total | Generación |
|---|---|---|---|
| Qwen3.8-27B UD-IQ3_XXS, caché q4 | 6/7 (*) | 7,0 min | — |
| Qwen3.8-27B UD-IQ3_XXS, caché q8 | 6/7 (*) | 6,0 min | 58 tok/s |
| Qwen3.8-27B GSQ-RCO IQ3_XXS, caché q4 | 7/7 | 7,8 min | 58 tok/s |
| **Qwen3.8-27B GSQ-RCO IQ3_S, caché q4** | 6/7 (*) | **5,2 min** | 55 tok/s |
| Qwen3.6-35B-A3B Q4_K_M | 7/7 | 11,0 min | 31 tok/s |

- Empate en aciertos; el GSQ-RCO IQ3_S es el más rápido de punta a punta (llega con menos tokens) y cabe
  entero con 64K, caché q4 y MTP. El 35B-A3B a 64K se hunde (expertos en RAM). Caché q8 frente a q4: igual.
- Elegido: **GSQ-RCO IQ3_S, 64K, caché q4, MTP**.

### gpt-oss-20b (MXFP4, 64K, muestreo de OpenAI: temperatura 1.0, top_p 1.0)
Recomendado por muchas guías para 16 GB. Con Skynet, 10 tareas antes de pararlo: **3/10** (factura,
planificador y regresión). Tres veces llama-server no pudo leer su respuesta al llamar a herramientas
(«does not match the expected peg-native format», el formato harmony de gpt-oss) y la tarea se cortó;
además escribió un JSON inválido en appids, cayó en la trampa de restricciones y falló logs y cache_ttl.
Donde acierta tampoco es más rápido: planificador 205 s (27K tokens generados) frente a 83 s. Descartado.

### OpenCode (3 tareas, GSQ-RCO IQ3_S)
OpenCode 1.18.35 en Docker (`docker-opencode/Dockerfile`), con el MCP `internet` de Skynet como buscador.
Las tres tareas en las que Skynet más tardó con este motor:

| Tarea | Skynet | OpenCode | Hermes |
|---|---|---|---|
| planificador | OK, 83 s | OK, 427 s | OK, 591 s (27B UD) |
| proyecto | OK, 73 s | OK, 93 s | OK, 294 s |
| appids (Internet) | OK, 56 s | OK, 61 s | OK, 105 s (27B UD) |

OpenCode acierta las tres y va cerca de Skynet en las cortas, pero se dispara en la de razonamiento. Solo
programa: no tiene memoria entre sesiones, cron ni canales.

### Después: memoria en Skynet (D20)
Con la herramienta `memoria`, Skynet repite la prueba de memoria con el GSQ-RCO IQ3_S: **OK en 27 s** (guardó la
preferencia en USER.md y la aplicó en la sesión nueva). Hermes: OK en 144 s. Calidad: 5/5 los dos.

## Conclusión
El bucle de Skynet no es peor en calidad y es mucho más rápido con un modelo local: merece la pena
conservarlo. Lo que Hermes aporta de verdad es aprender y recordar (memoria, skills) y lo que no se midió
aquí (cron, subagentes, navegador). Siguiente paso propuesto en PROGRESO.md.

## Reproducir
```powershell
.\.venv\Scripts\python herramientas\bench-hermes\comparar.py --motor gsq-iq3s -a skynet,hermes -t regresion,memoria
```
Requiere Docker Desktop y la imagen `skynet-bench/hermes` (`docker build -t skynet-bench/hermes herramientas\bench-hermes\docker`).
Resultados en `herramientas/bench-hermes/out/` y repos de cada ejecución en `data/bench-hermes/`.
