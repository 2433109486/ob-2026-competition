"""运行时配置：全部通过环境变量注入，不落盘任何凭据。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # seekdb（MySQL 协议）
    seekdb_host: str = field(default_factory=lambda: _env("SEEKDB_HOST", "127.0.0.1"))
    seekdb_port: int = field(default_factory=lambda: int(_env("SEEKDB_PORT", "2881")))
    seekdb_user: str = field(default_factory=lambda: _env("SEEKDB_USER", "root"))
    seekdb_password: str = field(default_factory=lambda: _env("SEEKDB_PASSWORD", ""))
    seekdb_database: str = field(default_factory=lambda: _env("SEEKDB_DATABASE", "absurd_court"))

    # PowerContext Server
    pc_base_url: str = field(default_factory=lambda: _env("POWERCONTEXT_BASE_URL", "http://127.0.0.1:8000").rstrip("/"))
    pc_enabled: bool = field(default_factory=lambda: _bool("POWERCONTEXT_ENABLED", True))
    pc_timeout: float = field(default_factory=lambda: float(_env("POWERCONTEXT_TIMEOUT", "4")))
    pc_scope_prefix: str = field(default_factory=lambda: _env("POWERCONTEXT_SCOPE_PREFIX", "absurd-court"))

    # Embedding：默认零依赖的确定性哈希向量；可切换 OpenAI 兼容接口
    embedding_backend: str = field(default_factory=lambda: _env("EMBEDDING_BACKEND", "hash").lower())
    embedding_dim: int = field(default_factory=lambda: int(_env("EMBEDDING_DIM", "128")))
    embedding_base_url: str = field(default_factory=lambda: _env("EMBEDDING_BASE_URL", "https://api.openai.com/v1"))
    embedding_api_key: str = field(default_factory=lambda: _env("EMBEDDING_API_KEY", ""))
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "text-embedding-3-small"))

    # 庭审规则
    max_turns: int = field(default_factory=lambda: int(_env("COURT_MAX_TURNS", "3")))

    def masked(self) -> dict:
        """用于 /api/v1/health，确认配置而不泄露密钥。"""

        return {
            "seekdb": f"{self.seekdb_host}:{self.seekdb_port}/{self.seekdb_database}",
            "powercontext": self.pc_base_url if self.pc_enabled else "disabled",
            "embedding": {
                "backend": self.embedding_backend,
                "dim": self.embedding_dim,
                "model": self.embedding_model if self.embedding_backend != "hash" else "builtin-hash",
                "api_key_configured": bool(self.embedding_api_key),
            },
            "max_turns": self.max_turns,
        }


settings = Settings()
