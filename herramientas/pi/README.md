# Pi como motor de Skynet

Pi 1.1.0 está instalado dentro del proyecto, fijado con lockfile. Se conecta al endpoint elegido
por su RPC oficial. Conserva read/bash/edit/write, instrucciones, sesiones y compactación;
Skynet no sustituye su bucle ni verifica el resultado por su cuenta.

1. Abre `C:\Git\Skynet\Abrir Skynet.cmd`.
2. Elige el proyecto o «Sin repo» para conversar.
3. Pulsa **Pi** bajo el chat para configurar harness, herramientas, modelos y extras.
4. Envía el objetivo. **Detener** conserva archivos y conversación; `continúa` retoma la tarea.

`Probar Pi.cmd` prepara `proyectos/prueba-pi`. Pi de consola en `C:\Git\PiLocal` sigue independiente.
Se comparte el servidor del modelo; no se duplican pesos. Compara en chats nuevos con iguales
opciones de contexto, razonamiento y MTP.

Opciones: `data/personalizacion.json`. Configuración generada: `data/pi/agent`.
Sesiones JSONL: `data/pi/sessions`, estables por chat y proyecto. MCP y memoria están apagados
inicialmente. MCP usa descubrimiento oficial de Pi; memoria se aprueba de una en una.
No se descubren claves, extensiones, settings o MCP de otras instalaciones ni `.pi` del proyecto.
Las instrucciones `AGENTS.md` del proyecto se conservan al modo habitual de Pi.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File herramientas/pi/instalar.ps1
```

Node.js 22.19 o posterior. `puente.ts` revisa llamadas antes de ejecutarse sin reemplazar las
herramientas; no aporta aislamiento del sistema operativo. Compactación original con 64K;
reserva adaptada para ventanas menores de 36K.

Prueba del modelo real después de migrar: tarea 202, cuatro llamadas, dos archivos Python y ocho
comprobaciones correctas. Tests con **Pi instalado**, proveedor simulado y MCP real comprueban
herramientas opcionales, descubrimiento, memoria individual y persistencia. Demuestran funcionamiento,
no superioridad universal en calidad. Evidencia del modelo en `data/pruebas/agua/motor-nativo.json`.

Documentación de la versión instalada: `node_modules/@earendil-works/pi-coding-agent/docs/`.
Contrato: [RPC](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/rpc.md),
[extensiones](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/extensions.md).
