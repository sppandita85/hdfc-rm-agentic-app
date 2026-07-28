"""Typed application settings, loaded once from .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_database_url: str

    ollama_host: str
    ollama_model: str
    ollama_timeout_s: float

    # Which provider classifies intent. Everything else (drafting, entity
    # extraction) always runs on the local Ollama model.
    intent_provider: str            # "anthropic" | "ollama"
    anthropic_api_key: str          # "" when unset — see anthropic_configured()
    anthropic_model: str
    anthropic_effort: str
    anthropic_max_tokens: int

    rm_name: str
    rm_title: str
    rm_bank: str

    def anthropic_configured(self) -> bool:
        """The SDK constructor does NOT raise on a missing key — it fails later, at call
        time, with an AuthenticationError. So check up front to show a useful banner."""
        return bool(self.anthropic_api_key.strip())

    @property
    def database_name(self) -> str:
        """The bare database name, parsed off the end of database_url.

        The seed script needs this separately from the URL because DROP/CREATE DATABASE
        must run against a *different* database (admin_database_url).
        """
        return self.database_url.rsplit("/", 1)[-1].split("?")[0]


def _get(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    return Settings(
        database_url=_get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/hdfc_rm"),
        admin_database_url=_get("ADMIN_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"),
        ollama_host=_get("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=_get("OLLAMA_MODEL", "llama3.1"),
        ollama_timeout_s=float(_get("OLLAMA_TIMEOUT_S", "60")),
        intent_provider=_get("INTENT_PROVIDER", "ollama").strip().lower(),
        anthropic_api_key=_get("ANTHROPIC_API_KEY", ""),
        anthropic_model=_get("ANTHROPIC_MODEL", "claude-opus-5"),
        anthropic_effort=_get("ANTHROPIC_EFFORT", "low"),
        anthropic_max_tokens=int(_get("ANTHROPIC_MAX_TOKENS", "1024")),
        rm_name=_get("RM_NAME", "Priya Nair"),
        rm_title=_get("RM_TITLE", "Relationship Manager"),
        rm_bank=_get("RM_BANK", "HDFC Bank"),
    )


settings = load_settings()
