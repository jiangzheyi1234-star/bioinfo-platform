from __future__ import annotations

from types import SimpleNamespace

from apps.remote_runner import reconciler_actions


def test_terminate_process_group_uses_taskkill_for_windows(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(reconciler_actions, "_uses_windows_process_groups", lambda: True)
    monkeypatch.setattr(reconciler_actions.subprocess, "run", fake_run)

    result = reconciler_actions.terminate_process_group("4242")

    assert result == {"terminated": True, "processGroupId": 4242}
    assert calls == [
        {
            "command": ["taskkill", "/PID", "4242", "/T"],
            "capture_output": True,
            "text": True,
            "check": False,
        }
    ]


def test_terminate_process_group_escalates_to_sigkill(monkeypatch) -> None:
    signals: list[int] = []
    probes = iter([False, True])

    monkeypatch.setattr(reconciler_actions, "_uses_windows_process_groups", lambda: False)
    monkeypatch.setattr(reconciler_actions.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(
        reconciler_actions.os,
        "killpg",
        lambda _pgid, signal_number: signals.append(signal_number),
        raising=False,
    )
    monkeypatch.setattr(
        reconciler_actions,
        "_wait_for_process_group_exit",
        lambda *_args, **_kwargs: next(probes),
    )

    result = reconciler_actions.terminate_process_group("4242", terminate_timeout_seconds=0)

    assert signals == [reconciler_actions.signal.SIGTERM, reconciler_actions.signal.SIGKILL]
    assert result == {
        "terminated": True,
        "confirmedStopped": True,
        "processGroupId": 4242,
        "signal": "SIGKILL",
    }
