import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from telethon import TelegramClient, events, custom, errors
from filelock import FileLock

from src.telebot.config import config
from src.telebot.core.migration import MigrationEngine
from src.telebot.core.storage import ACIDStorageManager
from src.telebot.db.workingna import find_candidate_by_phone, get_admin_url

logger = logging.getLogger("PersistentSurveyManager")

SURVEY_STATE_FILE = "survey_sessions.json"
SURVEY_STATE_LOCK = "survey_sessions.json.lock"

# 1-Tap Khmer Keyboard Buttons
BTN_CONSENT = [
    [custom.Button.text("✅ យល់ព្រម ", resize=True, single_use=True), custom.Button.text("❌ មិនយល់ព្រមទេ", resize=True, single_use=True)]
]
BTN_STATUS = [
    [custom.Button.text("នៅធ្វេី", resize=True, single_use=True), custom.Button.text("ឈប់ហេីយ", resize=True, single_use=True)]
]
BTN_URGENCY = [
    [custom.Button.text("បន្ទាន់", resize=True, single_use=True), custom.Button.text("កំពុងរកបណ្តេីរៗ", resize=True, single_use=True)]
]
BTN_CHANGE = [
    [custom.Button.text("ចង់", resize=True, single_use=True), custom.Button.text("មិនទាន់ចង់ទេ", resize=True, single_use=True)]
]
BTN_CLEAR = custom.Button.clear()

