// Sesiones: las conversaciones con el agente. No tiene ventana propia: entra al agente con la lista abierta.
import { plural } from './util.js';

export default {
  id: 'sesiones', nombre: 'Sesiones', icono: 'chat', color: '#7fb2ff',
  nebulosa: { ojo: '#5b8cff', capa: '#a9d4ff', borde: '#3b4fd8' },
  resumen: (s, app) => (app.sessions.length ? plural(app.sessions.length, 'reciente', 'recientes') : 'Tus conversaciones'),
  accion: (app) => app.enterAgent({ side: true }),
};
