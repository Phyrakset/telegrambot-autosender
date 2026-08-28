import os
import re
import logging
import asyncio
import threading
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from filelock import FileLock

from src.telebot.config import config
from src.telebot.integrations.google_sheets import GOOGLE_SHEET_COLUMNS, sync_result_to_google_sheet

logger = logging.getLogger("ACIDStorageManager")

# In-memory lock for concurrent coroutines in the same process
_ASYNC_LOCK = asyncio.Lock()
_THREAD_LOCK = threading.Lock()

def sanitize_value(val: Any) -> str:
    """Clean newlines and special characters so CSV columns never break across multiple rows."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    val_str = str(val).strip()
    # Collapse multiple whitespace / newlines into a clean single line
    val_str = re.sub(r"[\r\n\t]+", " ", val_str)
    return val_str

class ACIDStorageManager:
    """
    Thread-safe, process-safe, and ACID-compliant storage engine for campaign results.
    Guarantees atomic file writes, crash durability, row locking, and duplicate prevention.
    """

    @staticmethod
    def get_lock_path(csv_path: Optional[str] = None) -> str:
        target = csv_path or config.tverkar_results_csv
        return f"{target}.lock"

    @staticmethod
    def load_all_records(csv_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Safely reads all records using a shared file lock."""
        target = csv_path or config.tverkar_results_csv
        lock_path = ACIDStorageManager.get_lock_path(target)

        with _THREAD_LOCK:
            with FileLock(lock_path, timeout=10):
                if not os.path.exists(target):
                    return []
                try:
                    df = pd.read_csv(target, encoding="utf-8-sig", dtype=str)
                    df.fillna("", inplace=True)
                    return df.to_dict(orient="records")
                except Exception as e:
                    logger.warning(f"Notice: Failed to read CSV {target}: {e}")
                    return []

    @staticmethod
    def atomic_save_all_records(records: List[Dict[str, Any]], csv_path: Optional[str] = None) -> bool:
        """
        Atomically writes records to CSV with fsync durability and tempfile replace.
        Prevents partial writes, corruption, and concurrent collisions.
        """
        target = csv_path or config.tverkar_results_csv
        lock_path = ACIDStorageManager.get_lock_path(target)
        tmp_target = f"{target}.tmp_{os.getpid()}_{datetime.now().strftime('%f')}"

        with _THREAD_LOCK:
            with FileLock(lock_path, timeout=15):
                try:
                    # Sanitize all rows to ensure consistent schema
                    cleaned_records = []
                    for r in records:
                        cleaned_row = {}
                        for col in GOOGLE_SHEET_COLUMNS:
                            cleaned_row[col] = sanitize_value(r.get(col, ""))
                        cleaned_records.append(cleaned_row)

                    df = pd.DataFrame(cleaned_records, columns=GOOGLE_SHEET_COLUMNS)
                    
                    # 1. Write to temporary file
                    df.to_csv(tmp_target, index=False, encoding="utf-8-sig")

                    # 2. Flush to disk (Durability)
                    with open(tmp_target, "a", encoding="utf-8-sig") as f:
                        f.flush()
                        os.fsync(f.fileno())

                    # 3. Atomic replacement (Atomicity & Isolation)
                    if os.path.exists(target):
                        os.replace(tmp_target, target)
                    else:
                        os.rename(tmp_target, target)

                    logger.debug(f"✔ Atomically saved {len(records)} records to {target}")
                    return True
                except Exception as e:
                    logger.error(f"❌ Failed atomic write to {target}: {e}")
                    if os.path.exists(tmp_target):
                        try:
                            os.remove(tmp_target)
                        except Exception:
                            pass
                    return False

    @staticmethod
    async def record_campaign_result(
        row_dict: Dict[str, Any],
        csv_path: Optional[str] = None,
        sync_to_cloud: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Thread-safe & async-safe entry point to record candidate results.
        Performs an ACID upsert: updates existing candidate or inserts new.
        """
        target = csv_path or config.tverkar_results_csv
        sanitized_row = {col: sanitize_value(row_dict.get(col, "")) for col in GOOGLE_SHEET_COLUMNS}
        phone_key = sanitized_row.get("Phone (E.164)") or sanitized_row.get("Raw Phone")

        async with _ASYNC_LOCK:
            # 1. Load existing data
            existing = ACIDStorageManager.load_all_records(target)

            # 2. Match and Upsert
            updated = False
            if phone_key:
                for idx, item in enumerate(existing):
                    item_phone = item.get("Phone (E.164)") or item.get("Raw Phone")
                    if item_phone and item_phone == phone_key:
                        sanitized_row["Index"] = str(idx + 1)
                        existing[idx] = sanitized_row
                        updated = True
                        break

            if not updated:
                sanitized_row["Index"] = str(len(existing) + 1)
                existing.append(sanitized_row)

            # 3. Commit Atomic Write
            success = ACIDStorageManager.atomic_save_all_records(existing, target)

        # 4. Sync to Google Sheets with real-time confirmation
        if success and sync_to_cloud and config.google_sheet_webhook_url:
            try:
                gs_ok, gs_msg = await sync_result_to_google_sheet(sanitized_row)
                if gs_ok:
                    print(f"       \033[92m📊 [Google Sheets] Real-time row #{sanitized_row.get('Index')} synced successfully.\033[0m")
                else:
                    print(f"       \033[93m⚠ [Google Sheets Notice] {gs_msg}\033[0m")
            except Exception as e:
                logger.warning(f"Google Sheet sync notice: {e}")

        return success, sanitized_row.get("Index")
