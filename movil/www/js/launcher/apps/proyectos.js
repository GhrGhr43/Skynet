// Proyectos: los repos en los que el agente puede trabajar (elegir, añadir, quitar de la lista).
export default {
  id: 'proyectos', nombre: 'Proyectos', icono: 'repo', color: '#5fe0bf',
  nebulosa: { ojo: '#24c9a3', capa: '#b5ffe8', borde: '#0f7f6b' },
  resumen: (s) => s.repo || 'Sin repo',
  panel: 'ajustes', seccion: 'repos',
};
