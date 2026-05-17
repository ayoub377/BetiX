from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Explicitly load the .env file
load_dotenv(".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env",extra="allow")
    RATE_LIMITING_ENABLE: bool = False
    RATE_LIMITING_FREQUENCY: str = "2/3seconds"

    # Rate limiting configuration
    DEFAULT_MAX_REQUESTS: int = 50  # Increased to 20 for development
    DEFAULT_RESET_DURATION: int = 86400  # 24 hours in seconds

    # ── Telegram alerts ─────────────────────────────────────────────
    # BOT_TOKEN comes from @BotFather. WEBHOOK_SECRET is the shared secret
    # we set when registering the webhook with Telegram (sent back to us
    # in the X-Telegram-Bot-Api-Secret-Token header) so we can reject
    # forged webhook calls.
    # PUBLIC_BASE_URL is used to build the t.me deep-link and (optionally)
    # to auto-register the webhook URL — e.g. "https://api.sharperbets.com".
    # ALERT_COOLDOWN_SECONDS rate-limits re-alerts on the same
    # match+market+direction so a flapping odds line doesn't spam the user.
    # MIN_THRESHOLD_PCT / MAX_THRESHOLD_PCT bound what users can set; very
    # small thresholds would alert on every tick, very large ones never fire.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""  # e.g. "SharperBetsBot" (no @)
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_PUBLIC_BASE_URL: str = ""
    TELEGRAM_ALERT_COOLDOWN_SECONDS: int = 3600  # 60 min between same-direction alerts
    TELEGRAM_MIN_THRESHOLD_PCT: float = 1.0
    TELEGRAM_MAX_THRESHOLD_PCT: float = 50.0
    TELEGRAM_LINK_TOKEN_TTL_SECONDS: int = 600  # 10 minutes to complete deep-link


settings = Settings()
