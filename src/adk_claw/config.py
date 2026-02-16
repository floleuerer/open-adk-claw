from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    telegram_bot_token: str
    google_api_key: str
    model_name: str = "gemini-3-flash-preview"
    app_name: str = "adk-claw"
    base_dir: Path = Path("workspace")
    debounce_seconds: float = 2.0
    heartbeat_check_interval: float = 60.0
    session_idle_timeout: float = 1800.0
    admin_chat_id: str = ""
    browser_service_url: str = "http://browser:8000"
    sandbox_service_url: str = "http://sandbox:8000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    gmail_credentials_file: str = ""
    gmail_token_file: str = "/secrets/gmail_token.json"
    gmail_channel_enabled: bool = True
    gmail_poll_interval: float = 30.0
    gmail_label_filter: str = ""
    email_allowlist: str = ""
    email_guardrail_model: str = "gemini-2.5-flash-lite"
    execution_guardrail_model: str = "gemini-2.5-flash-lite"
    execution_guardrail_enabled: bool = True
