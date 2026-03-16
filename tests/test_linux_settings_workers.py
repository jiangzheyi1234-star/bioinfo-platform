import pytest


pytestmark = pytest.mark.ui


def test_conda_detect_worker_cancel_suppresses_emit(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import CondaDetectWorker

    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.env_detector.detect",
        lambda ssh_run_fn: {"status": "ok"},
    )

    worker = CondaDetectWorker(lambda *args, **kwargs: (0, "", ""))
    received = []
    worker.finished.connect(lambda result: received.append(result))

    worker.cancel()
    worker.run()

    assert received == []
