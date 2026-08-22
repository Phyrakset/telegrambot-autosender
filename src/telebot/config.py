import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class AppConfig:
    api_id: str = os.getenv("TELEGRAM_API_ID", "")
    api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
    phone: str = os.getenv("TELEGRAM_PHONE", "")
    default_country: str = os.getenv("DEFAULT_COUNTRY", "KH")
    min_delay_seconds: int = int(os.getenv("MIN_DELAY_SECONDS", "2"))
    max_delay_seconds: int = int(os.getenv("MAX_DELAY_SECONDS", "2"))
    session_name: str = "telebot_session"
    results_csv: str = "auto_send_results.csv"
    results_json: str = "auto_send_results.json"

    @classmethod
    def reload(cls) -> "AppConfig":
        load_dotenv(override=True)
        return cls(
            api_id=os.getenv("TELEGRAM_API_ID", ""),
            api_hash=os.getenv("TELEGRAM_API_HASH", ""),
            phone=os.getenv("TELEGRAM_PHONE", ""),
            default_country=os.getenv("DEFAULT_COUNTRY", "KH"),
            min_delay_seconds=int(os.getenv("MIN_DELAY_SECONDS", "2")),
            max_delay_seconds=int(os.getenv("MAX_DELAY_SECONDS", "2")),
        )

config = AppConfig()
