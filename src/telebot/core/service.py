import os
import sys
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple
from telethon import TelegramClient, functions, types, errors, custom
from src.telebot.config import config, AppConfig

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelegramService")

class TelegramService:
    _instance: Optional["TelegramService"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(TelegramService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, session_name: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.cfg = AppConfig.reload()
        self.session_name = session_name or self.cfg.session_name
        self.client: Optional[TelegramClient] = None
        self.phone_code_hash: Optional[str] = None
        self.pending_phone: Optional[str] = None
        self._media_cache: Dict[str, Any] = {}
        self._initialized = True

    def reload_env(self):
        self.cfg = AppConfig.reload()

    def _ensure_client(self):
        self.reload_env()
        if not self.cfg.api_id or not self.cfg.api_hash:
            raise ValueError("TELEGRAM_API_ID or TELEGRAM_API_HASH is missing. Please configure .env.")
        try:
            numeric_api_id = int(str(self.cfg.api_id).strip())
        except ValueError:
            raise ValueError("TELEGRAM_API_ID must be a numeric integer.")

        if not self.client:
            self.client = TelegramClient(self.session_name, numeric_api_id, str(self.cfg.api_hash).strip())

    async def connect(self):
        self._ensure_client()
        if not self.client.is_connected():
            await self.client.connect()
        return self.client

    async def is_authenticated(self) -> bool:
        try:
            await self.connect()
            return await self.client.is_user_authorized()
        except Exception:
            return False

    async def get_me_info(self) -> Optional[Dict[str, Any]]:
        if not await self.is_authenticated():
            return None
        me = await self.client.get_me()
        return {
            "id": me.id,
            "first_name": me.first_name or "",
            "last_name": me.last_name or "",
            "username": me.username or "",
            "phone": me.phone or "",
            "premium": getattr(me, "premium", False)
        }

    async def send_auth_code(self, phone: str) -> Tuple[bool, str]:
        await self.connect()
        clean_phone = phone.strip()
        try:
            result = await self.client.send_code_request(clean_phone)
            self.phone_code_hash = result.phone_code_hash
            self.pending_phone = clean_phone
            return True, f"Code sent to {clean_phone}. Check your Telegram app or SMS."
        except Exception as e:
            return False, f"Failed to send code: {str(e)}"

    async def sign_in_with_code(self, code: str, password: Optional[str] = None) -> Tuple[bool, str, bool]:
        if not self.pending_phone or not self.phone_code_hash:
            return False, "No pending login found. Request verification code first.", False
        
        await self.connect()
        try:
            await self.client.sign_in(
                phone=self.pending_phone,
                code=code.strip(),
                phone_code_hash=self.phone_code_hash
            )
            me = await self.get_me_info()
            return True, f"Logged in successfully as {me['first_name']} (@{me['username'] or 'NoUser'})", False
        except errors.SessionPasswordNeededError:
            if password:
                return await self.sign_in_with_password(password)
            return False, "Two-Step Verification (2FA) is enabled on this account. Please enter your 2FA password.", True
        except Exception as e:
            return False, f"Sign-in failed: {str(e)}", False

    async def sign_in_with_password(self, password: str) -> Tuple[bool, str, bool]:
        await self.connect()
        try:
            await self.client.sign_in(password=password.strip())
            me = await self.get_me_info()
            return True, f"Logged in successfully as {me['first_name']} (@{me['username'] or 'NoUser'})", False
        except Exception as e:
            return False, f"2FA verification failed: {str(e)}", True

    async def delete_contact(self, user_id: int):
        try:
            if self.client and self.client.is_connected():
                await self.client(functions.contacts.DeleteContactsRequest(id=[types.InputUser(user_id=user_id, access_hash=0)]))
        except Exception as e:
            logger.debug(f"Contact cleanup notice (ignored): {e}")

    async def check_phone_registration(
        self, 
        phone_e164: str, 
        cleanup_contact: bool = True
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Any]]:
        """
        Checks whether a phone number is registered on Telegram.
        Returns: (is_registered, user_info_dict, user_entity)
        """
        await self.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized. Please log in first.")

        contact = types.InputPhoneContact(
            client_id=0,
            phone=phone_e164,
            first_name="",
            last_name=""
        )

        try:
            result = await self.client(functions.contacts.ImportContactsRequest([contact]))
            if result.users:
                user = result.users[0]
                
                # Fetch genuine Telegram user profile information
                user_info = {
                    "id": user.id,
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "username": user.username or "",
                    "phone": user.phone or phone_e164,
                    "is_bot": getattr(user, "bot", False),
                    "is_deleted": getattr(user, "deleted", False),
                    "status": type(user.status).__name__ if user.status else "Unknown"
                }

                if cleanup_contact:
                    try:
                        await self.client(functions.contacts.DeleteContactsRequest(id=[user.id]))
                    except Exception as e:
                        logger.debug(f"Contact cleanup notice: {e}")

                return True, user_info, user
            else:
                return False, None, None

        except errors.FloodWaitError as e:
            logger.warning(f"Telegram FloodWait: Required to wait {e.seconds} seconds.")
            raise e
        except errors.PhoneNumberInvalidError:
            logger.error(f"Phone number {phone_e164} is invalid.")
            return False, {"error": "Invalid phone number"}, None
        except Exception as e:
            logger.error(f"Error checking {phone_e164}: {e}")
            return False, {"error": str(e)}, None

    async def send_message_to_user(
        self, 
        target_entity: Any, 
        message_text: str,
        buttons: Any = None
    ) -> Tuple[bool, str, str]:
        """
        Sends a direct message to a resolved Telegram user entity with optional buttons.
        Returns: (success: bool, status_type: str, details_or_msg_id: str)
        status_type can be: 'DELIVERED', 'PRIVACY_RESTRICTED', 'DEACTIVATED', 'FLOOD_LIMIT', 'ERROR'
        """
        await self.connect()
        try:
            sent_msg = await self.client.send_message(target_entity, message_text, buttons=buttons)
            return True, "DELIVERED", str(sent_msg.id)
        except errors.UserPrivacyRestrictedError:
            return False, "PRIVACY_RESTRICTED", "Recipient privacy blocks stranger messages"
        except (errors.UserDeactivatedError, errors.UserDeactivatedBanError):
            return False, "DEACTIVATED", "Account has been deactivated"
        except errors.PeerFloodError:
            return False, "FLOOD_LIMIT", "Sender account rate limited by Telegram"
        except errors.FloodWaitError as e:
            return False, "FLOOD_WAIT", f"FloodWait: required wait {e.seconds}s"
        except Exception as e:
            return False, "ERROR", str(e)

    async def upload_and_cache_video(self, video_path: str, progress_callback=None) -> Any:
        """
        Uploads video to Telegram once (Saved Messages cache) and returns media handle.
        This prevents re-uploading large video files for every single recipient.
        """
        await self.connect()
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file '{video_path}' does not exist.")
        
        file_stat = os.stat(video_path)
        cache_key = f"{os.path.abspath(video_path)}_{file_stat.st_mtime}_{file_stat.st_size}"
        
        if cache_key in self._media_cache:
            return self._media_cache[cache_key]
        
        logger.info(f"Uploading video '{video_path}' to cache ({file_stat.st_size / (1024*1024):.1f} MB)...")
        
        # Upload once to self (Saved Messages) to obtain a permanent MessageMedia reference
        saved_msg = await self.client.send_file(
            "me",
            video_path,
            caption="[TeleSender Pro Cached Asset - Do Not Delete]",
            supports_streaming=True,
            progress_callback=progress_callback
        )
        
        if saved_msg and saved_msg.media:
            self._media_cache[cache_key] = saved_msg.media
            logger.info("Video successfully uploaded and cached in Telegram cloud.")
            return saved_msg.media
        
        # Fallback to direct path
        self._media_cache[cache_key] = video_path
        return video_path

    async def send_media_to_user(
        self,
        target_entity: Any,
        media_item: Any,
        caption: str = "",
        buttons: Any = None
    ) -> Tuple[bool, str, str]:
        """
        Sends cached video/media to a target user with optional caption and interactive buttons.
        Returns: (success: bool, status_type: str, details_or_msg_id: str)
        """
        await self.connect()
        try:
            sent_msg = await self.client.send_file(
                target_entity,
                media_item,
                caption=caption if caption else None,
                buttons=buttons,
                supports_streaming=True
            )
            return True, "DELIVERED", str(sent_msg.id)
        except errors.UserPrivacyRestrictedError:
            return False, "PRIVACY_RESTRICTED", "Recipient privacy blocks stranger media/messages"
        except (errors.UserDeactivatedError, errors.UserDeactivatedBanError):
            return False, "DEACTIVATED", "Account has been deactivated"
        except errors.PeerFloodError:
            return False, "FLOOD_LIMIT", "Sender account rate limited by Telegram"
        except errors.FloodWaitError as e:
            return False, "FLOOD_WAIT", f"FloodWait: required wait {e.seconds}s"
        except Exception as e:
            return False, "ERROR", str(e)



    async def conduct_tverkar_campaign_session(
        self,
        target_entity: Any,
        initial_message: str = "",
        media: Optional[Any] = None,
        timeout: int = 180,
        phone_identifier: str = "",
        user_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Executes the interactive TverKar CV Transfer Survey branching workflow
        with 1-Tap Interactive Reply Keyboard Buttons:
        1. Consent: [✅ យល់ព្រម] vs [❌ មិនយល់ព្រមទេ]
        2. Status: [🏢 នៅធ្វេី] vs [🚪 ឈប់ហេីយ]
        3. Branch A: [⚡ បន្ទាន់] vs [🔍 កំពុងរកបណ្តេីរៗ] -> Salary -> Location
        4. Branch B: [🔄 ចង់] vs [⏳ មិនទាន់ចង់ទេ] -> Salary -> Location
        """
        await self.connect()
        answers: Dict[str, Any] = {
            "consent": "",
            "employment_status": "",
            "job_preference": "",
            "expected_salary": "",
            "preferred_location": "",
            "raw_dialogue": [],
            "voice_files": []
        }

        voice_dir = os.path.join(os.getcwd(), "voice_records")
        os.makedirs(voice_dir, exist_ok=True)

        # 1-Tap Interactive Buttons Definitions (Exact Khmer from Pisey Khun)
        btn_consent = [
            [custom.Button.text("✅ យល់ព្រម ", resize=True, single_use=True), custom.Button.text("❌ មិនយល់ព្រមទេ", resize=True, single_use=True)]
        ]
        btn_status = [
            [custom.Button.text("នៅធ្វេី", resize=True, single_use=True), custom.Button.text("ឈប់ហេីយ", resize=True, single_use=True)]
        ]
        btn_urgency = [
            [custom.Button.text("បន្ទាន់", resize=True, single_use=True), custom.Button.text("កំពុងរកបណ្តេីរៗ", resize=True, single_use=True)]
        ]
        btn_change = [
            [custom.Button.text("ចង់", resize=True, single_use=True), custom.Button.text("មិនទាន់ចង់ទេ", resize=True, single_use=True)]
        ]
        btn_clear = custom.Button.clear()

        async def _extract_response_text(resp, step_tag: str) -> str:
            if resp.voice or resp.audio:
                safe_phone = phone_identifier.replace("+", "") or "unknown"
                ts = int(resp.date.timestamp()) if hasattr(resp, "date") and resp.date else 0
                voice_fn = f"voice_{safe_phone}_{step_tag}_{ts}.ogg"
                voice_fp = os.path.join(voice_dir, voice_fn)
                await resp.download_media(file=voice_fp)
                answers["voice_files"].append(voice_fp)
                return f"[Voice Note: {voice_fn}]"
            return (resp.text or "[Non-text response]").strip()

        try:
            async with self.client.conversation(target_entity, timeout=timeout) as conv:
                # Send Initial outreach message / video if provided
                if initial_message or media:
                    if media:
                        await conv.send_file(media, caption=initial_message, buttons=btn_consent)
                    else:
                        await conv.send_message(initial_message, buttons=btn_consent)

                # --- STEP 0: Wait for initial Consent response ---
                resp0 = await conv.get_response()
                ans0_text = await _extract_response_text(resp0, "consent")
                answers["raw_dialogue"].append(f"User (Consent): {ans0_text}")
                
                # Check consent (Khmer & English fuzzy matching)
                low_ans0 = ans0_text.lower()
                no_keywords = ["មិនយល់ព្រម", "មិនព្រម", "ទេ", "no", "n", "2", "❌", "អត់", "មិនទាន់", "cancel"]
                is_no = any(k in low_ans0 for k in no_keywords) and not ("✅" in low_ans0 or "យល់ព្រម" in low_ans0)

                if is_no:
                    answers["consent"] = "❌ មិនយល់ព្រម (Declined)"
                    answers["employment_status"] = "N/A"
                    answers["job_preference"] = "N/A"
                    answers["expected_salary"] = "N/A"
                    answers["preferred_location"] = "N/A"
                    closing_no_msg = "🙏 អរគុណច្រើនបង! យើងខ្ញុំនឹងមិនធ្វើការផ្ទេរប្រវត្តិរូបរបស់បងឡើយ។ ប្រសិនបើថ្ងៃក្រោយបងត្រូវការ អាចទាក់ទងមកកាន់យើងខ្ញុំបានគ្រប់ពេល។"
                    await conv.send_message(closing_no_msg, buttons=btn_clear)
                    return True, answers, "User Declined Consent (❌ មិនយល់ព្រមទេ)"

                answers["consent"] = "✅ យល់ព្រម (Agreed)"

                # --- STEP 1: Employment Status ---
                q1_msg = (
                    "• តេីរាល់ថ្ងៃបងនៅធ្វេីការ រឺ ឈប់ហេីយ ?\n\n"
                    "1️⃣ នៅធ្វេី\n"
                    "2️⃣ ឈប់ហេីយ\n"
                    "👉 (សូមជ្រើសរើសដោយវាយលេខ ១ ឬ ២)"
                )
                await conv.send_message(q1_msg, buttons=btn_status)
                resp1 = await conv.get_response()
                ans1_text = await _extract_response_text(resp1, "employment_status")
                answers["raw_dialogue"].append(f"User (Status): {ans1_text}")

                low_ans1 = ans1_text.lower()
                stopped_keywords = ["ឈប់", "ឈប់ហើយ", "ឈប់ហេីយ", "quit", "stop", "stopped", "unemployed", "2", "២"]
                is_stopped = any(k in low_ans1 for k in stopped_keywords) and ("នៅ" not in low_ans1 or "ឈប់" in low_ans1)

                if is_stopped:
                    answers["employment_status"] = "ឈប់ហេីយ"

                    # Sub-branch A1: Urgency
                    qa1_msg = (
                        "• ចឹងតេីបងត្រូវការងារបន្ទាន់ទេ ?\n\n"
                        "1️⃣ បន្ទាន់\n"
                        "2️⃣ កំពុងរកបណ្តេីរៗ\n"
                        "👉 (សូមជ្រើសរើសដោយវាយលេខ ១ ឬ ២)"
                    )
                    await conv.send_message(qa1_msg, buttons=btn_urgency)
                    respa1 = await conv.get_response()
                    ansa1_text = await _extract_response_text(respa1, "urgency")
                    answers["raw_dialogue"].append(f"User (Urgency): {ansa1_text}")
                    answers["job_preference"] = "បន្ទាន់" if ("1" in ansa1_text or "១" in ansa1_text or "បន្ទាន់" in ansa1_text) else "កំពុងរកបណ្តេីរៗ"

                    # Sub-branch A2: Expected Salary
                    qa2_msg = "• សុំដឹងប្រាក់ខែដែលបងចង់បាន ៖\n👉 (ឧទាហរណ៍៖ $300, $500+)"
                    await conv.send_message(qa2_msg, buttons=btn_clear)
                    respa2 = await conv.get_response()
                    ansa2_text = await _extract_response_text(respa2, "salary")
                    answers["raw_dialogue"].append(f"User (Salary): {ansa2_text}")
                    answers["expected_salary"] = ansa2_text

                    # Sub-branch A3: Preferred Location
                    qa3_msg = "• សុំប្រាប់ទីតាំងដែលអាចធ្វេីការបាន ៖\n👉 (ឧទាហរណ៍៖ ភ្នំពេញ, ទួលគោក, សៀមរាប...)"
                    await conv.send_message(qa3_msg, buttons=btn_clear)
                    respa3 = await conv.get_response()
                    ansa3_text = await _extract_response_text(respa3, "location")
                    answers["raw_dialogue"].append(f"User (Location): {ansa3_text}")
                    answers["preferred_location"] = ansa3_text

                else:
                    answers["employment_status"] = "នៅធ្វេី"

                    # Sub-branch B1: Job Change Intention
                    qb1_msg = (
                        "• ចឹងបងចង់ផ្លាស់ប្តូរការងាទេ ?\n\n"
                        "1️⃣ ចង់\n"
                        "2️⃣ មិនទាន់ចង់ទេ\n"
                        "👉 (សូមជ្រើសរើសដោយវាយលេខ ១ ឬ ២)"
                    )
                    await conv.send_message(qb1_msg, buttons=btn_change)
                    respb1 = await conv.get_response()
                    ansb1_text = await _extract_response_text(respb1, "job_change")
                    answers["raw_dialogue"].append(f"User (JobChange): {ansb1_text}")
                    answers["job_preference"] = "ចង់" if ("1" in ansb1_text or "១" in ansb1_text or "ចង់" in ansb1_text and "មិន" not in ansb1_text) else "មិនទាន់ចង់ទេ"

                    # Sub-branch B2: Expected Salary
                    qb2_msg = "• សុំដឹងប្រាក់ខែដែលបងចង់បាន ៖\n👉 (ឧទាហរណ៍៖ $300, $500+)"
                    await conv.send_message(qb2_msg, buttons=btn_clear)
                    respb2 = await conv.get_response()
                    ansb2_text = await _extract_response_text(respb2, "salary")
                    answers["raw_dialogue"].append(f"User (Salary): {ansb2_text}")
                    answers["expected_salary"] = ansb2_text

                    # Sub-branch B3: Preferred Location
                    qb3_msg = (
                        "• សុំប្រាប់ទីតាំងដែលអាចធ្វេីការបាន ថ្ងៃក្រោយពេលបងចង់ផ្លាស់ប្តូរ ងាយស្រួលរកតែម្តង ៖\n"
                        "👉 (ឧទាហរណ៍៖ ភ្នំពេញ, ទួលគោក, សៀមរាប...)"
                    )
                    await conv.send_message(qb3_msg, buttons=btn_clear)
                    respb3 = await conv.get_response()
                    ansb3_text = await _extract_response_text(respb3, "location")
                    answers["raw_dialogue"].append(f"User (Location): {ansb3_text}")
                    answers["preferred_location"] = ansb3_text

                # Final wrap-up / thank you message
                wrapup_msg = (
                    "🙏 អរគុណច្រើនបង! ព័ត៌មានរបស់បងត្រូវបានកត់ត្រាទុកក្នុងប្រព័ន្ធ TverKar រួចរាល់។\n"
                    "ក្រុមការងារយើងនឹងជូនដំណឹងនៅពេលមានឱកាសការងារល្អៗជូនបង!"
                )
                await conv.send_message(wrapup_msg, buttons=btn_clear)
                return True, answers, "TverKar Campaign Completed Successfully"

        except asyncio.TimeoutError:
            return False, answers, f"Survey Timeout (Candidate did not reply within {timeout}s)"
        except errors.UserPrivacyRestrictedError:
            return False, answers, "Privacy Restricted: Cannot receive survey messages"
        except errors.PeerFloodError:
            return False, answers, "PeerFlood limit reached during campaign"
        except Exception as e:
            return False, answers, f"Campaign survey error: {str(e)}"

    def format_message_template(self, template: str, user_info: Optional[Dict[str, Any]] = None) -> str:
        if not template:
            return ""
        first_name = (user_info.get("first_name") if user_info else "") or ""
        last_name = (user_info.get("last_name") if user_info else "") or ""
        full_name = f"{first_name} {last_name}".strip()
        disp_name = full_name if full_name else (user_info.get("username") if user_info and user_info.get("username") else "បង")
        username = f"@{user_info.get('username')}" if (user_info and user_info.get("username")) else ""
        
        msg = template
        # Replace placeholders for Khmer and standard formats
        msg = msg.replace("[ឈ្មោះបេក្ខជន]", disp_name)
        msg = msg.replace("{name}", disp_name)
        msg = msg.replace("{candidate_name}", disp_name)
        msg = msg.replace("{username}", username)
        return msg.strip()

    async def disconnect(self):
        if self.client and self.client.is_connected():
            await self.client.disconnect()

