"""The watchdog loop keeps its blocking database work off the event loop."""
import asyncio

import pytest


def test_every_watchdog_step_runs_in_a_thread(monkeypatch):
    import app.main as main

    in_thread = []

    async def fake_to_thread(fn, *a, **kw):
        in_thread.append(fn.__name__)

    async def stop(_seconds):
        raise asyncio.CancelledError

    def on_loop():
        raise AssertionError("ran on the event loop")

    for name in ("recover_stalled_jobs", "process_pending_learning", "purge_template_uploads",
                 "purge_delivery_files", "purge_old_notifications"):
        monkeypatch.setattr(main, name, on_loop)
    monkeypatch.setattr(main.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(main.asyncio, "sleep", stop)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._watchdog_loop())
    assert len(in_thread) == 5
