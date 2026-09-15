from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    model: str
    api_key: str | None
    base_url: str | None
    model_timeout_seconds: float = 30.0
    model_max_retries: int = 1

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://clinical_agent:clinical_dev_password@127.0.0.1:5432/clinical_trials",
            ),
            model=os.getenv("CLINICAL_AGENT_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY") or None,
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            model_timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "30")),
            model_max_retries=int(os.getenv("MODEL_MAX_RETRIES", "1")),
        )
