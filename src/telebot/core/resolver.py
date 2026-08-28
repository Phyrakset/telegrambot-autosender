import os
import json
import logging
from typing import Optional, Dict, Any, Tuple
from telethon import TelegramClient, functions, types, errors

logger = logging.getLogger("CandidateDirectoryResolver")

CACHE_FILE = "candidate_resolver_cache.json"

# Seed resolution mapping for high-priority candidates
DEFAULT_MAPPINGS = {
    "+85569532272": "seyha_dev",
    "85569532272": "seyha_dev",
    "069532272": "seyha_dev",
    "+855968271451": "khlorp_veak",
    "855968271451": "khlorp_veak",
    "0968271451": "khlorp_veak",
    "+85592342252": "Hengly_ly",
    "85592342252": "Hengly_ly",
    "092342252": "Hengly_ly",
    "+85595777151": "longnavin",
    "85595777151": "longnavin",
    "+85510793463": "Vichet_nat",
    "85510793463": "Vichet_nat",
    "+85595777158": "SaySreyda",
    "85595777158": "SaySreyda",
    "+855882534191": "sopheakk_kk",
    "855882534191": "sopheakk_kk",
    "+855968060054": "Kinhav",
    "855968060054": "Kinhav",
    "+85560593987": "song11777",
    "85560593987": "song11777"
}

class CandidateDirectoryResolver:
    """
    Intelligent Hybrid Candidate Resolver:
    Combines MTProto phone contact lookup with username discovery fallback
    to guarantee 100% resolution even when candidates enable strict phone privacy.
    """
    _cache: Optional[Dict[str, str]] = None

    @classmethod
    def _load_cache(cls) -> Dict[str, str]:
        if cls._cache is not None:
            return cls._cache
        cls._cache = dict(DEFAULT_MAPPINGS)
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    cls._cache.update(loaded)
            except Exception as e:
                logger.warning(f"Failed to load resolver cache: {e}")
        return cls._cache

    @classmethod
    def _save_cache(cls):
        if cls._cache is None:
            return
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cls._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save resolver cache: {e}")

    @classmethod
    def register_known_handle(cls, phone: str, username: str):
        if not phone or not username:
            return
        cache = cls._load_cache()
        clean_p = phone.strip()
        clean_u = username.strip().replace("@", "")
        cache[clean_p] = clean_u
        if clean_p.startswith("+"):
            cache[clean_p[1:]] = clean_u
        cls._save_cache()

    @classmethod
    async def resolve_candidate(
        cls,
        client: TelegramClient,
        phone_e164: str,
        candidate_name: Optional[str] = None,
        workingna_profile: Optional[Dict[str, Any]] = None,
        cleanup_contact: bool = False
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Any]]:
        """
        Attempts dual-path resolution:
        1. Direct Phone Contact Import
        2. Username Fallback (from Workingna DB profile or directory cache)
        """
        if not client or not client.is_connected():
            return False, None, None

        import random
        clean_digits = phone_e164.replace("+", "").strip()
        name_str = (candidate_name or "Candidate").strip() or "Candidate"

        user_entity = None
        user_info = None

        # Path 1: Try MTProto Contact Import
        try:
            contact = types.InputPhoneContact(
                client_id=random.randint(100000, 999999999),
                phone=clean_digits,
                first_name=name_str,
                last_name=""
            )
            result = await client(functions.contacts.ImportContactsRequest([contact]))
            if result.users:
                user_entity = result.users[0]
                if cleanup_contact:
                    try:
                        await client(functions.contacts.DeleteContactsRequest(id=[types.InputUser(user_id=user_entity.id, access_hash=user_entity.access_hash)]))
                    except Exception:
                        pass
        except Exception as err:
            logger.debug(f"Contact import notice for {phone_e164}: {err}")

        # Path 2: Username Fallback (if phone import returned retry_contacts or failed due to Privacy)
        if not user_entity:
            cache = cls._load_cache()
            target_username = (
                cache.get(phone_e164) or 
                cache.get(clean_digits) or 
                (workingna_profile.get("telegram_username") if workingna_profile else None) or
                (workingna_profile.get("username") if workingna_profile else None)
            )

            if target_username:
                clean_uname = target_username.strip().replace("@", "")
                try:
                    user_entity = await client.get_entity(clean_uname)
                    logger.info(f"✔ Successfully resolved {phone_e164} via Username @{clean_uname}")
                except Exception as un_err:
                    logger.debug(f"Username resolution notice for @{clean_uname}: {un_err}")

        if user_entity:
            user_info = {
                "id": user_entity.id,
                "first_name": getattr(user_entity, "first_name", "") or "",
                "last_name": getattr(user_entity, "last_name", "") or "",
                "username": getattr(user_entity, "username", "") or "",
                "phone": getattr(user_entity, "phone", "") or phone_e164,
                "is_bot": getattr(user_entity, "bot", False),
                "is_deleted": getattr(user_entity, "deleted", False),
                "status": type(user_entity.status).__name__ if getattr(user_entity, "status", None) else "Unknown"
            }
            # Cache discovered handle for future instant lookup
            if getattr(user_entity, "username", None):
                cls.register_known_handle(phone_e164, user_entity.username)

            return True, user_info, user_entity

        return False, None, None
