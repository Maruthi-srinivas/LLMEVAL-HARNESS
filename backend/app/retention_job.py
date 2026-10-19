"""Scheduled retention purge. Compose runs this process; it does not install anything on the host."""

from __future__ import annotations

import time

from backend.app.db import session_scope
from backend.app.services.retention import purge_expired


def main() -> None:
    while True:
        with session_scope() as session:
            purge_expired(session)
        time.sleep(3600)


if __name__ == "__main__":
    main()
