import logging
from typing import List, Dict, Any, Optional
import pymysql
from pymysql.cursors import DictCursor

from src.telebot.config import config
from src.telebot.utils.phone import format_phone_e164

logger = logging.getLogger("WorkingnaDB")

def get_workingna_connection():
    """Create and return a MySQL connection to Workingna database."""
    cfg = config.reload() if hasattr(config, "reload") else config
    return pymysql.connect(
        host=cfg.workingna_db_host,
        port=cfg.workingna_db_port,
        user=cfg.workingna_db_user,
        password=cfg.workingna_db_password,
        database=cfg.workingna_db_name,
        cursorclass=DictCursor,
        connect_timeout=5,
        charset="utf8mb4"
    )

def get_admin_url(profile_id: int | str) -> str:
    """Generate the clickable Workingna Admin Job-Seeker URL."""
    base = config.workingna_admin_base_url.rstrip("/")
    return f"{base}/{profile_id}?tab=detail"

def fetch_workingna_candidates(
    limit: int = 50,
    offset: int = 0,
    only_looking: bool = False,
    has_phone_only: bool = True,
    search: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch candidate list from Workingna DB for campaign targeting.
    """
    query = """
        SELECT 
            p.id AS profile_id,
            p.userId AS user_id,
            p.firstName,
            p.lastName,
            p.email,
            p.contactNumber,
            p.gender,
            p.dob,
            p.province,
            p.khan,
            p.sangkat,
            p.address,
            p.currentSalary,
            p.prefer_salary_range,
            p.prefer_location,
            p.lookingForJobs,
            p.aboutMe,
            p.imageUrl,
            p.fileUrl,
            p.updatedAt,
            p.createdAt,
            u.phoneNumber AS user_phone,
            u.email AS user_email
        FROM profile p
        LEFT JOIN user u ON p.userId = u.id
        WHERE 1=1
    """
    params: List[Any] = []

    if has_phone_only:
        query += " AND (COALESCE(p.contactNumber, '') != '' OR COALESCE(u.phoneNumber, '') != '')"

    if only_looking:
        query += " AND p.lookingForJobs = 1"

    if search:
        query += " AND (p.firstName LIKE %s OR p.lastName LIKE %s OR p.contactNumber LIKE %s OR u.phoneNumber LIKE %s)"
        like_str = f"%{search.strip()}%"
        params.extend([like_str, like_str, like_str, like_str])

    query += " ORDER BY p.id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    results = []
    try:
        with get_workingna_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                for row in rows:
                    raw_phone = row.get("contactNumber") or row.get("user_phone") or ""
                    e164_phone = format_phone_e164(raw_phone, default_country=config.default_country)
                    
                    first = (row.get("firstName") or "").strip()
                    last = (row.get("lastName") or "").strip()
                    full_name = f"{first} {last}".strip()
                    if not full_name:
                        full_name = "បេក្ខជន"

                    admin_url = get_admin_url(row["profile_id"])
                    
                    results.append({
                        "profile_id": row["profile_id"],
                        "user_id": row["user_id"],
                        "candidate_name": full_name,
                        "raw_phone": raw_phone,
                        "e164_phone": e164_phone,
                        "admin_url": admin_url,
                        "gender": row.get("gender"),
                        "dob": row.get("dob"),
                        "province": row.get("province"),
                        "khan": row.get("khan"),
                        "sangkat": row.get("sangkat"),
                        "address": row.get("address"),
                        "current_salary": row.get("currentSalary"),
                        "prefer_salary": row.get("prefer_salary_range"),
                        "prefer_location": row.get("prefer_location"),
                        "looking_for_jobs": bool(row.get("lookingForJobs")),
                        "about_me": row.get("aboutMe"),
                        "image_url": row.get("imageUrl"),
                        "file_url": row.get("fileUrl"),
                    })
    except Exception as e:
        logger.error(f"Error fetching candidates from Workingna DB: {e}")
        raise e

    return results

def fetch_full_candidate_detail(profile_id: int | str) -> Optional[Dict[str, Any]]:
    """
    Fetch comprehensive candidate profile with experiences and educations for migration.
    """
    try:
        with get_workingna_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Fetch Profile
                cursor.execute("""
                    SELECT 
                        p.id AS profile_id,
                        p.userId AS user_id,
                        p.firstName,
                        p.lastName,
                        p.email,
                        p.contactNumber,
                        p.gender,
                        p.dob,
                        p.province,
                        p.khan,
                        p.sangkat,
                        p.address,
                        p.currentSalary,
                        p.prefer_salary_range,
                        p.prefer_location,
                        p.lookingForJobs,
                        p.aboutMe,
                        p.imageUrl,
                        p.fileUrl,
                        u.phoneNumber AS user_phone
                    FROM profile p
                    LEFT JOIN user u ON p.userId = u.id
                    WHERE p.id = %s
                """, (profile_id,))
                prof = cursor.fetchone()
                if not prof:
                    return None

                # 2. Fetch Experiences
                cursor.execute("""
                    SELECT 
                        id,
                        jobTitle,
                        company,
                        city,
                        country,
                        isWorking,
                        fromMonth,
                        fromYear,
                        toMonth,
                        toYear,
                        description
                    FROM experience
                    WHERE profileId = %s OR (userId = %s AND userId IS NOT NULL)
                    ORDER BY COALESCE(fromYear, 0) DESC, COALESCE(fromMonth, 0) DESC
                """, (profile_id, prof.get("user_id")))
                experiences = cursor.fetchall() or []

                # 3. Fetch Educations
                cursor.execute("""
                    SELECT 
                        id,
                        school,
                        fieldOfStudy,
                        degree,
                        city,
                        country,
                        fromYear,
                        toYear
                    FROM education
                    WHERE profileId = %s OR (userId = %s AND userId IS NOT NULL)
                    ORDER BY COALESCE(fromYear, 0) DESC
                """, (profile_id, prof.get("user_id")))
                educations = cursor.fetchall() or []

                first = (prof.get("firstName") or "").strip()
                last = (prof.get("lastName") or "").strip()
                full_name = f"{first} {last}".strip()
                raw_phone = prof.get("contactNumber") or prof.get("user_phone") or ""

                return {
                    "profile_id": prof["profile_id"],
                    "user_id": prof["user_id"],
                    "candidate_name": full_name or "បេក្ខជន",
                    "raw_phone": raw_phone,
                    "e164_phone": format_phone_e164(raw_phone, default_country=config.default_country),
                    "admin_url": get_admin_url(prof["profile_id"]),
                    "gender": prof.get("gender"),
                    "dob": prof.get("dob"),
                    "province": prof.get("province"),
                    "khan": prof.get("khan"),
                    "sangkat": prof.get("sangkat"),
                    "address": prof.get("address"),
                    "current_salary": prof.get("currentSalary"),
                    "prefer_salary": prof.get("prefer_salary_range"),
                    "prefer_location": prof.get("prefer_location"),
                    "looking_for_jobs": bool(prof.get("lookingForJobs")),
                    "about_me": prof.get("aboutMe"),
                    "image_url": prof.get("imageUrl"),
                    "file_url": prof.get("fileUrl"),
                    "experiences": experiences,
                    "educations": educations
                }
    except Exception as e:
        logger.error(f"Error fetching full candidate profile {profile_id}: {e}")
        return None

def find_candidate_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """
    Search candidate profile in Workingna DB matching given phone number.
    """
    if not phone:
        return None
    
    clean_digits = "".join([c for c in phone if c.isdigit()])
    if not clean_digits:
        return None

    # Strip country code 855 if present for local matching
    local_digits = clean_digits[3:] if clean_digits.startswith("855") else clean_digits
    if local_digits.startswith("0"):
        local_no_zero = local_digits[1:]
    else:
        local_no_zero = local_digits
        local_digits = f"0{local_digits}"

    try:
        with get_workingna_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT p.id 
                    FROM profile p
                    LEFT JOIN user u ON p.userId = u.id
                    WHERE p.contactNumber LIKE %s 
                       OR p.contactNumber LIKE %s
                       OR u.phoneNumber LIKE %s
                       OR u.phoneNumber LIKE %s
                    ORDER BY p.id DESC
                    LIMIT 1
                """, (
                    f"%{local_digits}%",
                    f"%{local_no_zero}%",
                    f"%{local_digits}%",
                    f"%{local_no_zero}%"
                ))
                row = cursor.fetchone()
                if row and row.get("id"):
                    return fetch_full_candidate_detail(row["id"])
    except Exception as e:
        logger.warning(f"Could not find candidate by phone {phone}: {e}")
    return None
