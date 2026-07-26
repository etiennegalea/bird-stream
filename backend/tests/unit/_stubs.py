"""Conditional stand-ins for third-party deps in minimal environments.

Unit tests exercise pure logic in modules that import paho/litestar/aiohttp at
module level. In the full dev environment (uv sync) the real packages are
used; when a package is missing (e.g. a constrained CI sandbox), a minimal
stub is injected so the module under test can still be imported.
"""

import sys
import types


def ensure_paho():
    try:
        import paho.mqtt.client  # noqa: F401
        return
    except ImportError:
        pass
    paho = types.ModuleType("paho")
    mqtt_pkg = types.ModuleType("paho.mqtt")
    client = types.ModuleType("paho.mqtt.client")
    enums = types.ModuleType("paho.mqtt.enums")

    class _Result:
        rc = 0

    class Client:
        def __init__(self, **kwargs): ...
        def username_pw_set(self, u, p): ...
        def connect_async(self, *a, **k): ...
        def loop_start(self): ...
        def loop_stop(self): ...
        def disconnect(self): ...
        def subscribe(self, *a, **k): ...
        def publish(self, topic, payload, qos=0):
            return _Result()

    client.Client = Client
    client.MQTTv5 = 5
    client.MQTT_ERR_SUCCESS = 0

    class CallbackAPIVersion:
        VERSION2 = 2

    enums.CallbackAPIVersion = CallbackAPIVersion
    sys.modules.update({"paho": paho, "paho.mqtt": mqtt_pkg,
                        "paho.mqtt.client": client, "paho.mqtt.enums": enums})


def ensure_litestar():
    try:
        import litestar  # noqa: F401
        return
    except ImportError:
        pass
    lit = types.ModuleType("litestar")

    class Controller: ...

    def _decorator(*a, **k):
        def wrap(fn):
            return fn
        return wrap

    lit.Controller = Controller
    lit.get = lit.post = lit.patch = lit.websocket = _decorator

    class WebSocket: ...
    lit.WebSocket = WebSocket

    exc = types.ModuleType("litestar.exceptions")

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class WebSocketDisconnect(Exception): ...

    exc.HTTPException = HTTPException
    exc.WebSocketDisconnect = WebSocketDisconnect
    sys.modules.update({"litestar": lit, "litestar.exceptions": exc})


def ensure_aiohttp():
    try:
        import aiohttp  # noqa: F401
        return
    except ImportError:
        pass
    aio = types.ModuleType("aiohttp")

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class ClientSession: ...

    aio.ClientTimeout = ClientTimeout
    aio.ClientSession = ClientSession
    sys.modules["aiohttp"] = aio


def ensure_auth_service():
    """services.auth_service pulls in sqlalchemy/jwt; stub when unavailable."""
    try:
        import sqlalchemy  # noqa: F401
        import jwt  # noqa: F401
        return
    except ImportError:
        pass
    svc = types.ModuleType("services.auth_service")
    svc.decode_jwt = lambda token: None
    svc.decode_stream_access_token = lambda token: None
    import services as services_pkg
    services_pkg.auth_service = svc
    sys.modules["services.auth_service"] = svc
