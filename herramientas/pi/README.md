# Pi con el modelo local de Skynet

Pi 1.1.0 está instalado aquí y conectado mediante su RPC y una extensión oficiales.
Pi lleva el bucle de programación; Skynet conserva el chat, las herramientas MCP, los permisos,
las tareas y la verificación. Utiliza tu modelo llama.cpp ya configurado, sin duplicar los pesos.

## Para probarlo

1. Doble clic en `C:\Git\Skynet\Probar Pi.cmd`.
2. En la web aparece `Coder · Pi`, modelo local y repo `prueba-pi`.
3. Envía una petición completa. Los archivos quedan en `C:\Git\Skynet\proyectos\prueba-pi`.
4. Para otra carpeta, elígela en el selector de repos autorizados.
5. Para comparar agentes: `+ > Agente para programar > Skynet/Pi` y crea una tarea nueva.

El lanzador enciende el modelo si hace falta, reutiliza o arranca la web y abre
http://127.0.0.1:8765. Si la web está trabajando, espera a que termine antes de cambiar opciones.
Puedes abrir directamente `proyectos\prueba-pi\index.html`: Pi ya ha creado un contador de ejemplo.
No hace falta LM Studio abierto. LiteLLM sigue instalado porque lo usa el motor habitual de Skynet.

En el chat de terminal:

```text
/repo prueba-pi
/coder pi
Crea una web de ... y comprueba los botones, el móvil y una captura antes de terminar.
```

`/coder skynet` vuelve al motor habitual. `continúa` retoma la tarea con el motor que tenía,
aunque cambies el selector antes. El arranque general de Skynet usa su motor habitual;
el lanzador de pruebas elige Pi de nuevo. La APK no incorpora este selector todavía.

## Configuración y mantenimiento

La configuración generada está en `data/pi/agent`, y las sesiones oficiales en `data/pi/sessions`.
El perfil local de Skynet decide endpoint, contexto, salida, muestreo, razonamiento y visión;
la integración lo aplica al iniciar cada ejecución. En este PC utiliza el mismo Qwen y contexto 64K.
No se importan las claves ni extensiones de una instalación personal de Pi.

Para reinstalar dependencias, desde `C:\Git\Skynet`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File herramientas/pi/instalar.ps1
```

Requiere Node.js 22.19 o posterior; aquí se ha probado con 24.19.0. El lockfile fija las
dependencias instaladas. Las herramientas de ejecución propias de Pi están desactivadas:
sus llamadas pasan por los mismos permisos de Skynet. Esto no añade aislamiento del sistema operativo.

## Pruebas realizadas

- Pi y modelo reales: función Python con ocho tests, tarea 186.
- Pi y modelo reales: contador HTML con persistencia y revisión de captura, tarea 187.
- Comprobación independiente: sumar, reiniciar, recargar, anchos 390/768/1440 y selector Skynet/Pi.
- Tests del adaptador: gate real, autenticación, cancelación, uso, imágenes y planes pendientes.

Evidencias en `data/pruebas/pi`; el código del contador lo escribió Pi sin correcciones manuales.
No se ha medido todavía si supera a Skynet en tareas equivalentes. El verificador del repo de
ejemplo comprueba carga, errores JavaScript y desbordamiento; no certifica todas las funciones que
puedas pedir. Para una aplicación compleja añade tests de sus requisitos.

Si la web no arranca, revisa `data/logs/web-pi.stderr.log`. Si el modelo falla, usa el diagnóstico
de Skynet. El aviso previo del repo inexistente `age-of-empires-3d` no impide usar `prueba-pi`.

Interfaz oficial: [RPC](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/rpc.md),
[modelos](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/models.md) y
[extensiones](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/extensions.md).
