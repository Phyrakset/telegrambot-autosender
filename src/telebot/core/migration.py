import logging
from typing import Dict, Any, Optional, Tuple

from src.telebot.db.workingna import find_candidate_by_phone, fetch_full_candidate_detail, get_admin_url
from src.telebot.db.tverkar import upsert_worker_from_workingna

logger = logging.getLogger("MigrationEngine")

class MigrationEngine:
    @staticmethod
    def resolve_candidate_profile(
        phone: str, 
        profile_id: Optional[int | str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Locate candidate in Workingna DB by profile_id or phone number.
        """
        if profile_id:
            profile = fetch_full_candidate_detail(profile_id)
            if profile:
                return profile

        if phone:
            return find_candidate_by_phone(phone)

        return None

    @staticmethod
    def migrate_consenting_candidate(
        phone: str,
        survey_answers: Dict[str, Any],
        telegram_user_info: Optional[Dict[str, Any]] = None,
        workingna_profile: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Main migration entry point when candidate consents in survey.
        Returns: (migration_status, tverkar_worker_id, admin_url)
        """
        # If profile wasn't pre-loaded, resolve it from phone
        if not workingna_profile:
            workingna_profile = MigrationEngine.resolve_candidate_profile(phone=phone)

        if not workingna_profile:
            logger.warning(f"No Workingna profile found for phone {phone}. Candidate consented but profile cannot be migrated.")
            return "NO_WORKINGNA_PROFILE", None, None

        admin_url = workingna_profile.get("admin_url") or get_admin_url(workingna_profile.get("profile_id"))

        # Perform upsert into TverKar database
        success, worker_id, err = upsert_worker_from_workingna(
            workingna_profile=workingna_profile,
            survey_answers=survey_answers,
            telegram_user_info=telegram_user_info
        )

        if success:
            return "MIGRATED_SUCCESS", worker_id, admin_url
        else:
            return f"MIGRATION_FAILED: {err}", None, admin_url
