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

    # --- Decryption key for kickbd source URLs ---
    kickbd_decrypt_key: str = Field(default="999999859198", validation_alias="KICKBD_DECRYPT_KEY")
    proxy_required_patterns: str = Field(default="phantemlis.top,/papi/tv/playlist/", validation_alias="PROXY_REQUIRED_PATTERNS")

    # --- Auth: single shared API key across the project ---
    xkey: str = Field(default="", validation_alias="XKEY")

    model_config = {"extra": "ignore"}


settings = Settings()
