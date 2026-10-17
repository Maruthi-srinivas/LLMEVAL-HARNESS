"""Run status transitions. Illegal moves fail closed."""

_TRANSITIONS = {
    ("pending", "start"): "running",
    ("queued", "start"): "running",
    ("queued", "cancel"): "cancelled",
    ("running", "cancel"): "cancelled",
    ("running", "succeed"): "completed",
    ("running", "partial"): "partial",
}


class InvalidTransition(Exception):
    pass


def transition(current: str, event: str) -> str:
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as exc:
        raise InvalidTransition(f"Cannot apply {event} while the run is {current}") from exc
