"""Regression tests for the continuous post-collection processing worker."""

from __future__ import annotations


def test_processing_worker_repeats_bounded_cycles() -> None:
    from newsroom.pipeline.processing_worker import ProcessingWorker

    calls: list[str] = []
    pauses: list[float] = []
    worker = ProcessingWorker(
        run_cycle=lambda: calls.append("cycle") or 0,
        sleep=pauses.append,
        interval_seconds=17,
    )

    worker.run(max_cycles=3)

    assert calls == ["cycle", "cycle", "cycle"]
    assert pauses == [17, 17]


def test_compose_runs_the_continuous_processing_worker() -> None:
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(encoding="utf-8")
    report_worker = compose.split("  report-worker:", 1)[1].split("  scheduler:", 1)[0]

    assert "newsroom.pipeline.processing_worker" in report_worker
    assert "time.sleep(3600)" not in report_worker


def test_production_cycle_prioritizes_telegram_before_the_general_backlog(monkeypatch) -> None:
    from newsroom.pipeline import processing_worker

    calls: list[str | None] = []

    def fake_process(*, source_type: str | None = None, batch_size: int | None = None):
        del batch_size
        calls.append(source_type)
        return processing_worker.ProcessingCycle(0, 0, 0, 0)

    monkeypatch.setattr(processing_worker, "process_pending_items", fake_process)
    monkeypatch.setattr(processing_worker.settings, "processing_priority_source_type", "telegram", raising=False)

    assert processing_worker._run_production_cycle() == 0
    assert calls == ["telegram", None]


def test_pending_raw_claims_use_skip_locked_for_concurrent_workers() -> None:
    import inspect

    from newsroom.pipeline.processing_worker import process_pending_items

    implementation = inspect.getsource(process_pending_items)

    assert "with_for_update" in implementation
    assert "skip_locked=True" in implementation
