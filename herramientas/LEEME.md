# Herramientas auxiliares (fuera del Core)

- `bench-hermes/`: compara agentes (Skynet, Hermes, OpenCode) y motores locales con tareas y verificador oculto
  (`comparar.py`; informe en docs/COMPARATIVA-HERMES.md).
- `bench-agentico/`: las tareas agénticas de código que usa `bench-hermes`.
- `motores/`: `motores.cmd` muestra o apaga los motores en marcha (puertos 8090 local, 8642 Hermes, 1234 LM Studio).

La app del móvil está en `movil/` (www/ + android/build.sh; instrucciones en movil/INSTALAR.md y
docs/ACCESO-MOVIL.md). La firma (`firma/`) y los APK no se suben al repo.
