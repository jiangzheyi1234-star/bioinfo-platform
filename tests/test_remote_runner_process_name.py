from __future__ import annotations

from apps.remote_runner import run as remote_run


def test_remote_runner_sets_short_linux_process_name(monkeypatch) -> None:
    calls: list[tuple[int, bytes]] = []

    class FakeLibc:
        def prctl(self, option, name, *_args):
            calls.append((option, name.value))
            return 0

    monkeypatch.setattr(remote_run.ctypes, "CDLL", lambda *_args, **_kwargs: FakeLibc())

    remote_run._set_process_name()

    assert calls == [(15, b"h2ometa-remote")]
    assert len(calls[0][1]) <= 15
