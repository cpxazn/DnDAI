from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    database_path: str = Field(default="data/app/mydnd.sqlite3", alias="DATABASE_PATH")
    llm_base_url: str = Field(default="http://127.0.0.1:8080/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gemma-4-31B-it-Q4_K_S-Beellama", alias="LLM_MODEL")
    llm_timeout_seconds: int = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    rules_source_dir: str = Field(default="data/rules/source", alias="RULES_SOURCE_DIR")
    rules_jsonl_path: str = Field(
        default="data/rules/processed/srd_5_2_1_chunks.jsonl",
        alias="RULES_JSONL_PATH",
    )
    lore_source_dir: str = Field(default="data/lore/source", alias="LORE_SOURCE_DIR")
    lore_jsonl_path: str = Field(
        default="data/lore/processed/lore_chunks.jsonl",
        alias="LORE_JSONL_PATH",
    )
    enable_chat_debug: bool = Field(default=False, alias="ENABLE_CHAT_DEBUG")
    enable_memory_debug: bool = Field(default=False, alias="ENABLE_MEMORY_DEBUG")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_file(self) -> Path:
        return self._resolve_path(self.database_path)

    @property
    def rules_jsonl_file(self) -> Path:
        return self._resolve_path(self.rules_jsonl_path)

    @property
    def rules_source_path(self) -> Path:
        return self._resolve_path(self.rules_source_dir)

    @property
    def lore_source_path(self) -> Path:
        return self._resolve_path(self.lore_source_dir)

    @property
    def lore_jsonl_file(self) -> Path:
        return self._resolve_path(self.lore_jsonl_path)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return REPO_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
