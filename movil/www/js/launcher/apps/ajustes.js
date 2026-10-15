// Configuración: motor del agente (harness), modelo local, modelos y memoria.
export default {
  id: 'ajustes', nombre: 'Configuración', icono: 'sliders', color: '#b9c6dc',
  resumen: (s) => [s.personalizacion?.harnesses?.[s.harness]?.nombre || s.harness, s.modelo].filter(Boolean).join(' · ') || 'Motor y modelos',
  panel: 'ajustes',
};
