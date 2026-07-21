"""Persist the X channel upgrade to production after live verification."""
import sys

from sqlalchemy.orm import sessionmaker

from newsroom.sources.agent_reach.adapters import upgrade_x_to_production
from newsroom.sources.agent_reach.registry import (
    AgentReachCapabilityRegistry,
)
from newsroom.storage.database import engine
from newsroom.storage.models import AgentReachBackendState


def main() -> int:
    # Load the recorded doctor output (from Gate 5).
    try:
        with open("docs/verification/GATE_5_DOCTOR_OUTPUT.json", encoding="utf-8") as f:
            doctor_data = f.read()
    except FileNotFoundError:
        doctor_data = "{}"

    r = AgentReachCapabilityRegistry(pinned_version="1.5.0")
    r.parse_doctor_output(doctor_data)

    # Apply default decisions, then upgrade X to production.
    from newsroom.sources.agent_reach.adapters import apply_default_production_decisions

    apply_default_production_decisions(r)
    upgrade_x_to_production(r)

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

    x_state = next((s for s in states if s.channel == "x"), None)
    if x_state:
        sys.stdout.buffer.write(
            b"x channel: production_ready=" + str(x_state.production_ready).encode() + b" approval=" + x_state.production_approval.encode() + b"\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
