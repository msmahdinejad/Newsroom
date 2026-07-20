"""Persist Agent-Reach backend states from real doctor output to the DB.

Run once during Gate 5 live verification. Reads the recorded doctor output,
applies the default production decisions, flips the channels that passed
bounded real-read verification to production_ready, and persists the state
rows to agent_reach_backend_state.
"""
import json
import sys

from sqlalchemy.orm import sessionmaker

from newsroom.sources.agent_reach.adapters import apply_default_production_decisions
from newsroom.sources.agent_reach.registry import (
    AgentReachCapabilityRegistry,
    ProductionApproval,
)
from newsroom.storage.database import engine
from newsroom.storage.models import AgentReachBackendState


def main(doctor_path: str = "doctor_output3.json") -> int:
    with open(doctor_path, encoding="utf-8") as f:
        data = f.read()
    r = AgentReachCapabilityRegistry(pinned_version="1.5.0")
    r.parse_doctor_output(data)
    if r.doctor_parse_error:
        print(f"parse error: {r.doctor_parse_error}", file=sys.stderr)
        return 1
    apply_default_production_decisions(r)

    # Channels that passed bounded real-read verification in Gate 5.
    r.set_production_approval(
        "youtube",
        ProductionApproval.APPROVED,
        notes="yt-dlp installed and bounded real-read verified",
    )
    r.mark_success("youtube", backend="yt-dlp", production_ready=True)
    r.mark_success("web", backend="Jina Reader", production_ready=True)
    r.mark_success("rss", backend="feedparser", production_ready=True)
    r.mark_success("github", backend="gh CLI", production_ready=True)

    states = r.to_backend_states()
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for s in db.query(AgentReachBackendState).all():
            db.delete(s)
        db.flush()
        for state in states:
            db.add(
                AgentReachBackendState(
                    channel=state.channel,
                    pinned_version=state.pinned_version,
                    selected_backend=state.selected_backend,
                    fallback_backends=state.fallback_backends,
                    healthy=state.healthy,
                    last_success_at=state.last_success_at,
                    last_failure_at=state.last_failure_at,
                    failure_category=state.failure_category,
                    degraded=state.degraded,
                    production_ready=state.production_ready,
                    production_approval=state.production_approval,
                    last_doctor_run_at=state.last_doctor_run_at,
                    notes=state.notes,
                )
            )
        db.commit()

    sys.stdout.buffer.write(
        b"persisted " + str(len(states)).encode() + b" backend states\n"
    )
    for s in states:
        line = (
            "  "
            + s.channel
            + ": "
            + (s.selected_backend or "-")
            + " healthy="
            + str(s.healthy)
            + " production_ready="
            + str(s.production_ready)
            + " approval="
            + s.production_approval
            + "\n"
        )
        sys.stdout.buffer.write(line.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "doctor_output3.json"))
