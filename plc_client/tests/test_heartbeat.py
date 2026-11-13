import inspect

import main


def test_heartbeat_never_calls_production_endpoint():
    source = inspect.getsource(main.run)
    heartbeat_source = source[source.index("def heartbeat"):source.index("heartbeat_worker = None")]
    assert "production-event" not in heartbeat_source
    assert "client.send_event" not in heartbeat_source
