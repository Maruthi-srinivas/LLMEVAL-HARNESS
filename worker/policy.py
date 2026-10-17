"""How a finished run is classified.

Target success with a failing metric stays an execution success and a quality failure.
timeout, rate_limit, and provider_error are execution errors. They are counted on their
own and are not treated as wrong answers.

Any execution error makes the run partial. A run with only quality failures can be
completed. A run cannot become completed or partial while a case has no terminal
attempt. Cancellation keeps finished results and stops new claims; the status stays
cancelled even if some cases were never claimed.
"""

from __future__ import annotations


def completion_status(current: str, unresolved: int, execution_errors: int) -> str | None:
    """Return the terminal status, or None while cases are still unresolved."""
    if current == "cancelled":
        return "cancelled"
    if unresolved:
        return None
    if execution_errors:
        return "partial"
    return "completed"
