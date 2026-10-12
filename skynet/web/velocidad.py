"""Velocidad reciente a partir de tokens contados por llama-server, sin estimar texto."""
from __future__ import annotations


class ContadorTokens:
    def __init__(self):
        self.ultimo: float | None = None
        self.cuentas: dict[tuple[int, int], int] = {}

    def medir(self, slots: object, ahora: float) -> float:
        if not isinstance(slots, list):
            self.ultimo = None
            self.cuentas = {}
            return 0
        actuales = {}
        for slot in slots:
            if not isinstance(slot, dict) or not slot.get("is_processing"):
                continue
            token = slot.get("next_token", {})
            if isinstance(token, list):
                token = token[0] if token else {}
            if isinstance(token, dict):
                n = token.get("n_decoded", 0)
                if isinstance(n, int) and n >= 0:
                    actuales[(slot.get("id", 0), slot.get("id_task", 0))] = n
        intervalo = ahora - self.ultimo if self.ultimo is not None else 0
        delta = sum(max(0, n - self.cuentas.get(k, 0)) for k, n in actuales.items())
        self.ultimo, self.cuentas = ahora, actuales
        return round(delta / intervalo, 1) if intervalo > 0 else 0
