// Pi conserva su bucle; las herramientas usan el gate y el MCP de Skynet.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default async function (pi: ExtensionAPI) {
  const url = process.env.SKYNET_PI_BRIDGE;
  const token = process.env.SKYNET_PI_TOKEN;
  if (!url || !token) throw new Error("Arranca Pi desde Skynet para conectar sus herramientas.");
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const response = await fetch(`${url}/manifest`, { headers });
  if (!response.ok) throw new Error("No se pudo conectar Pi con Skynet.");
  const { tools } = await response.json();
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
