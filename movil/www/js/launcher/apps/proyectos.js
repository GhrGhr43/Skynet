// Proyectos: los repos en los que el agente puede trabajar (elegir, añadir, quitar de la lista).
export default {
  id: 'proyectos', nombre: 'Proyectos', icono: 'repo', color: '#7fd6c2',
  resumen: (s) => s.repo || 'Sin repo',
  panel: 'ajustes', seccion: 'repos',
};
