// Conexión (solo en el móvil): con qué PC está enlazada la app, probarla o desconectarla.
import { modoConexion, conexion } from '../../api.js';

export default {
  id: 'conexion', nombre: 'Tu PC', icono: 'link', color: '#6cd0ff',
  nebulosa: { ojo: '#2fb8ff', capa: '#c4efff', borde: '#1670c4' },
  resumen: () => (modoConexion === 'pc' ? (conexion().url || '').replace(/^https?:\/\//, '').split('.')[0] || 'Conectado' : 'Modo demo · conectar'),
  panel: 'ajustes', seccion: 'conexion',
};
