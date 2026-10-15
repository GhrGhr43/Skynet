// Aprendizaje: lo que el agente propone recordar (skills y memoria), pendiente de tu visto bueno.
export default {
  id: 'aprendizaje', nombre: 'Aprendizaje', icono: 'sparkle', color: '#ff8ad8',
  resumen: (s) => (s.propuestas ? `${s.propuestas} pendiente${s.propuestas > 1 ? 's' : ''} de revisar` : 'Nada pendiente'),
  insignia: (s) => s.propuestas || 0,
  panel: 'aprendizaje',
};
