"""GpuGate: prioriza a GPU para o usuário sobre trabalho de fundo (learner e,
agora, o flywheel do Nano / avaliação às cegas, que rodam em thread comum)."""

import asyncio
import threading
import time

from src.gpu_gate import GpuGate


def test_user_active_reflete_enter_exit():
    g = GpuGate()
    assert not g.user_active
    g.user_enter()
    assert g.user_active
    g.user_enter()          # 2 requisições simultâneas
    g.user_exit()
    assert g.user_active    # ainda há 1 ativa
    g.user_exit()
    assert not g.user_active


def test_wait_for_idle_retorna_na_hora_se_ninguem_ativo():
    g = GpuGate()
    assert asyncio.run(g.wait_for_idle(timeout=1.0)) is True


def test_wait_for_idle_espera_o_usuario_sair():
    g = GpuGate()
    g.user_enter()

    async def run():
        asyncio.get_event_loop().call_later(0.05, g.user_exit)
        return await g.wait_for_idle(timeout=2.0)

    assert asyncio.run(run()) is True


def test_wait_for_idle_sync_retorna_na_hora_se_ninguem_ativo():
    g = GpuGate()
    t0 = time.monotonic()
    assert g.wait_for_idle_sync(timeout=2.0, poll=0.05) is True
    assert time.monotonic() - t0 < 0.3     # não esperou — já estava ocioso


def test_wait_for_idle_sync_espera_o_usuario_sair():
    """O caso que corrige o bug: teacher_fn/judge_fn rodam numa THREAD comum
    (asyncio.to_thread) — sem asyncio disponível ali, precisam do poll síncrono."""
    g = GpuGate()
    g.user_enter()
    threading.Timer(0.1, g.user_exit).start()
    t0 = time.monotonic()
    assert g.wait_for_idle_sync(timeout=2.0, poll=0.02) is True
    assert time.monotonic() - t0 >= 0.1    # de fato esperou o usuário sair


def test_wait_for_idle_sync_estoura_timeout_e_segue():
    g = GpuGate()
    g.user_enter()
    assert g.wait_for_idle_sync(timeout=0.1, poll=0.02) is False
    g.user_exit()
