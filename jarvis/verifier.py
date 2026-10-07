"""Verificador objetivo (principio 7): un agente no da por buena su propia tarea.

Ejecuta el comando `verificador` del repo (tests, build, ejecución headless). Exit 0 = pasa.
El comando viene de config/repos.toml (lo escribe el dueño), no del modelo.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifierResult:
    ok: bool
    exit_code: int | None
    output_tail: str
    seconds: float
    command: str

    @property
    def signature(self) -> str:
        """Huella del fallo para detectar errores repetidos (ignora números, rutas y tiempos)."""
        tail = "\n".join(self.output_tail.strip().splitlines()[-15:])
        norm = re.sub(r"\d+(\.\d+)?", "N", tail)
        norm = re.sub(r"0x[0-9a-fA-F]+", "X", norm)
        return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:12]

    def counts(self) -> tuple[int, int] | None:
        """(pasan, fallan) si la salida tiene el resumen típico de pytest/jest/unittest; si no, None."""
        text = self.output_tail
        passed = sum(int(n) for n in re.findall(r"(\d+) (?:passed|passing)\b", text))
        failing = sum(int(n) for n in re.findall(r"(\d+) (?:failed|failing|errors?)\b", text))
        m = re.search(r"Ran (\d+) tests?", text)  # unittest
        if m and not passed and not failing:
            total = int(m.group(1))
            f = re.search(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?\)", text)
            failing = sum(int(x) for x in f.groups() if x) if f else 0
            passed = total - failing
        if not passed and not failing:
            return None
        return passed, failing

    def not_worse_than(self, base: "VerifierResult | None") -> bool:
        """Avance aceptable aunque no esté todo en verde: no pasan menos tests ni fallan más."""
        if self.ok:
            return True
        if base is None or base.ok:
            return False
        now, before = self.counts(), base.counts()
        if now is None or before is None:
            return False
        return now[0] >= before[0] and now[1] <= before[1]

    def summary(self) -> str:
        state = "PASA" if self.ok else f"FALLA (exit {self.exit_code})"
        return f"{state} en {self.seconds:.0f} s: {self.command}"


def run_verifier(command: str, cwd: Path, timeout: int = 900, tail_chars: int = 4000) -> VerifierResult:
    t0 = time.monotonic()
    try:
        r = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
        code: int | None = r.returncode
    except subprocess.TimeoutExpired as e:
        partial = e.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        out = f"{partial}\n[TIMEOUT tras {timeout} s]"
        code = None
    secs = time.monotonic() - t0
    return VerifierResult(code == 0, code, out[-tail_chars:], secs, command)
