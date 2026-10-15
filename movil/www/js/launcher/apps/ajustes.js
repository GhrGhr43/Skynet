// Configuración: motor del agente (harness), modelo local, modelos y memoria.
export default {
  id: 'ajustes', nombre: 'Configuración', icono: 'sliders', color: '#ffcf7a',
  nebulosa: { ojo: '#3f8cff', capa: '#ffd27a', borde: '#e8492a' },
  resumen: (s) => [s.personalizacion?.harnesses?.[s.harness]?.nombre || s.harness, s.modelo].filter(Boolean).join(' · ') || 'Motor y modelos',
  panel: 'ajustes',
};
