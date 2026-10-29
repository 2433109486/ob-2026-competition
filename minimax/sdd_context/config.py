"""Configuration for the SDD context module.

All values are environment-driven. A local ``.env`` file may be used for
development; it is excluded from git and must never contain a committed key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    return int(raw) if raw else default


@dataclass(slots=True)
class Settings:
    project_root: Path
    seekdb_host: str
    seekdb_port: int
    seekdb_user: str
    seekdb_password: str
    seekdb_database: str
    powercontext_url: str
    powercontext_scope_file: Path
    powercontext_state_kind: str
    powercontext_scope_key: str
    minimax_api_key: str
    minimax_base_url: str
    minimax_model: str
    minimax_embedding_model: str
    embedding_dimension: int
    embedding_batch_size: int
    specs_dir: Path
    code_dirs: tuple[Path, ...]
    tests_dir: Path
    demo_dir: Path
    artifacts_dir: Path
    records_dir: Path
    verbose: bool = False
    notes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        _load_dotenv(env_file or PROJECT_ROOT / ".env")
        root = PROJECT_ROOT
        demo_dir = root / "demo"
        scope_file = Path(
            _env("POWERCONTEXT_SCOPE_FILE", str(demo_dir / "runtime" / "powercontext_scope.txt"))
        )
        if not scope_file.is_absolute():
            scope_file = root / scope_file
        return cls(
            project_root=root,
            seekdb_host=_env("SEEKDB_HOST", "127.0.0.1"),
            seekdb_port=_env_int("SEEKDB_PORT", 2881),
            seekdb_user=_env("SEEKDB_USER", "root"),
            seekdb_password=_env("SEEKDB_PASSWORD", ""),
            seekdb_database=_env("SEEKDB_DATABASE", "sdd_context"),
            powercontext_url=_env("POWERCONTEXT_URL", "http://127.0.0.1:8765").rstrip("/"),
            powercontext_scope_file=scope_file,
            powercontext_state_kind=_env("POWERCONTEXT_STATE_KIND", "sdd_task_state"),
            powercontext_scope_key=_env("POWERCONTEXT_SCOPE_KEY", "booknest-sdd"),
            minimax_api_key=_env("MINIMAX_API_KEY"),
            minimax_base_url=_env("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/"),
            minimax_model=_env("MINIMAX_MODEL", "MiniMax-M3.1-Flash"),
            minimax_embedding_model=_env("MINIMAX_EMBEDDING_MODEL", "embo-01"),
            embedding_dimension=_env_int("EMBEDDING_DIMENSION", 1536),
            embedding_batch_size=_env_int("EMBEDDING_BATCH_SIZE", 10),
            specs_dir=root / "specs",
            code_dirs=(root / "booknest",),
            tests_dir=root / "tests",
            demo_dir=demo_dir,
            artifacts_dir=root / "artifacts",
            records_dir=demo_dir / "minimax_records",
        )

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.demo_dir / "runtime",
            self.demo_dir / "minimax_records",
            self.artifacts_dir / "before",
            self.artifacts_dir / "after",
            self.artifacts_dir / "test_logs",
            self.records_dir,
            self.powercontext_scope_file.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
