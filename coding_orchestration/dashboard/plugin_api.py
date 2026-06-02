from __future__ import annotations

try:
    from fastapi import APIRouter
except ImportError:
    class APIRouter:
        def __init__(self):
            self.routes = []

        def get(self, path: str):
            def decorator(func):
                self.routes.append(("GET", path, func))
                return func

            return decorator

from coding_orchestration.orchestrator import CodingOrchestrator


router = APIRouter()


@router.get("/status")
def status():
    orchestrator = CodingOrchestrator.from_default_config()
    return orchestrator.dashboard_status_payload()
