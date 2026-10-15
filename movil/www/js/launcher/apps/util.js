// Utilidades compartidas por las apps del launcher.
export const kfmt = (n) => (n >= 1e6 ? `${(n / 1e6).toLocaleString('es-ES', { maximumFractionDigits: 1 })} M`
  : n >= 1000 ? `${Math.round(n / 1000).toLocaleString('es-ES')} k` : String(n || 0));

export const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
