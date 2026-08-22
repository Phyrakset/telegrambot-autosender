import os
import re
import phonenumbers
from phonenumbers import PhoneNumberFormat

def format_phone_e164(raw_phone: str, default_region: str = "KH") -> str:
    """
    Parses and converts a raw phone string into standard E.164 format (+855...).
    Handles Cambodian local format (093..., 018...) or international format (+855...).
    """
    cleaned = raw_phone.strip()
    if not cleaned:
        return ""
    
    # Clean non-digit characters except leading +
    cleaned = re.sub(r"[^\d+]", "", cleaned)

    try:
        parsed = phonenumbers.parse(cleaned, default_region)
        formatted = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        # Fix for Cambodia or other regions where local leading zero might get retained:
        if formatted.startswith("+8550"):
            formatted = "+855" + formatted[5:]
        return formatted
    except phonenumbers.NumberParseException:
        # Fallback if raw digits provided
        if cleaned.startswith("+"):
            return cleaned
        if cleaned.startswith("0"):
            cleaned = cleaned[1:]
        if default_region.upper() == "KH":
            return f"+855{cleaned}"
        return f"+{cleaned}"

def load_phone_numbers(file_path: str, default_region: str = "KH") -> list[dict]:
    """
    Loads phone numbers from a text file, cleans them, and returns formatted records.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    results = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            e164 = format_phone_e164(raw, default_region)
            results.append({
                "line": line_num,
                "raw": raw,
                "e164": e164
            })
    return results
