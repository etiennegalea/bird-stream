"""Read-only endpoints for the bird detection worker."""

from litestar import Controller, get
from litestar.datastructures import State


class DetectionController(Controller):
    path = "/detection"
    tags = ["detection"]

    @get("/status", sync_to_thread=False)
    def status(self, state: State) -> dict:
        svc = getattr(state, "detection_service", None)
        if svc is None:
            return {"enabled": False, "running": False,
                    "reason": "DETECTION_ENABLED is not true"}
        return svc.status()

    @get("/latest", sync_to_thread=False)
    def latest(self, state: State) -> dict:
        svc = getattr(state, "detection_service", None)
        if svc is None:
            return {"enabled": False, "detections": []}
        return svc.get_latest()

    @get("/events", sync_to_thread=False)
    def events(self, state: State, limit: int = 50) -> list[dict]:
        svc = getattr(state, "detection_service", None)
        if svc is None:
            return []
        return svc.get_events(limit=max(1, min(limit, 100)))
