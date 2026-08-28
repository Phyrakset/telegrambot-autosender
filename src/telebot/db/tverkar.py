import logging
import uuid
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from src.telebot.config import config

logger = logging.getLogger("TverkarDB")

def get_tverkar_connection():
    """Create and return a PostgreSQL connection to TverKar database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        raise ImportError("psycopg2-binary is not installed. Please run: pip install psycopg2-binary")

    cfg = config.reload() if hasattr(config, "reload") else config
    return psycopg2.connect(
        cfg.tverkar_database_url,
        cursor_factory=RealDictCursor,
        connect_timeout=5
    )

def parse_salary_amount(raw_val: Any) -> Optional[float]:
    """Extract numeric salary from string or number (e.g. '$300+', '250-300', '350$')."""
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    
    val_str = str(raw_val).strip()
    # Replace Khmer digits with Arabic digits
    khmer_digits = {"០": "0", "១": "1", "២": "2", "៣": "3", "៤": "4", "៥": "5", "៦": "6", "៧": "7", "៨": "8", "៩": "9"}
    for kh, ar in khmer_digits.items():
        val_str = val_str.replace(kh, ar)

    matches = re.findall(r"\d+(?:\.\d+)?", val_str)
    if matches:
        try:
            return float(matches[0])
        except ValueError:
            return None
    return None

def map_gender(val: Any) -> Optional[str]:
    """Map gender from Workingna integer (1: Male, 2: Female, 3: Other) or string to TverKar enum."""
    if val is None:
        return None
    if val in (1, "1", "male", "Male", "M", "ប្រុស"):
        return "male"
    if val in (2, "2", "female", "Female", "F", "ស្រី"):
        return "female"
    return "other"

def map_worker_status(survey_status: str, survey_job_pref: str) -> str:
    """Map survey answers to TverKar worker status enum ('urgent' | 'looking' | 'employed')."""
    stat = (survey_status or "").lower()
    pref = (survey_job_pref or "").lower()

    if "ឈប់" in stat or "stop" in stat or "unemployed" in stat:
        if "បន្ទាន់" in pref or "urgent" in pref or "1" in pref:
            return "urgent"
        return "looking"
    else:
        # Currently employed
        if "ចង់" in pref and "មិន" not in pref:
            return "looking"
        return "employed"

def upsert_worker_from_workingna(
    workingna_profile: Dict[str, Any],
    survey_answers: Dict[str, Any],
    telegram_user_info: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Migrate & prefill candidate into TverKar Postgres DB.
    Returns: (success, worker_id, error_message)
    """
    try:
        tg_id = str(telegram_user_info.get("id")) if telegram_user_info and telegram_user_info.get("id") else None
        tg_username = telegram_user_info.get("username") if telegram_user_info else None
        phone = workingna_profile.get("e164_phone") or workingna_profile.get("raw_phone") or ""

        # Determine Worker Status & Salary from Survey
        status = map_worker_status(
            survey_answers.get("employment_status", ""),
            survey_answers.get("job_preference", "")
        )

        expected_salary = parse_salary_amount(survey_answers.get("expected_salary"))
        if expected_salary is None:
            expected_salary = parse_salary_amount(workingna_profile.get("prefer_salary"))
        if expected_salary is None:
            expected_salary = parse_salary_amount(workingna_profile.get("current_salary"))

        preferred_location = (survey_answers.get("preferred_location") or "").strip()
        if not preferred_location:
            preferred_location = workingna_profile.get("prefer_location") or workingna_profile.get("province") or "Phnom Penh"

        gender = map_gender(workingna_profile.get("gender"))
        dob = workingna_profile.get("dob")
        current_address = workingna_profile.get("sangkat") or workingna_profile.get("address") or ""
        khan_district = workingna_profile.get("khan") or ""
        city_province = workingna_profile.get("province") or "Phnom Penh"
        about = workingna_profile.get("about_me") or ""
        full_name = workingna_profile.get("candidate_name") or "បេក្ខជន"

        now = datetime.now(timezone.utc)

        conn = get_tverkar_connection()
        try:
            with conn.cursor() as cursor:
                # 1. Check if worker already exists by telegram_user_id or phone (with row locking)
                existing_worker_id = None
                if tg_id:
                    cursor.execute("SELECT id FROM workers WHERE telegram_user_id = %s LIMIT 1 FOR UPDATE", (tg_id,))
                    row = cursor.fetchone()
                    if row:
                        existing_worker_id = str(row["id"])

                if not existing_worker_id and phone:
                    cursor.execute("SELECT id FROM workers WHERE phone = %s LIMIT 1 FOR UPDATE", (phone,))
                    row = cursor.fetchone()
                    if row:
                        existing_worker_id = str(row["id"])

                if existing_worker_id:
                    # Update existing worker
                    worker_id = existing_worker_id
                    cursor.execute("""
                        UPDATE workers SET
                            full_name = %s,
                            phone = COALESCE(phone, %s),
                            telegram_user_id = COALESCE(telegram_user_id, %s),
                            telegram_username = COALESCE(telegram_username, %s),
                            gender = COALESCE(gender, %s),
                            date_of_birth = COALESCE(date_of_birth, %s),
                            current_address = COALESCE(current_address, %s),
                            khan_district = COALESCE(khan_district, %s),
                            city_province = COALESCE(city_province, %s),
                            expected_wage_min = %s,
                            zone_of_availability = %s,
                            status = %s,
                            about = COALESCE(about, %s),
                            claimed_at = COALESCE(claimed_at, %s),
                            terms_contact_accepted_at = COALESCE(terms_contact_accepted_at, %s),
                            updated_at = %s
                        WHERE id = %s
                    """, (
                        full_name, phone, tg_id, tg_username, gender, dob,
                        current_address, khan_district, city_province,
                        expected_salary, preferred_location, status, about,
                        now, now, now, worker_id
                    ))
                else:
                    # Insert new worker
                    worker_id = str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO workers (
                            id, full_name, phone, telegram_user_id, telegram_username,
                            gender, date_of_birth, current_address, khan_district, city_province,
                            expected_wage_min, zone_of_availability, status, preferred_contact,
                            profile_state, about, claimed_at, terms_contact_accepted_at,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, 'telegram',
                            'draft', %s, %s, %s,
                            %s, %s
                        )
                    """, (
                        worker_id, full_name, phone, tg_id, tg_username,
                        gender, dob, current_address, khan_district, city_province,
                        expected_salary, preferred_location, status,
                        about, now, now, now, now
                    ))

                # 2. Insert Experiences
                experiences = workingna_profile.get("experiences") or []
                for exp in experiences:
                    company = (exp.get("company") or "").strip()
                    title = (exp.get("jobTitle") or "").strip()
                    if not company and not title:
                        continue
                    company = company or "General"
                    title = title or "Staff"

                    cursor.execute("""
                        SELECT id FROM worker_experiences 
                        WHERE worker_id = %s AND company_name = %s AND position_title = %s 
                        LIMIT 1
                    """, (worker_id, company, title))
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO worker_experiences (
                                id, worker_id, company_name, position_title, location,
                                from_month, from_year, to_month, to_year, is_current,
                                responsibilities, created_at, updated_at
                            ) VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s
                            )
                        """, (
                            str(uuid.uuid4()), worker_id, company, title,
                            exp.get("city") or exp.get("country"),
                            int(exp["fromMonth"]) if exp.get("fromMonth") and str(exp["fromMonth"]).isdigit() else None,
                            exp.get("fromYear"),
                            int(exp["toMonth"]) if exp.get("toMonth") and str(exp["toMonth"]).isdigit() else None,
                            exp.get("toYear"),
                            bool(exp.get("isWorking")),
                            exp.get("description"),
                            now, now
                        ))

                # 3. Insert Educations
                educations = workingna_profile.get("educations") or []
                for edu in educations:
                    school = (edu.get("school") or "").strip()
                    if not school:
                        continue
                    cursor.execute("""
                        SELECT id FROM worker_educations 
                        WHERE worker_id = %s AND school_name = %s 
                        LIMIT 1
                    """, (worker_id, school))
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO worker_educations (
                                id, worker_id, school_name, degree, field_of_study,
                                from_year, to_year, created_at, updated_at
                            ) VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s
                            )
                        """, (
                            str(uuid.uuid4()), worker_id, school,
                            edu.get("degree"), edu.get("fieldOfStudy"),
                            edu.get("fromYear"), edu.get("toYear"),
                            now, now
                        ))

                conn.commit()
                logger.info(f"Successfully migrated candidate {full_name} -> TverKar worker {worker_id}")
                return True, worker_id, None

        except Exception as err:
            conn.rollback()
            logger.error(f"Transaction rolled back: {err}")
            return False, None, str(err)
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Failed to migrate candidate to TverKar: {e}")
        return False, None, str(e)
