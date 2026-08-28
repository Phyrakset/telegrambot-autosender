import os
import re
from typing import List, Dict, Any
import phonenumbers
from phonenumbers import PhoneNumberFormat

def format_phone_e164(raw_phone: str, default_region: str = "KH", default_country: str = "KH") -> str:
    """
    Parses and converts a raw phone string into standard E.164 format (+855...).
    Intelligently handles Cambodian local format, country code prefixes (855), 
    accidental typos (e.g. 885... instead of 855...), and duplicate zeros.
    """
    region = default_country if default_country != "KH" else default_region
    cleaned = str(raw_phone).split(".")[0].strip()
    if not cleaned or cleaned.lower() == "nan":
        return ""
    
    # Strip all non-digit characters except leading +
    cleaned = re.sub(r"[^\d+]", "", cleaned)
    if not cleaned:
        return ""
    
    has_plus = cleaned.startswith("+")
    digits = cleaned.lstrip("+")
    
    if region.upper() == "KH":
        # Fix common typo: 885... with 11 or 12 digits -> 855...
        if digits.startswith("885") and len(digits) in (11, 12):
            digits = "855" + digits[3:]
        
        # If already starts with 855 (Cambodia country code)
        if digits.startswith("855"):
            rest = digits[3:]
            if rest.startswith("0"):
                rest = rest[1:]
            return f"+855{rest}"
        
        # If starts with leading 0 (e.g. 092342252)
        if digits.startswith("0"):
            return f"+855{digits[1:]}"
            
        # If 8 or 9 digits (standard Cambodian mobile without leading 0, e.g. 92342252, 882534191)
        if len(digits) in (8, 9):
            return f"+855{digits}"

    # General libphonenumber fallback for other regions / international
    try:
        parsed = phonenumbers.parse("+" + digits if not has_plus else cleaned, region)
        formatted = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        if formatted.startswith("+8550"):
            formatted = "+855" + formatted[5:]
        return formatted
    except phonenumbers.NumberParseException:
        if has_plus:
            return f"+{digits}"
        return f"+{digits}"

def load_phone_numbers(
    file_path: str, 
    default_region: str = "KH",
    deduplicate: bool = True
) -> List[Dict[str, Any]]:
    """
    Loads phone numbers from Excel (.xlsx, .xls), CSV (.csv), or Text (.txt) files.
    Automatically detects phone number columns and converts them into standard E.164.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Target file not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    raw_list: List[str] = []

    if ext in (".xlsx", ".xls"):
        import pandas as pd
        df = pd.read_excel(file_path)
        # Search for column named phone, phoneNumber, contactNumber, mobile, etc.
        target_col = None
        for col in df.columns:
            clean_col = str(col).lower().replace(" ", "").replace("_", "")
            if clean_col in ("phonenumber", "phone", "contactnumber", "mobile", "tel", "telephone", "cell"):
                target_col = col
                break
        
        if target_col is not None:
            raw_list = df[target_col].dropna().astype(str).tolist()
        else:
            # Fallback: pick first column with digit-containing strings
            for col in df.columns:
                series = df[col].dropna().astype(str)
                if series.str.contains(r"\d{7,}", regex=True).any():
                    raw_list = series.tolist()
                    break
            if not raw_list and len(df.columns) > 0:
                raw_list = df.iloc[:, 0].dropna().astype(str).tolist()

    elif ext == ".csv":
        import pandas as pd
        df = pd.read_csv(file_path, encoding="utf-8-sig")
        target_col = None
        for col in df.columns:
            clean_col = str(col).lower().replace(" ", "").replace("_", "")
            if clean_col in ("phonenumber", "phone", "contactnumber", "mobile", "tel", "telephone"):
                target_col = col
                break
        if target_col is not None:
            raw_list = df[target_col].dropna().astype(str).tolist()
        else:
            raw_list = df.iloc[:, 0].dropna().astype(str).tolist()

    else:
        # Standard text file
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    raw_list.append(stripped)

    results: List[Dict[str, Any]] = []
    seen_e164 = set()

    for idx, raw_val in enumerate(raw_list, 1):
        clean_raw = str(raw_val).split(".")[0].strip()  # handle float parsing in excel (e.g. 85595777151.0)
        clean_raw = clean_raw.split("#")[0].strip()
        if not clean_raw or clean_raw.lower() == "nan":
            continue
        
        e164 = format_phone_e164(clean_raw, default_region=default_region)
        if not e164:
            continue

        if deduplicate:
            if e164 in seen_e164:
                continue
            seen_e164.add(e164)

        results.append({
            "line": idx,
            "raw": clean_raw,
            "e164": e164
        })

    return results
