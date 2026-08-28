import os
import json
import logging
from typing import Dict, Any, List, Tuple, Optional
import httpx
import requests
import pandas as pd

from src.telebot.config import config

logger = logging.getLogger("GoogleSheetsSync")

GOOGLE_SHEET_COLUMNS = [
    "Index",
    "Timestamp",
    "Phone (E.164)",
    "Raw Phone",
    "Candidate Name",
    "Username",
    "User ID",
    "Consent Transfer",
    "Employment Status",
    "Job Preference / Urgency",
    "Expected Salary",
    "Preferred Location",
    "Voice Notes",
    "Dialogue Summary",
    "Campaign Status",
    "Notes",
    "Workingna Admin URL",
    "Migration Status",
    "TverKar Worker ID"
]

def format_row_for_sheet(row: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all required columns exist and clean non-serializable objects."""
    formatted = {}
    for col in GOOGLE_SHEET_COLUMNS:
        val = row.get(col, "")
        if val is None or (isinstance(val, float) and pd.isna(val)):
            formatted[col] = ""
        else:
            formatted[col] = str(val)
    return formatted

async def sync_result_to_google_sheet(row_dict: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Asynchronously appends a single candidate row to the Google Spreadsheet via Webhook.
    """
    webhook_url = config.google_sheet_webhook_url or os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.debug("GOOGLE_SHEET_WEBHOOK_URL is not configured; skipping Google Sheet sync.")
        return False, "GOOGLE_SHEET_WEBHOOK_URL is not set"

    payload = {
        "action": "append",
        "row": format_row_for_sheet(row_dict)
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200:
                logger.info(f"✔ Successfully synced candidate {row_dict.get('Phone (E.164)')} to Google Sheets.")
                return True, "Synced to Google Sheets"
            else:
                msg = f"HTTP {resp.status_code}: {resp.text[:120]}"
                logger.warning(f"Failed to sync to Google Sheets: {msg}")
                return False, msg
    except Exception as e:
        logger.error(f"Google Sheet sync network error: {e}")
        return False, str(e)

def sync_result_to_google_sheet_sync(row_dict: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Synchronously appends a single candidate row to the Google Spreadsheet via Webhook.
    """
    webhook_url = config.google_sheet_webhook_url or os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False, "GOOGLE_SHEET_WEBHOOK_URL is not set"

    payload = {
        "action": "append",
        "row": format_row_for_sheet(row_dict)
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            return True, "Synced to Google Sheets"
        else:
            return False, f"HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"Google Sheet sync error: {e}")
        return False, str(e)

def sync_bulk_csv_to_google_sheet(csv_path: Optional[str] = None) -> Tuple[bool, str, int]:
    """
    Uploads all rows from local CSV (e.g. tverkar_campaign_results.csv) to Google Sheets.
    """
    webhook_url = config.google_sheet_webhook_url or os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False, "Please configure GOOGLE_SHEET_WEBHOOK_URL in .env first", 0

    target_csv = csv_path or config.tverkar_results_csv
    if not os.path.exists(target_csv):
        return False, f"Local CSV '{target_csv}' not found.", 0

    try:
        df = pd.read_csv(target_csv, encoding="utf-8-sig")
        if df.empty:
            return False, "CSV file is empty", 0

        records = df.to_dict(orient="records")
        cleaned_rows = [format_row_for_sheet(r) for r in records]

        payload = {
            "action": "bulk",
            "rows": cleaned_rows
        }

        resp = requests.post(webhook_url, json=payload, timeout=30, allow_redirects=True)
        if resp.status_code == 200:
            return True, f"Successfully uploaded {len(cleaned_rows)} rows to Google Sheets", len(cleaned_rows)
        else:
            return False, f"Server responded HTTP {resp.status_code}: {resp.text[:120]}", 0
    except Exception as e:
        logger.error(f"Bulk sync to Google Sheets error: {e}")
        return False, str(e), 0
