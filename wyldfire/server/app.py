"""FastAPI application for Wyldfire hosted sync server."""

from typing import Any, Dict, List, Optional
import os

try:
    from fastapi import FastAPI, Depends, HTTPException, Header, status
    from pydantic import BaseModel
except ImportError:
    # If fastapi not installed in local environment, provide placeholder
    FastAPI = None
    Depends = lambda *args, **kwargs: None
    HTTPException = None
    Header = lambda *args, **kwargs: None
    status = None
    BaseModel = object

from wyldfire.server import db


def create_app():
    server_token = os.environ.get("WYLD_SERVER_TOKEN")
    if not server_token:
        raise RuntimeError("WYLD_SERVER_TOKEN environment variable must be set")

    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install with 'pip install wyldfire[server]'")

    app = FastAPI(title="Wyldfire Sync Server", version="0.1.0")

    def verify_token(authorization: Optional[str] = Header(None)) -> str:
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
            )
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization header scheme",
            )
        token = authorization[len(prefix):].strip()
        expected = os.environ.get("WYLD_SERVER_TOKEN", server_token)
        if token != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid API token",
            )
        return token

    class ProjectRequest(BaseModel):
        project_id: str
        name: str

    class PushEventsRequest(BaseModel):
        project_id: str
        events: List[Dict[str, Any]]

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "wyldfire-sync-server"}

    @app.post("/api/v1/projects")
    def create_or_link_project(req: ProjectRequest, _: str = Depends(verify_token)):
        proj = db.get_or_create_project(req.project_id, req.name)
        return {"status": "ok", "project": proj}

    @app.post("/api/v1/events")
    def push_events(req: PushEventsRequest, _: str = Depends(verify_token)):
        accepted, skipped = db.save_events(req.project_id, req.events)
        return {"status": "ok", "accepted": accepted, "skipped": skipped}

    @app.get("/api/v1/events")
    def pull_events(project_id: str, since: Optional[str] = None, _: str = Depends(verify_token)):
        events = db.get_events(project_id, since=since)
        return {"status": "ok", "project_id": project_id, "events": events}

    return app


class MissingTokenApp:
    def __call__(self, scope, receive, send):
        raise RuntimeError("WYLD_SERVER_TOKEN environment variable must be set")


# Lazy-loaded instance for uvicorn
app = None
if FastAPI is not None:
    if os.environ.get("WYLD_SERVER_TOKEN"):
        app = create_app()
    else:
        app = MissingTokenApp()
