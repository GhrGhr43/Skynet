"""Prueba de integración con el modelo local real. Solo corre con JARVIS_TEST_LMSTUDIO=1."""
import os

import pytest
from conftest import FakeUI

from jarvis.coordinator import Coordinator
from jarvis.store import HECHA

pytestmark = [
    pytest.mark.lmstudio,
    pytest.mark.skipif(os.environ.get("JARVIS_TEST_LMSTUDIO") != "1", reason="LM Studio no solicitado"),
]


async def test_real_local_model_fixes_code(make_rt, repo_path):
    rt = make_rt(None)  # LiteLLM real contra LM Studio
    ui = FakeUI()
    await Coordinator(rt, ui).handle("Implementa la función doble de mod.py (devuelve el doble de x).")
    task = rt.store.list_tasks(1)[0]
    assert task.status == HECHA, ui.infos
    assert rt.store.totals(task_id=task.id)["tokens_in"] > 0
