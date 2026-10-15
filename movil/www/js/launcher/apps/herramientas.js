// Herramientas: servidores MCP que el agente puede usar.
export default {
  id: 'herramientas', nombre: 'Herramientas', icono: 'terminal', color: '#b59cff',
  resumen: (s) => {
    const mcp = Object.values(s.personalizacion?.mcp || {});
    return mcp.length ? `${mcp.filter((m) => m.enabled).length} de ${mcp.length} MCP activos` : 'Servidores MCP';
  },
  panel: 'ajustes', seccion: 'mcp',
};
