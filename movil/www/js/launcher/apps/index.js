// Registro de apps del launcher (versión móvil). La app madre es el agente (la nebulosa del centro);
// estas son las apps hijas que flotan a su alrededor. Mismo manifiesto que en la web
// (skynet/web/static/js/launcher/apps/index.js); en el móvil, «Móvil» se cambia por «Tu PC».
import sesiones from './sesiones.js';
import proyectos from './proyectos.js';
import herramientas from './herramientas.js';
import uso from './uso.js';
import estado from './estado.js';
import conexion from './conexion.js';
import aprendizaje from './aprendizaje.js';
import ajustes from './ajustes.js';

export const APPS = [sesiones, proyectos, herramientas, uso, estado, conexion, aprendizaje, ajustes];
