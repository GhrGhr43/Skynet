// Estado: comprobación de la instalación (doctor) y del motor local.
export default {
  id: 'estado', nombre: 'Estado', icono: 'pulse', color: '#6dffa8',
  nebulosa: { ojo: '#2fe07c', capa: '#c9ffdc', borde: '#178a4a' },
  resumen: (s) => {
    const local = (s.motores || []).find((e) => e.nombre === 'local');
    return local ? `Motor local ${local.ocupado ? 'cambiando' : local.encendido ? 'encendido' : 'apagado'}` : 'Comprobar la instalación';
  },
  panel: 'diagnostico',
};
