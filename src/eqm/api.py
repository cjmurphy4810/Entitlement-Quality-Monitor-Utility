"""FastAPI app — skeleton with auth and health."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from eqm.config import Settings, get_settings
from eqm.persistence import JsonStore

bearer_scheme = HTTPBearer(auto_error=False)
app = FastAPI(title="EQM Utility", version="0.1.0")


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    if credentials is None or credentials.credentials != settings.bearer_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid bearer token")


def get_store(settings: Settings = Depends(get_settings)) -> JsonStore:  # noqa: B008
    return JsonStore(settings.data_dir)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/simulate/tick", dependencies=[Depends(require_token)])
def simulate_tick_placeholder() -> dict:
    return {"todo": "wired in Task 32"}
