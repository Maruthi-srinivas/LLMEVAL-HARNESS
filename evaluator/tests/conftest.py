"""Keep product tests queued unless a test publishes on purpose."""

import os

os.environ["EVALFORGE_ENQUEUE_RUNS"] = "false"
