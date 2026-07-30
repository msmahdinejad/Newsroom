"""The public report command must use the production editorial pipeline."""

from __future__ import annotations

import argparse


def test_report_command_runs_current_editorial_pipeline(monkeypatch, capsys) -> None:
    from newsroom.cli.commands import report
    from newsroom.pipeline import runner

    observed: dict[str, object] = {}

    def fake_run_pipeline(*, blocking_lock: bool, request) -> dict[str, object]:
        observed["blocking_lock"] = blocking_lock
        observed["report_mode"] = request.report_mode
        observed["digest_slug"] = request.digest_slug
        return {"status": "ok", "report_id": 44, "delivery_id": 55}

    monkeypatch.setattr(runner, "run_pipeline", fake_run_pipeline)

    assert report.report_command(argparse.Namespace()) == 0
    assert observed == {
        "blocking_lock": True,
        "report_mode": "manual",
        "digest_slug": "default",
    }
    assert "44" in capsys.readouterr().out


def test_report_command_can_scope_to_telegram(monkeypatch) -> None:
    from newsroom.cli.commands import report
    from newsroom.pipeline import runner

    observed: dict[str, object] = {}

    def fake_run_pipeline(*, blocking_lock: bool, request) -> dict[str, object]:
        observed["blocking_lock"] = blocking_lock
        observed["report_mode"] = request.report_mode
        observed["digest_slug"] = request.digest_slug
        return {"status": "ok", "report_id": 45, "delivery_id": 56}

    monkeypatch.setattr(runner, "run_pipeline", fake_run_pipeline)

    assert report.report_command(argparse.Namespace(source="telegram")) == 0
    assert observed == {
        "blocking_lock": True,
        "report_mode": "platform_telegram",
        "digest_slug": "default",
    }
