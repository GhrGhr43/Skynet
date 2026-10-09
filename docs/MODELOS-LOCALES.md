# Modelos locales para Skynet (RX 9070 XT 16 GB, 32 GB RAM) — 2026-10-08

## Por qué va lento ahora
Qwen 27B denso en Q4_K_M ocupa ~17 GB + 49K de contexto en FP16: no cabe en 16 GB, se va a RAM y un modelo denso fuera de VRAM cae a ~6 tok/s (medido en la 9070 XT con Ollama). [1]

## Recomendación por tarea
| Tarea | Modelo | Cuantización / ajustes | Velocidad esperada (estimada en tu tarjeta) |
|---|---|---|---|
| Código (calidad) | Qwen3.8-27B (denso, el más nuevo) | **UD-IQ3_XXS** de Unsloth, KV cache q8_0 (o q4_0 si quieres 64K+), Flash Attention on, MTP | ~20-28 tok/s (3080 da 20-30) [2] |
| Código rápido / tareas largas en bucle | Qwen3.6-35B-A3B (MoE, 3B activos) | UD-Q4_K_M + "MoE Expert Offloading" (~13 capas de expertos a RAM) a 32K | ~30-50 tok/s [3] |
| Chat rápido | gpt-oss-20b (MoE) | Q4/MXFP4, cabe entero | ~90 tok/s, 3.400+ tok/s de prompt [1] |
| Router / clasificar | Qwen3.5-9B Q4_K_M (o 4B si existe en tu LM Studio) | Contexto corto (4-8K) | ~90 tok/s en Vulkan [1] |

Para tareas largas: el MoE es el mejor equilibrio (rápido y con contexto grande). Deja el 27B para pasos difíciles o como "verificador/revisor". Gemini Flash gratis como escalado cuando el local falle dos veces.

## Novedades y rarezas útiles para AMD
- **Vulkan > ROCm en tu tarjeta** para generar: +13-35 % en modelos que caben en VRAM. ROCm solo gana en prefill o modelos desbordados. En Windows usa el runtime Vulkan de LM Studio (Ctrl+Shift+R). [1][4]
- **MTP (multi-token prediction)**: llama.cpp desde mayo 2026 (`--spec-type draft-mtp`), estable en LM Studio 0.4.14. Usa la cabeza MTP del propio modelo, sin modelo borrador: 1.4-1.7x en Qwen3.5/3.6/3.8 y Gemma 4 26B-A4B. En 16 GB la ganancia es menor (gasta algo de VRAM); probar `--spec-draft-n-max 2` + `ngram-mod`. [2][5][6]
- **KV cache cuantizada** (q8_0 ≈ mitad de memoria, q4_0 ≈ cuarto): Qwen la tolera bien y es lo que permite 64-128K en 16 GB. En Qwen3.6 MoE ahorra poco (solo 10 de 40 capas con atención completa). [2][3]
- **MoE + expertos en RAM** (`--n-cpu-moe` / "MoE Expert Offloading"): la misma idea que Strata pero en LM Studio; tu 7800X3D y DDR5 lo aguantan bien.
- **No existe Qwen3.8 MoE oficial** (solo 27B denso); los "Qwen3.8-35B-A3B" en HF son destilados de terceros. [7]

## Prueba sugerida (5 min, en LM Studio)
1. Descargar `unsloth/Qwen3.8-27B-GGUF` UD-IQ3_XXS, contexto 32K, KV q8_0, Flash Attention on, runtime Vulkan.
2. Descargar `unsloth/Qwen3.6-35B-A3B-GGUF` UD-Q4_K_M con MoE offloading.
3. Comparar tok/s en la misma tarea de código y dejar el ganador como `coding` en Skynet.

## Fuentes
1. https://localaimaster.com/blog/rx-9070-xt-local-ai (ago 2026)
2. https://www.autodidacts.io/how-to-fit-qwen3-8-27b-into-16gb-vram-run-with-llama-cpp-rtx-3080-flags-quantizations/
3. https://dev.to/donald_lee_707b59c456e304/how-to-pick-n-cpu-moe-in-llamacpp-qwen36-35b-a3b-on-12-16-and-24-gb-gpus-43f3
4. https://runaihome.com/blog/rdna4-vulkan-vs-rocm-local-llm-benchmark-2026/ (jul 2026)
5. https://www.cloudmagazin.com/en/2026/05/27/llama-cpp-mtp-support-27b-modelle-1-7x-schneller-consumer/
6. https://insiderllm.com/guides/lm-studio-tips-and-tricks/
7. https://huggingface.co/Qwen/Qwen3.8-27B/discussions/120
