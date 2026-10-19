"""Keep product tests queued unless a test publishes on purpose."""

import os

os.environ["EVALFORGE_ENQUEUE_RUNS"] = "false"
os.environ["KAFKA_BOOTSTRAP_SERVERS"] = ""
os.environ["ARTIFACT_S3_ENDPOINT"] = ""
