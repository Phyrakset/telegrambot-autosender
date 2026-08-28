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
    survey_results_csv: str = "survey_responses.csv"
    tverkar_results_csv: str = "tverkar_campaign_results.csv"
    default_video_path: str = os.getenv(
        "DEFAULT_VIDEO_PATH", 
        "video/TverKar&WN_using.mp4" if os.path.exists("video/TverKar&WN_using.mp4") else (
            "video/TverKar&WN_10MB.mp4" if os.path.exists("video/TverKar&WN_10MB.mp4") else "video/TverKar&WN.mp4"
        )
    )
    survey_timeout_seconds: int = int(os.getenv("SURVEY_TIMEOUT_SECONDS", "120"))

    # Workingna MySQL Database Settings
    workingna_db_host: str = os.getenv("WORKINGNA_DB_HOST", "127.0.0.1")
    workingna_db_port: int = int(os.getenv("WORKINGNA_DB_PORT", "3306"))
    workingna_db_user: str = os.getenv("WORKINGNA_DB_USER", "workingna")
    workingna_db_password: str = os.getenv("WORKINGNA_DB_PASSWORD", "Workingna#123")
    workingna_db_name: str = os.getenv("WORKINGNA_DB_NAME", "workingnadb_dev")
    workingna_admin_base_url: str = os.getenv(
        "WORKINGNA_ADMIN_BASE_URL", "https://admin.workingna.com/cms/job-seeker"
    )

    # TverKar PostgreSQL Database Settings
    tverkar_database_url: str = os.getenv(
        "TVERKAR_DATABASE_URL", 
        os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tverkar")
    )

    # Google Sheets Integration
    google_sheet_webhook_url: str = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "")
    google_sheet_url: str = os.getenv(
        "GOOGLE_SHEET_URL", 
        "https://docs.google.com/spreadsheets/d/1oOI6FGaXqfa_54vn7UV9FVLJrGTp3jmXRhJybYu5DfQ/edit?gid=1408716999#gid=1408716999"
    )

    # TverKar Campaign Default Templates (Khmer)
    tverkar_initial_message: str = (
        "សួស្តីបង [ឈ្មោះបេក្ខជន] 👋\n\n"
        "ខ្ញុំជា HR ពីខាងក្រុមហុន WORKINGNA , ឥឡូវនេះ WORKINGNA បានបង្កើតវេបសាយមួយឈ្មោះថា ធ្វេីការ- TverKar "
        "ដើម្បីជួយបងបង្កេីតប្រវត្តិរូបងាយស្រួល ហេីយខាងក្រុមហុនដែលត្រូវការរេីសបុគ្គលិក នឹងទាក់ទងមកបងផ្ទាល់តែម្តង។\n\n"
        "ហេីយដោយសារតែបង ធ្លាប់បានមាន CV ជាមួយខាងWORKINGNAរួចហេិយ ដើម្បីកុំឱ្យអ្នកត្រូវបំពេញព័ត៌មានម្ដងទៀត "
        "យើងសូមស្នើផ្ទេរប្រវត្តិរូបការងាររបស់អ្នកពី WORKINGNA ទៅកាន់ TverKar។ បន្ទាប់មក បងអាចបញ្ជាក់ និងធ្វើបច្ចុប្បន្នភាពព័ត៌មានរបស់បងបាន។\n\n"
        "****សូមបញ្ជាក់ថា ទោះបីជាបងមិនទាន់ចង់រកការងារក៏ដោយ ក៏បងនៅតែអាចបង្កេីតប្រវត្តិរូបបានដែរ ស្រួលពេលណាបងចង់ប្តូរការងារ "
        "បានគ្រាន់តែបេីកមុខងារនៅក្នុងប្រវត្តិរូបតែប៉ុណ្ណោះ គឺក្រុមហុនអាចទាក់ទងបងបានហេីយ ។\n\n"
        "តើអ្នកយល់ព្រមឱ្យយើងផ្ទេរប្រវត្តិរូបរបស់អ្នកទៅ TverKar ដែរឬទេ?\n\n"
        "1️⃣ យល់ព្រម\n"
        "2️⃣ មិនយល់ព្រមទេ\n"
        "👉 (សូមឆ្លើយតបដោយវាយលេខ ១ ឬ ២)"
    )

    @classmethod
    def reload(cls) -> "AppConfig":
        load_dotenv(override=True)
        video_p = os.getenv(
            "DEFAULT_VIDEO_PATH", 
            "video/TverKar&WN_using.mp4" if os.path.exists("video/TverKar&WN_using.mp4") else (
                "video/TverKar&WN_10MB.mp4" if os.path.exists("video/TverKar&WN_10MB.mp4") else "video/TverKar&WN.mp4"
            )
        )
        return cls(
            api_id=os.getenv("TELEGRAM_API_ID", ""),
            api_hash=os.getenv("TELEGRAM_API_HASH", ""),
            phone=os.getenv("TELEGRAM_PHONE", ""),
            default_country=os.getenv("DEFAULT_COUNTRY", "KH"),
            min_delay_seconds=int(os.getenv("MIN_DELAY_SECONDS", "2")),
            max_delay_seconds=int(os.getenv("MAX_DELAY_SECONDS", "2")),
            default_video_path=video_p,
            survey_timeout_seconds=int(os.getenv("SURVEY_TIMEOUT_SECONDS", "120")),
            workingna_db_host=os.getenv("WORKINGNA_DB_HOST", "127.0.0.1"),
            workingna_db_port=int(os.getenv("WORKINGNA_DB_PORT", "3306")),
            workingna_db_user=os.getenv("WORKINGNA_DB_USER", "workingna"),
            workingna_db_password=os.getenv("WORKINGNA_DB_PASSWORD", "Workingna#123"),
            workingna_db_name=os.getenv("WORKINGNA_DB_NAME", "workingnadb_dev"),
            workingna_admin_base_url=os.getenv("WORKINGNA_ADMIN_BASE_URL", "https://admin.workingna.com/cms/job-seeker"),
            tverkar_database_url=os.getenv("TVERKAR_DATABASE_URL", os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tverkar")),
            google_sheet_webhook_url=os.getenv("GOOGLE_SHEET_WEBHOOK_URL", ""),
            google_sheet_url=os.getenv(
                "GOOGLE_SHEET_URL", 
                "https://docs.google.com/spreadsheets/d/1oOI6FGaXqfa_54vn7UV9FVLJrGTp3jmXRhJybYu5DfQ/edit?gid=1408716999#gid=1408716999"
            ),
        )


config = AppConfig()
