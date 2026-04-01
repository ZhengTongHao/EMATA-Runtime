import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.integrations import TemporalRuntime
from app.routes import register_routers
from app.services import ServiceContainer


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _strip_env_value(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _load_env_file(
    file_path: Path,
    *,
    override_existing: bool = False,
    protected_keys: Optional[set[str]] = None,
) -> None:
    if not file_path.exists():
        return
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if protected_keys and key in protected_keys:
            continue
        if not override_existing and key in os.environ:
            continue
        os.environ[key] = _strip_env_value(value)


def _load_project_env_files() -> None:
    protected_keys = set(os.environ.keys())
    _load_env_file(PROJECT_ROOT / ".env.example", protected_keys=protected_keys)
    _load_env_file(
        PROJECT_ROOT / ".env",
        override_existing=True,
        protected_keys=protected_keys,
    )


def create_app(
    database_url: Optional[str] = None,
    temporal_runtime: Optional[TemporalRuntime] = None,
) -> FastAPI:
    _load_project_env_files()
    app = FastAPI(
        title="EMATA API",
        version="0.1.0",
        summary="Enterprise Multi-Agent Task Assistant backend.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.container = ServiceContainer(
        database_url=database_url,
        temporal_runtime=temporal_runtime,
    )
    register_routers(app)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "service": app.title}

    return app


def _build_cors_origins() -> list[str]:
    default_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    raw = os.getenv("EMATA_CORS_ALLOW_ORIGINS", "")
    configured = [item.strip() for item in raw.split(",") if item.strip()]
    merged: list[str] = []
    for origin in configured + default_origins:
        if origin not in merged:
            merged.append(origin)
    return merged


app = create_app()
