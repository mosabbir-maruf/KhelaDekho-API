from datetime import timezone, timedelta
from pydantic_settings import BaseSettings

BDT = timezone(timedelta(hours=6))


class Settings(BaseSettings):
    v1_home_url: str = ""
    v2_home_url: str = "https://kickbd.org"
    sportzfy_target_url: str = "https://sportzfytvlive.xyz"
    sportzfy_playback_key: str = "ZESBtSlRTuF4Ac4k757OuasOWOA0W8LcqRn3SFgdInDoMyS8"
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.2 Safari/605.1.15"
    )
    request_timeout: float = 30.0
    scrape_interval_seconds: int = 60
    match_cache_ttl: int = 120
    channel_cache_ttl: int = 120
    vote_cache_ttl: int = 300
    redis_url: str = "redis://localhost:6379/0"
    max_retries: int = 3
    retry_backoff: float = 2.0
    rate_limit_rpm: int = 30

    debug: bool = False
    log_level: str = "INFO"
    allow_origins: list[str] = ["*"]
    secret_key: str
    signature_window_seconds: int = 60

    model_config = {"env_prefix": "KHELADEKHO_"}


settings = Settings()
