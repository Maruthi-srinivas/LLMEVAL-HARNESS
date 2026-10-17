def test_health_body_requires_both_dependencies():
    from backend.app.health import build_health_body

    assert build_health_body(True, True)[0] == 200
    status, body = build_health_body(True, False)
    assert status == 503
    assert body["checks"] == {"postgres": "ok", "redis": "unavailable"}
    assert body["status"] == "unavailable"


def test_engine_modules_do_not_import_fastapi():
    import sys

    sys.modules.pop("fastapi", None)
    import evaluator.adapters.mock  # noqa: F401
    import evaluator.metrics.deterministic  # noqa: F401
    import evaluator.runner  # noqa: F401

    assert "fastapi" not in sys.modules