class PersistentSurveyManager:
    """
    Manages asynchronous, persistent, multi-step candidate survey conversations.
    Enables candidates to reply at ANY time (immediately, hours later, or next day)
    and guarantees exact resumption of their conversation state and automated migration.
    """
    _instance: Optional["PersistentSurveyManager"] = None
    _listener_registered = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PersistentSurveyManager, cls).__new__(cls)
        return cls._instance

    @staticmethod
    def _load_all_states() -> Dict[str, Any]:
        with FileLock(SURVEY_STATE_LOCK, timeout=10):
            if not os.path.exists(SURVEY_STATE_FILE):
                return {}
            try:
                with open(SURVEY_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read survey states: {e}")
                return {}

    @staticmethod
    def _save_all_states(states: Dict[str, Any]):
        with FileLock(SURVEY_STATE_LOCK, timeout=10):
            tmp_file = f"{SURVEY_STATE_FILE}.tmp_{os.getpid()}"
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(states, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_file, SURVEY_STATE_FILE)
            except Exception as e:
                logger.error(f"Failed to save survey states: {e}")
                if os.path.exists(tmp_file):
                    try:
                        os.remove(tmp_file)
                    except Exception:
                        pass

    @classmethod
    def get_user_session(cls, user_id: int) -> Optional[Dict[str, Any]]:
        states = cls._load_all_states()
        return states.get(str(user_id))

    @classmethod
    def register_initial_session(
        cls,
        user_id: int,
        phone: str,
        name: str,
        username: str,
        admin_url: Optional[str] = None,
        profile_data: Optional[Dict[str, Any]] = None
    ):
        """Initializes a new survey session when outreach is dispatched."""
        states = cls._load_all_states()
        states[str(user_id)] = {
            "user_id": user_id,
            "phone": phone,
            "name": name,
            "username": username,
            "step": "WAITING_CONSENT",
            "answers": {
                "consent": "",
                "employment_status": "",
                "job_preference": "",
                "expected_salary": "",
                "preferred_location": "",
                "raw_dialogue": [],
                "voice_files": []
            },
            "admin_url": admin_url or "",
            "profile_data": profile_data or {},
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        }
        cls._save_all_states(states)
        logger.info(f"Registered persistent session for {name} ({phone}, ID: {user_id})")

    @classmethod
    def attach_event_listener(cls, client: TelegramClient):
        """Attaches a background Telegram message event handler for 24/7 survey continuation."""
        if cls._listener_registered or not client:
            return

        @client.on(events.NewMessage(incoming=True))
        async def _on_incoming_message(event: events.NewMessage.Event):
            if not event.is_private:
                return

            user_id = event.sender_id
            session = cls.get_user_session(user_id)
            if not session:
                return

            step = session.get("step")
            if not step or step in ("COMPLETED", "DECLINED"):
                return

            await cls.process_user_reply(client, event, session)

        cls._listener_registered = True
        logger.info("✔ Persistent Survey Event Listener successfully attached to Telegram client.")

    @classmethod
    async def process_user_reply(cls, client: TelegramClient, event: events.NewMessage.Event, session: Dict[str, Any]):
        """Processes incoming user replies asynchronously, advancing survey and performing migration."""
        user_id = session["user_id"]
        phone = session.get("phone", "")
        name = session.get("name", "Candidate")
        step = session.get("step", "WAITING_CONSENT")
        answers = session.get("answers", {})

        # Extract voice note or text
        msg_text = ""
        if event.voice or event.audio:
            voice_dir = os.path.join(os.getcwd(), "voice_records")
            os.makedirs(voice_dir, exist_ok=True)
            safe_phone = phone.replace("+", "") or str(user_id)
            ts = int(event.date.timestamp()) if event.date else int(datetime.now().timestamp())
            voice_fn = f"voice_{safe_phone}_{step}_{ts}.ogg"
            voice_fp = os.path.join(voice_dir, voice_fn)
            await event.download_media(file=voice_fp)
            answers.setdefault("voice_files", []).append(voice_fp)
            msg_text = f"[Voice Note: {voice_fn}]"
        else:
            msg_text = (event.text or "").strip()

        answers.setdefault("raw_dialogue", []).append(f"User ({step}): {msg_text}")
        low_text = msg_text.lower()

        try:
            # -------------------------------------------------------------
            # STEP 0: WAITING_CONSENT
            # -------------------------------------------------------------
            if step == "WAITING_CONSENT":
                no_keywords = ["មិនយល់ព្រម", "មិនព្រម", "ទេ", "no", "n", "2", "❌", "អត់", "មិនទាន់", "cancel"]
                is_no = any(k in low_text for k in no_keywords) and not ("✅" in low_text or "យល់ព្រម" in low_text)

                if is_no:
                    answers["consent"] = "❌ មិនយល់ព្រម (Declined)"
                    session["step"] = "DECLINED"
                    closing_msg = "🙏 អរគុណច្រើនបង! យើងខ្ញុំនឹងមិនធ្វើការផ្ទេរប្រវត្តិរូបរបស់បងឡើយ។ ប្រសិនបើថ្ងៃក្រោយបងត្រូវការ អាចទាក់ទងមកកាន់យើងខ្ញុំបានគ្រប់ពេល។"
                    await client.send_message(user_id, closing_msg, buttons=BTN_CLEAR)
                    await cls._finalize_session(session, is_agreed=False, reason="User Declined Consent (❌ មិនយល់ព្រមទេ)")
                else:
                    answers["consent"] = "✅ យល់ព្រម (Agreed)"
                    session["step"] = "WAITING_STATUS"
                    q1_msg = (
                        "• តេីរាល់ថ្ងៃបងនៅធ្វេីការ រឺ ឈប់ហេីយ ?\n\n"
                        "1️⃣ នៅធ្វេី\n"
                        "2️⃣ ឈប់ហេីយ\n"
                        "👉 (សូមជ្រើសរើសដោយវាយលេខ ១ ឬ ២)"
                    )
                    await client.send_message(user_id, q1_msg, buttons=BTN_STATUS)

            # -------------------------------------------------------------
            # STEP 1: WAITING_STATUS
            # -------------------------------------------------------------
            elif step == "WAITING_STATUS":
                stopped_keywords = ["ឈប់", "ឈប់ហើយ", "ឈប់ហេីយ", "quit", "stop", "stopped", "unemployed", "2", "២"]
                is_stopped = any(k in low_text for k in stopped_keywords) and ("នៅ" not in low_text or "ឈប់" in low_text)

                if is_stopped:
                    answers["employment_status"] = "ឈប់ហេីយ"
                    session["step"] = "WAITING_URGENCY"
                    qa1_msg = (
                        "• ចឹងតេីបងត្រូវការងារបន្ទាន់ទេ ?\n\n"
                        "1️⃣ បន្ទាន់\n"
                        "2️⃣ កំពុងរកបណ្តេីរៗ\n"
                        "👉 (សូមជ្រើសរើសដោយវាយលេខ ១ ឬ ២)"
                    )
                    await client.send_message(user_id, qa1_msg, buttons=BTN_URGENCY)
                else:
                    answers["employment_status"] = "នៅធ្វេី"
                    session["step"] = "WAITING_JOB_CHANGE"
                    qb1_msg = (
                        "• ចឹងបងចង់ផ្លាស់ប្តូរការងាទេ ?\n\n"
                        "1️⃣ ចង់\n"
                        "2️⃣ មិនទាន់ចង់ទេ\n"
                        "👉 (សូមជ្រើសរើសដោយវាយលេខ ១ ឬ ២)"
                    )
                    await client.send_message(user_id, qb1_msg, buttons=BTN_CHANGE)

            # -------------------------------------------------------------
            # STEP 2A: WAITING_URGENCY (Branch A)
            # -------------------------------------------------------------
            elif step == "WAITING_URGENCY":
                answers["job_preference"] = "បន្ទាន់" if ("1" in low_text or "១" in low_text or "បន្ទាន់" in low_text) else "កំពុងរកបណ្តេីរៗ"
                session["step"] = "WAITING_SALARY"
                qa2_msg = "• សុំដឹងប្រាក់ខែដែលបងចង់បាន ៖\n👉 (ឧទាហរណ៍៖ $300, $500+)"
                await client.send_message(user_id, qa2_msg, buttons=BTN_CLEAR)

            # -------------------------------------------------------------
            # STEP 2B: WAITING_JOB_CHANGE (Branch B)
            # -------------------------------------------------------------
            elif step == "WAITING_JOB_CHANGE":
                answers["job_preference"] = "ចង់" if ("1" in low_text or "១" in low_text or "ចង់" in low_text) else "មិនទាន់ចង់ទេ"
                session["step"] = "WAITING_SALARY"
                qb2_msg = "• សុំដឹងប្រាក់ខែដែលបងចង់បាន ៖\n👉 (ឧទាហរណ៍៖ $400, $600+)"
                await client.send_message(user_id, qb2_msg, buttons=BTN_CLEAR)

            # -------------------------------------------------------------
            # STEP 3: WAITING_SALARY
            # -------------------------------------------------------------
            elif step == "WAITING_SALARY":
                answers["expected_salary"] = msg_text
                session["step"] = "WAITING_LOCATION"
                q3_msg = "• សុំប្រាប់ទីតាំងដែលអាចធ្វេីការបាន ៖\n👉 (ឧទាហរណ៍៖ ភ្នំពេញ, ទួលគោក, សៀមរាប...)"
                await client.send_message(user_id, q3_msg, buttons=BTN_CLEAR)

            # -------------------------------------------------------------
            # STEP 4: WAITING_LOCATION (Final Step)
            # -------------------------------------------------------------
            elif step == "WAITING_LOCATION":
                answers["preferred_location"] = msg_text
                session["step"] = "COMPLETED"
                closing_success_msg = (
                    "🎉 អរគុណច្រើនបងសម្រាប់ការឆ្លើយសំណួរ!\n\n"
                    "ព័ត៌មានរបស់បងត្រូវបានបញ្ជូនទៅកាន់ក្រុមការងារ ធ្វេីការ- TverKar រួចរាល់ហើយ។ "
                    "ក្រុមហ៊ុនដែលត្រូវនឹងជំនាញរបស់បង នឹងទាក់ទងមកបងក្នុងពេលឆាប់ៗនេះ។ ✨"
                )
                await client.send_message(user_id, closing_success_msg, buttons=BTN_CLEAR)
                await cls._finalize_session(session, is_agreed=True, reason="TverKar Campaign Completed Successfully")

            # Update session state
            session["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            states = cls._load_all_states()
            states[str(user_id)] = session
            cls._save_all_states(states)

        except Exception as err:
            logger.error(f"Error processing reply from user {user_id}: {err}")

    @classmethod
    async def _finalize_session(cls, session: Dict[str, Any], is_agreed: bool, reason: str):
        """Finalizes completed survey, performs ACID TverKar migration, and updates Google Sheets."""
        phone = session.get("phone", "")
        name = session.get("name", "")
        username = session.get("username", "")
        user_id = session.get("user_id")
        answers = session.get("answers", {})
        admin_url = session.get("admin_url", "")
        profile_data = session.get("profile_data")

        migration_status = "N/A"
        tverkar_worker_id = None

        if is_agreed:
            # Query Workingna DB if profile_data is not present
            if not profile_data:
                profile_data = find_candidate_by_phone(phone)
                if profile_data and not admin_url:
                    admin_url = profile_data.get("admin_url") or get_admin_url(profile_data.get("profile_id"))

            mig_stat, w_id, u_url = MigrationEngine.migrate_consenting_candidate(
                phone=phone,
                survey_answers=answers,
                telegram_user_info={"id": user_id, "username": username, "first_name": name},
                workingna_profile=profile_data
            )
            migration_status = mig_stat
            tverkar_worker_id = w_id
            if not admin_url and u_url:
                admin_url = u_url

        elif answers.get("consent") == "❌ មិនយល់ព្រម (Declined)":
            migration_status = "DECLINED_BY_USER"

        row_payload = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Phone (E.164)": phone,
            "Raw Phone": phone.replace("+855", "0") if phone.startswith("+855") else phone,
            "Candidate Name": name,
            "Username": username,
            "User ID": user_id,
            "Consent Transfer": answers.get("consent", ""),
            "Employment Status": answers.get("employment_status", ""),
            "Job Preference / Urgency": answers.get("job_preference", ""),
            "Expected Salary": answers.get("expected_salary", ""),
            "Preferred Location": answers.get("preferred_location", ""),
            "Voice Notes": "; ".join(answers.get("voice_files", [])),
            "Dialogue Summary": " | ".join(answers.get("raw_dialogue", [])),
            "Campaign Status": "Completed" if is_agreed else "Incomplete",
            "Notes": reason,
            "Workingna Admin URL": admin_url or "",
            "Migration Status": migration_status,
            "TverKar Worker ID": tverkar_worker_id or ""
        }

        # Atomically record to local CSV and sync to Google Sheets
        await ACIDStorageManager.record_campaign_result(row_payload)
        logger.info(f"✔ Finalized and migrated session for {name} ({phone})")
