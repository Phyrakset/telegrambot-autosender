import os
import sys
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple
from dotenv import load_dotenv
from telethon import TelegramClient, functions, types, errors

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelegramService")

class TelegramService:
    _instance: Optional["TelegramService"] = None

    def __new__(cls, *args, **kwargs):
        # Singleton pattern to reuse the connected client session across UI & background tasks
        if cls._instance is None:
            cls._instance = super(TelegramService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, session_name: str = "telebot_session"):
        if getattr(self, "_initialized", False):
            return
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")
        self.phone = os.getenv("TELEGRAM_PHONE")
        self.session_name = session_name
        self.client: Optional[TelegramClient] = None
        self.phone_code_hash: Optional[str] = None
        self.pending_phone: Optional[str] = None
        self.is_stopping: bool = False
        self._initialized = True

    def reload_env(self):
        """Reloads credentials from .env file."""
        load_dotenv(override=True)
        self.api_id = os.getenv("TELEGRAM_API_ID")
        self.api_hash = os.getenv("TELEGRAM_API_HASH")
        self.phone = os.getenv("TELEGRAM_PHONE")

    def _ensure_client(self):
        self.reload_env()
        if not self.api_id or not self.api_hash:
            raise ValueError("TELEGRAM_API_ID or TELEGRAM_API_HASH is missing. Please configure .env.")
        try:
            numeric_api_id = int(str(self.api_id).strip())
        except ValueError:
            raise ValueError("TELEGRAM_API_ID must be a numeric integer.")

        if not self.client:
            self.client = TelegramClient(self.session_name, numeric_api_id, str(self.api_hash).strip())

    async def connect(self):
        """Initializes and connects the MTProto client session."""
        self._ensure_client()
        if not self.client.is_connected():
            await self.client.connect()
        return self.client

    async def is_authenticated(self) -> bool:
        """Checks if the client session is currently authorized."""
        try:
            await self.connect()
            return await self.client.is_user_authorized()
        except Exception:
            return False

    async def get_me_info(self) -> Optional[Dict[str, Any]]:
        """Returns details about the logged-in Telegram user."""
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
        """Sends an authentication code to the specified phone number via Telegram."""
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
        """
        Signs in with received code.
        Returns: (success: bool, message: str, needs_password: bool)
        """
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
        """Signs in with 2FA password."""
        await self.connect()
        try:
            await self.client.sign_in(password=password.strip())
            me = await self.get_me_info()
            return True, f"Logged in successfully as {me['first_name']} (@{me['username'] or 'NoUser'})", False
        except Exception as e:
            return False, f"2FA verification failed: {str(e)}", True

    async def delete_contact(self, user_id: int):
        """Safely removes an imported temporary contact from Telegram contacts."""
        try:
            if self.client and self.client.is_connected():
                await self.client(functions.contacts.DeleteContactsRequest(id=[types.InputUser(user_id=user_id, access_hash=0)]))
        except Exception as e:
            logger.debug(f"Contact cleanup exception (ignored): {e}")

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
            first_name="TempCheck",
            last_name=""
        )

        try:
            result = await self.client(functions.contacts.ImportContactsRequest([contact]))
            if result.users:
                user = result.users[0]
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
        message_text: str
    ) -> Tuple[bool, Optional[str]]:
        """Sends a direct message to a resolved Telegram user entity."""
        await self.connect()
        try:
            sent_msg = await self.client.send_message(target_entity, message_text)
            return True, str(sent_msg.id)
        except errors.FloodWaitError as e:
            return False, f"FloodWaitError: {e.seconds}s"
        except errors.PeerFloodError:
            return False, "PeerFloodError: Restricted by Telegram Anti-Spam"
        except errors.UserPrivacyRestrictedError:
            return False, "UserPrivacyRestrictedError: Blocked by user privacy settings"
        except Exception as e:
            return False, str(e)

    def format_message_template(self, template: str, user_info: Optional[Dict[str, Any]] = None) -> str:
        """
        Renders message template with optional variables:
        - {name}: recipient first name or 'Valued Customer'
        - {username}: recipient @username or ''
        """
        if not template:
            return ""
        first_name = (user_info.get("first_name") if user_info else "") or ""
        username = f"@{user_info.get('username')}" if (user_info and user_info.get("username")) else ""
        
        msg = template.replace("{name}", first_name).replace("{username}", username)
        return msg.strip()

    async def disconnect(self):
        if self.client and self.client.is_connected():
            await self.client.disconnect()

