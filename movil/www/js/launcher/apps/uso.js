// Uso: llamadas al modelo, tokens, coste y registro de eventos.
import { kfmt } from './util.js';

export default {
  id: 'uso', nombre: 'Uso', icono: 'log', color: '#ffc46b',
  nebulosa: { ojo: '#ff9f2e', capa: '#ffe2a6', borde: '#d2551b' },
  resumen: (s) => `${kfmt((s.mes?.tokens_in || 0) + (s.mes?.tokens_out || 0))} tokens este mes`,
  panel: 'registro',
};
