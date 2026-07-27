"""The public report command must use the production editorial pipeline."""

from __future__ import annotations

import argparse
import os


def test_report_command_runs_current_editorial_pipeline(monkeypatch, capsys) -> None:
    from newsroom.cli.commands import report
    from newsroom.pipeline import runner

    observed: dict[str, object] = {}

    def fake_run_pipeline(*, blocking_lock: bool) -> dict[str, object]:
        observed["blocking_lock"] = blocking_lock
        observed["report_mode"] = os.environ.get("NEWSROOM_REPORT_MODE")
        return {"status": "ok", "report_id": 44, "delivery_id": 55}

    monkeypatch.setattr(runner, "run_pipeline", fake_run_pipeline)

    assert report.report_command(argparse.Namespace()) == 0
    assert observed == {"blocking_lock": True, "report_mode": "manual"}
    assert "44" in capsys.readouterr().out


def test_report_command_can_scope_to_telegram(monkeypatch) -> None:
    from newsroom.cli.commands import report
    from newsroom.pipeline import runner

    observed: dict[str, object] = {}

    def fake_run_pipeline(*, blocking_lock: bool) -> dict[str, object]:
        observed["blocking_lock"] = blocking_lock
        observed["report_mode"] = os.environ.get("NEWSROOM_REPORT_MODE")
        return {"status": "ok", "report_id": 45, "delivery_id": 56}

    monkeypatch.setattr(runner, "run_pipeline", fake_run_pipeline)

    assert report.report_command(argparse.Namespace(source="telegram")) == 0
    assert observed == {
        "blocking_lock": True,
        "report_mode": "platform_telegram",
    }
