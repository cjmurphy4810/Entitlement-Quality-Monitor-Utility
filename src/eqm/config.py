"""Application config loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EQM_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("./data"))
    bearer_token: str
    git_push_enabled: bool = False
    git_push_token: str | None = None
    git_remote_url: str | None = None

    @property
    def entitlements_path(self) -> Path:
        return self.data_dir / "entitlements.json"

    @property
    def hr_employees_path(self) -> Path:
        return self.data_dir / "hr_employees.json"

    @property
    def cmdb_resources_path(self) -> Path:
        return self.data_dir / "cmdb_resources.json"

    @property
    def assignments_path(self) -> Path:
        return self.data_dir / "assignments.json"

    @property
    def violations_path(self) -> Path:
        return self.data_dir / "violations.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
