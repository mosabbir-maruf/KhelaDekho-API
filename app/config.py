from datetime import timezone, timedelta

from pydantic import Field
from pydantic_settings import BaseSettings

BDT = timezone(timedelta(hours=6))


class Settings(BaseSettings):
    # --- Upstream providers ---
    # All upstream base URLs come from env, never hardcoded in source.
    #   V1 = score provider, V2 = kickbd, V4 = proxybdix
    v1_home_url: str = Field(default="", validation_alias="V1_HOME_URL")
    v2_home_url: str = Field(default="", validation_alias="V2_HOME_URL")
    v4_home_url: str = Field(default="", validation_alias="V4_HOME_URL")
    v5_home_url: str = Field(default="", validation_alias="V5_HOME_URL")

    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.2 Safari/605.1.15"
    )

    # --- Runtime ---
    debug: bool = False
    log_level: str = "INFO"
    allow_origins: list[str] = ["*"]

    # --- Auth: single shared API key across the project ---
    xkey: str = Field(default="", validation_alias="XKEY")

    model_config = {"env_prefix": "KHELADEKHO_", "extra": "ignore"}


settings = Settings()
