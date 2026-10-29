"""Runtime configuration for ResearchPulse (研脉).

The app deliberately keeps configuration small and explicit: seekdb is addressed
through the MySQL protocol and PowerContext through its HTTP API. No credential
is required for the recommended local setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass
class Settings:
    project_root: Path
    web_root: Path
    seekdb_host: str
    seekdb_port: int
    seekdb_user: str
    seekdb_password: str
    seekdb_database: str
    powercontext_url: str
    powercontext_scope_file: Path
    powercontext_scope_key: str
    powercontext_enabled: bool
    embedding_dimension: int
    app_host: str
    app_port: int
    runtime_dir: Path
    seed_dir: Path
    docs_dir: Path
    allowed_origins: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        _load_dotenv(env_file or PROJECT_ROOT / ".env")
        root = PROJECT_ROOT
        runtime = root / "runtime"
        scope_file = Path(_env("POWERCONTEXT_SCOPE_FILE", str(runtime / "powercontext_scope.txt")))
        if not scope_file.is_absolute():
            scope_file = root / scope_file
        return cls(
            project_root=root,
            web_root=WEB_ROOT,
            seekdb_host=_env("SEEKDB_HOST", "127.0.0.1"),
            seekdb_port=_env_int("SEEKDB_PORT", 2881),
            seekdb_user=_env("SEEKDB_USER", "root"),
            seekdb_password=_env("SEEKDB_PASSWORD", ""),
            seekdb_database=_env("SEEKDB_DATABASE", "yanmai"),
            powercontext_url=_env("POWERCONTEXT_URL", "http://127.0.0.1:8765").rstrip("/"),
            powercontext_scope_file=scope_file,
            powercontext_scope_key=_env("POWERCONTEXT_SCOPE_KEY", "yanmai-research-v1"),
            powercontext_enabled=_env("POWERCONTEXT_ENABLED", "true").lower() not in {"0", "false", "no"},
            embedding_dimension=_env_int("EMBEDDING_DIMENSION", 768),
            app_host=_env("APP_HOST", "127.0.0.1"),
            app_port=_env_int("APP_PORT", 7860),
            runtime_dir=runtime,
            seed_dir=root / "seed",
            docs_dir=root / "docs",
            allowed_origins=[item for item in _env("ALLOWED_ORIGINS", "").split(",") if item],
        )

    def ensure_runtime_dirs(self) -> None:
        for path in (self.runtime_dir, self.powercontext_scope_file.parent):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings.load()
