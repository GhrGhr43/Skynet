// Pi conserva bucle y herramientas; esta extensión consulta permisos y memoria opcional.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default async function (pi: ExtensionAPI) {
  const url = process.env.SKYNET_PI_BRIDGE;
  const token = process.env.SKYNET_PI_TOKEN;
  if (!url || !token) throw new Error("Arranca Pi desde Skynet para conectar sus herramientas.");
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const response = await fetch(`${url}/manifest`, { headers });
  if (!response.ok) throw new Error("No se pudo conectar Pi con Skynet.");
  const { tools } = await response.json();
  pi.on("tool_call", async (event) => {
    const response = await fetch(`${url}/authorize`, {
      method: "POST", headers,
      body: JSON.stringify({ name: event.toolName, args: event.input }),
    });
    if (!response.ok) return { block: true, reason: "No se pudo comprobar el permiso" };
    const result = await response.json();
    if (!result.allowed) return { block: true, reason: result.reason || "Acción no permitida" };
  });
  for (const tool of tools) {
    pi.registerTool({
      name: tool.name,
      label: tool.name,
      description: tool.description,
      parameters: tool.parameters,
      async execute(_id, args, signal) {
        const response = await fetch(`${url}/tool`, {
          method: "POST", headers, signal,
          body: JSON.stringify({ name: tool.name, args }),
        });
        if (!response.ok) throw new Error(`El puente de Skynet respondió ${response.status}`);
        return await response.json();
      },
    });
  }
}
