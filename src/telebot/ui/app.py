import os
import sys
import socket
import asyncio
import pandas as pd
import gradio as gr
from telethon import custom, errors
from typing import Optional, Dict, Any, List, Tuple, Set
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from src.telebot.config import config, AppConfig
from src.telebot.utils.phone import format_phone_e164, load_phone_numbers
from src.telebot.core.service import TelegramService
from src.telebot.db.workingna import fetch_workingna_candidates, find_candidate_by_phone, get_admin_url
from src.telebot.core.migration import MigrationEngine
from src.telebot.integrations.google_sheets import sync_result_to_google_sheet, sync_bulk_csv_to_google_sheet
from src.telebot.core.storage import ACIDStorageManager

service = TelegramService()
STOP_SIGNAL = False

DEFAULT_OUTREACH_MESSAGE = config.tverkar_initial_message

CUSTOM_CSS = """
/* Modern SaaS Minimalist Theme */
.gradio-container {
    max-width: 1350px !important;
    margin: 0 auto !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
}
.app-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    background: #0f172a;
    border-radius: 12px;
    margin-bottom: 16px;
    border: 1px solid #1e293b;
}
.app-brand {
    display: flex;
    align-items: center;
    gap: 10px;
}
.app-title {
    font-size: 18px;
    font-weight: 700;
    color: #f8fafc;
    margin: 0;
    letter-spacing: -0.3px;
}
.app-subtitle {
    font-size: 12px;
    color: #94a3b8;
    margin: 0;
}
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 10px;
    margin-bottom: 16px;
}
.kpi-card {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 10px;
    padding: 12px 14px;
}
.kpi-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
}
.kpi-value {
    font-size: 20px;
    font-weight: 700;
    margin-top: 4px;
    color: #f8fafc;
}
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    background: #1e293b;
    color: #e2e8f0;
}
"""

def find_available_port(start_port: int = 7860, max_port: int = 7890) -> int:
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0

def get_candidates_database_stats() -> Tuple[Dict[str, int], Dict[str, Any]]:
    """Analyzes all numbers in Excel against existing CSV results."""
    excel_path = "all_Phone_barstar_service_cashair.xlsx"
    records = []
    if os.path.exists(excel_path):
        records = load_phone_numbers(excel_path, default_region=config.default_country, deduplicate=True)
    
    csv_records = ACIDStorageManager.load_all_records()
    sent_map: Dict[str, Dict[str, Any]] = {}
    for r in csv_records:
        p = r.get("Phone (E.164)") or r.get("Raw Phone")
        if p:
            sent_map[p] = r

    stats = {
        "total": len(records),
        "unsent": 0,
        "agreed": 0,
        "declined": 0,
        "incomplete": 0,
        "unregistered": 0
    }

    for r in records:
        e164 = r["e164"]
        if e164 not in sent_map:
            stats["unsent"] += 1
        else:
            rec = sent_map[e164]
            consent = rec.get("Consent Transfer", "")
            mig = rec.get("Migration Status", "")
            camp_stat = rec.get("Campaign Status", "")
            notes = rec.get("Notes", "")

            if "យល់ព្រម" in consent:
                stats["agreed"] += 1
            elif "មិនយល់ព្រម" in consent or "DECLINED" in mig:
                stats["declined"] += 1
            elif "Unregistered" in mig or "not registered" in notes:
                stats["unregistered"] += 1
            elif camp_stat == "Incomplete":
                stats["incomplete"] += 1
            else:
                stats["agreed"] += 1

    return stats, sent_map

def render_db_stats_badge() -> str:
    stats, _ = get_candidates_database_stats()
    return f"""
    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; font-size: 12px; font-weight: 600;">
        <span style="background: #1e293b; padding: 4px 10px; border-radius: 6px; color: #94a3b8; border: 1px solid #334155;">📁 Total Excel: <b style="color:#f8fafc;">{stats['total']}</b></span>
        <span style="background: #064e3b; padding: 4px 10px; border-radius: 6px; color: #6ee7b7; border: 1px solid #059669;">🟢 Fresh Unsent: <b style="color:#ffffff;">{stats['unsent']}</b></span>
        <span style="background: #1e3a8a; padding: 4px 10px; border-radius: 6px; color: #93c5fd; border: 1px solid #2563eb;">✅ Agreed / Migrated: <b style="color:#ffffff;">{stats['agreed']}</b></span>
        <span style="background: #451a03; padding: 4px 10px; border-radius: 6px; color: #fde68a; border: 1px solid #d97706;">🟡 Incomplete: <b style="color:#ffffff;">{stats['incomplete']}</b></span>
        <span style="background: #450a0a; padding: 4px 10px; border-radius: 6px; color: #fca5a5; border: 1px solid #dc2626;">🔴 Declined: <b style="color:#ffffff;">{stats['declined']}</b></span>
    </div>
    """

def filter_excel_candidates(filter_mode: str, batch_size: Optional[int] = 100, offset: int = 0) -> Tuple[str, str]:
    """Filters candidate numbers based on campaign history and selected batch size/offset."""
    excel_path = "all_Phone_barstar_service_cashair.xlsx"
    if not os.path.exists(excel_path):
        return get_default_phone_list(), render_db_stats_badge()

    records = load_phone_numbers(excel_path, default_region=config.default_country, deduplicate=True)
    _, sent_map = get_candidates_database_stats()

    filtered = []
    for r in records:
        e164 = r["e164"]
        is_sent = e164 in sent_map
        rec = sent_map.get(e164, {})
        consent = rec.get("Consent Transfer", "")
        mig = rec.get("Migration Status", "")
        camp_stat = rec.get("Campaign Status", "")
        notes = rec.get("Notes", "")

        if "Unsent" in filter_mode:
            if not is_sent:
                filtered.append(e164)
        elif "Incomplete" in filter_mode:
            if is_sent and camp_stat == "Incomplete":
                filtered.append(e164)
        elif "Agreed" in filter_mode:
            if is_sent and "យល់ព្រម" in consent:
                filtered.append(e164)
        elif "Declined" in filter_mode:
            if is_sent and ("មិនយល់ព្រម" in consent or "DECLINED" in mig):
                filtered.append(e164)
        else:
            # All numbers (Preserve exact Excel Row 1 Order)
            filtered.append(e164)

    start_idx = max(0, int(offset or 0))
    end_idx = start_idx + int(batch_size) if (batch_size and int(batch_size) > 0) else len(filtered)
    selected = filtered[start_idx:end_idx]

    phone_text = "\n".join(selected)
    return phone_text, render_db_stats_badge()

def load_excel_phone_list(limit: Optional[int] = 100) -> str:
    text, _ = filter_excel_candidates("📁 All Numbers in Excel (Original Row Order)", batch_size=limit, offset=0)
    return text

def get_default_phone_list() -> str:
    excel_path = "all_Phone_barstar_service_cashair.xlsx"
    if os.path.exists(excel_path):
        text, _ = filter_excel_candidates("📁 All Numbers in Excel (Original Row Order)", batch_size=100, offset=0)
        return text
    for candidate in ["phone-list.txt", "phone-list.example.txt"]:
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read().strip()
    return ""

def load_candidates_from_workingna_db(limit: int, only_looking: bool, search: str) -> str:
    """Helper to query Workingna DB and return newline-separated phone numbers."""
    try:
        candidates = fetch_workingna_candidates(
            limit=int(limit or 50),
            only_looking=bool(only_looking),
            has_phone_only=True,
            search=search.strip() if search else None
        )
        lines = []
        for c in candidates:
            raw = c.get("raw_phone") or c.get("e164_phone")
            name = c.get("candidate_name") or ""
            if raw:
                lines.append(f"{raw} # {name} (Profile ID: {c.get('profile_id')})")
        if not lines:
            return "# No candidates found matching criteria in Workingna DB"
        return "\n".join(lines)
    except Exception as e:
        return f"# Error connecting to Workingna DB: {str(e)}"

def get_empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["#", "Phone (E.164)", "Candidate", "Workingna Admin URL", "Consent", "Employment", "Expected Salary", "Migration", "Status"])

def get_tverkar_df(search_query: str = "", status_filter: str = "All") -> pd.DataFrame:
    if os.path.exists(config.tverkar_results_csv):
        try:
            df = pd.read_csv(config.tverkar_results_csv, encoding="utf-8-sig", dtype=str)
            df.fillna("", inplace=True)
            if status_filter and status_filter != "All":
                if status_filter == "Agreed":
                    df = df[df["Consent Transfer"].str.contains("យល់ព្រម", na=False)]
                elif status_filter == "Declined":
                    df = df[df["Consent Transfer"].str.contains("មិនយល់ព្រម", na=False) | df["Migration Status"].str.contains("DECLINED", na=False)]
                elif status_filter == "Incomplete":
                    df = df[df["Campaign Status"] == "Incomplete"]
                elif status_filter == "Unregistered":
                    df = df[df["Migration Status"].str.contains("Unregistered", na=False) | df["Notes"].str.contains("not registered", na=False)]
            
            if search_query and search_query.strip():
                q = search_query.strip().lower()
                df = df[
                    df["Phone (E.164)"].str.lower().str.contains(q, na=False) |
                    df["Candidate Name"].str.lower().str.contains(q, na=False) |
                    df["Username"].str.lower().str.contains(q, na=False)
                ]
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=[
        "Index", "Timestamp", "Phone (E.164)", "Candidate Name", "Username", "Workingna Admin URL",
        "Consent Transfer", "Employment Status", "Job Preference / Urgency",
        "Expected Salary", "Preferred Location", "Migration Status", "TverKar Worker ID", "Campaign Status", "Notes"
    ])

def render_kpi_html(total: int, reg: int, sent: int, agreed: int, migrated: int, unreg: int) -> str:
    return f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">Total Numbers</div>
            <div class="kpi-value" style="color: #60a5fa;">{total}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Registered Accounts</div>
            <div class="kpi-value" style="color: #34d399;">{reg}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Delivered / Sent</div>
            <div class="kpi-value" style="color: #a78bfa;">{sent}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Consent Agreed (✅)</div>
            <div class="kpi-value" style="color: #10b981;">{agreed}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Migrated to TverKar</div>
            <div class="kpi-value" style="color: #38bdf8;">{migrated}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Unregistered</div>
            <div class="kpi-value" style="color: #94a3b8;">{unreg}</div>
        </div>
    </div>
    """

async def check_header_status() -> str:
    try:
        if await service.is_authenticated():
            me = await service.get_me_info()
            if me:
                name = f"{me['first_name']} {me['last_name']}".strip()
                uname = f"@{me['username']}" if me['username'] else "NoUser"
                return f"""
                <div class="status-pill" style="border: 1px solid #059669; background: #064e3b; color: #a7f3d0;">
                    <span style="height:8px;width:8px;border-radius:50%;background:#10b981;display:inline-block;"></span>
                    <span>Sender Phone: {name} ({uname})</span>
                </div>
                """
        return """
        <div class="status-pill" style="border: 1px solid #dc2626; background: #450a0a; color: #fecaca;">
            <span style="height:8px;width:8px;border-radius:50%;background:#ef4444;display:inline-block;"></span>
            <span>Disconnected · Log In Required</span>
        </div>
        """
    except Exception:
        return """
        <div class="status-pill" style="border: 1px solid #d97706; background: #451a03; color: #fde68a;">
            <span>Session Offline</span>
        </div>
        """

def set_stop():
    global STOP_SIGNAL
    STOP_SIGNAL = True
    return "Stopping after current step..."

# Core Batch Processor (Dedicated TverKar Campaign)
async def execute_batch(
    phone_text: str,
    country_code: str,
    auto_send: bool = True,
    message_text: str = "",
    delay_s: float = 2.0,
    video_path: Optional[str] = None,
    survey_timeout: int = 180
):
    global STOP_SIGNAL
    STOP_SIGNAL = False
    
    raw_lines = [line.strip() for line in phone_text.splitlines() if line.strip() and not line.strip().startswith("#")]
    total = len(raw_lines)
    if total == 0:
        yield get_empty_df(), "Error: No valid phone numbers provided.", render_kpi_html(0, 0, 0, 0, 0, 0)
        return

    try:
        yield get_empty_df(), "Connecting to Telegram MTProto...", render_kpi_html(total, 0, 0, 0, 0, 0)
        is_auth = await service.is_authenticated()
        if not is_auth:
            yield get_empty_df(), "Error: Telegram account is NOT logged in. Go to Account tab to login first.", render_kpi_html(total, 0, 0, 0, 0, 0)
            return
    except Exception as e:
        yield get_empty_df(), f"Connection Error: {str(e)}", render_kpi_html(total, 0, 0, 0, 0, 0)
        return

    # Cache Video Asset
    cached_media = None
    if auto_send and video_path and os.path.exists(video_path):
        try:
            yield get_empty_df(), f"Uploading & caching video '{video_path}' to Telegram...", render_kpi_html(total, 0, 0, 0, 0, 0)
            cached_media = await service.upload_and_cache_video(video_path)
        except Exception:
            pass

    rows = []
    parsed_items = []
    seen_phones = set()
    dup_count = 0

    for raw_line in raw_lines:
        clean_raw = raw_line.split("#")[0].strip()
        e164 = format_phone_e164(clean_raw, default_region=country_code)
        if not e164:
            continue
        if e164 in seen_phones:
            dup_count += 1
            continue
        seen_phones.add(e164)
        item_idx = len(parsed_items) + 1
        parsed_items.append({"raw": clean_raw, "e164": e164})
        rows.append({
            "#": item_idx,
            "Phone (E.164)": e164,
            "Candidate": "-",
            "Workingna Admin URL": "-",
            "Consent": "Queued",
            "Employment": "-",
            "Expected Salary": "-",
            "Migration": "-",
            "Status": "Pending" if auto_send else "Queued"
        })

    total = len(parsed_items)
    df = pd.DataFrame(rows)
    tverkar_campaign_results = []
    if os.path.exists(config.tverkar_results_csv):
        try:
            existing_df = pd.read_csv(config.tverkar_results_csv, encoding="utf-8-sig")
            tverkar_campaign_results = existing_df.to_dict(orient="records")
        except Exception:
            tverkar_campaign_results = []
            
    stats = {"registered": 0, "delivered": 0, "agreed": 0, "migrated": 0, "unregistered": 0, "failed": 0}
    
    action_label = "Running TverKar Outreach & Survey" if auto_send else "Checking registrations"
    yield df, f"Starting {action_label} for {total} target numbers (Delay: {delay_s}s)...", render_kpi_html(total, 0, 0, 0, 0, 0)

    active_background_tasks = set()

    async def _async_survey_worker(
        s_idx: int,
        s_raw: str,
        s_e164: str,
        s_recipient: str,
        s_uname: str,
        s_info: Dict[str, Any],
        s_entity: Any,
        s_admin_url: str,
        s_profile: Optional[Dict[str, Any]],
        s_msg: str
    ):
        nonlocal stats
        try:
            survey_ok, answers, survey_reason = await service.conduct_tverkar_campaign_session(
                s_entity,
                initial_message=s_msg,
                media=cached_media,
                timeout=int(survey_timeout or 180),
                phone_identifier=s_e164,
                user_info=s_info
            )

            df.at[s_idx, "Consent"] = answers.get("consent", "Agreed" if survey_ok else "Declined")
            df.at[s_idx, "Employment"] = answers.get("employment_status", "-")
            df.at[s_idx, "Expected Salary"] = answers.get("expected_salary", "-")

            migration_status = "N/A"
            tverkar_worker_id = None

            if answers.get("consent") == "✅ យល់ព្រម (Agreed)":
                stats["agreed"] += 1
                mig_stat, w_id, u_url = MigrationEngine.migrate_consenting_candidate(
                    phone=s_e164,
                    survey_answers=answers,
                    telegram_user_info=s_info,
                    workingna_profile=s_profile
                )
                migration_status = mig_stat
                tverkar_worker_id = w_id
                df.at[s_idx, "Migration"] = "✔ Success" if "SUCCESS" in mig_stat else f"⚠ {mig_stat}"
                if "SUCCESS" in mig_stat:
                    stats["migrated"] += 1
                if not s_admin_url and u_url:
                    s_admin_url = u_url
                    df.at[s_idx, "Workingna Admin URL"] = s_admin_url

            elif answers.get("consent") == "❌ មិនយល់ព្រម (Declined)":
                migration_status = "DECLINED_BY_USER"
                df.at[s_idx, "Migration"] = "Declined"

            if survey_ok:
                df.at[s_idx, "Status"] = "Completed"
            else:
                df.at[s_idx, "Status"] = f"Incomplete ({survey_reason})"

            row_payload = {
                "Index": s_idx + 1,
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Phone (E.164)": s_e164,
                "Raw Phone": s_raw,
                "Candidate Name": s_recipient,
                "Username": s_uname,
                "User ID": s_info.get("id"),
                "Consent Transfer": answers.get("consent", ""),
                "Employment Status": answers.get("employment_status", ""),
                "Job Preference / Urgency": answers.get("job_preference", ""),
                "Expected Salary": answers.get("expected_salary", ""),
                "Preferred Location": answers.get("preferred_location", ""),
                "Voice Notes": "; ".join(answers.get("voice_files", [])),
                "Dialogue Summary": " | ".join(answers.get("raw_dialogue", [])),
                "Campaign Status": "Completed" if survey_ok else "Incomplete",
                "Notes": survey_reason,
                "Workingna Admin URL": s_admin_url or "",
                "Migration Status": migration_status,
                "TverKar Worker ID": tverkar_worker_id or ""
            }
            await ACIDStorageManager.record_campaign_result(row_payload)
        except Exception as err:
            df.at[s_idx, "Status"] = f"Error: {err}"
        finally:
            await service.delete_contact(s_info["id"])

    for idx, item in enumerate(parsed_items):
        if STOP_SIGNAL:
            yield df, f"Halted by user at #{idx}/{total}.", render_kpi_html(total, stats["registered"], stats["delivered"], stats["agreed"], stats["migrated"], stats["unregistered"])
            return

        raw = item["raw"]
        e164 = item["e164"]
        df.at[idx, "Status"] = "Checking..."

        # Query Workingna DB candidate profile
        workingna_profile = find_candidate_by_phone(e164)
        known_name = workingna_profile.get("candidate_name") if workingna_profile else None
        admin_url = workingna_profile.get("admin_url") if workingna_profile else (get_admin_url(workingna_profile.get("profile_id")) if workingna_profile else "")

        if admin_url:
            df.at[idx, "Workingna Admin URL"] = admin_url

        try:
            is_reg, info, user_entity = await service.check_phone_registration(e164, candidate_name=known_name, cleanup_contact=False)
            if is_reg and info:
                stats["registered"] += 1
                full_n = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
                uname = f"@{info.get('username')}" if info.get('username') else ""
                recipient_str = known_name or full_n or uname or f"User ID: {info['id']}"
                
                df.at[idx, "Candidate"] = recipient_str

                if auto_send:
                    df.at[idx, "Status"] = "Dispatched (Surveying...)"
                    stats["delivered"] += 1
                    final_msg = service.format_message_template(
                        message_text,
                        user_info={"first_name": recipient_str, "username": info.get("username")}
                    )

                    # Spawn concurrent background survey session
                    task = asyncio.create_task(_async_survey_worker(
                        idx, raw, e164, recipient_str, uname, info, user_entity, admin_url, workingna_profile, final_msg
                    ))
                    active_background_tasks.add(task)
                    task.add_done_callback(active_background_tasks.discard)

                    yield df, f"🚀 Dispatched [{idx + 1}/{total}] to {recipient_str} ({e164}). Next in {delay_s}s...", render_kpi_html(total, stats["registered"], stats["delivered"], stats["agreed"], stats["migrated"], stats["unregistered"])
                else:
                    df.at[idx, "Status"] = "Registered"
                    await service.delete_contact(info["id"])
            else:
                stats["unregistered"] += 1
                df.at[idx, "Candidate"] = known_name or "-"
                df.at[idx, "Consent"] = "-"
                df.at[idx, "Employment"] = "-"
                df.at[idx, "Expected Salary"] = "-"
                df.at[idx, "Migration"] = "-"
                df.at[idx, "Status"] = "Unregistered"
        except errors.FloodWaitError as e:
            df.at[idx, "Status"] = f"FloodWait: {e.seconds}s"
            break
        except Exception as e:
            df.at[idx, "Status"] = f"Error: {str(e)}"
            
        yield df, f"Queue [{idx + 1}/{total}] Dispatched", render_kpi_html(total, stats["registered"], stats["delivered"], stats["agreed"], stats["migrated"], stats["unregistered"])
        if idx < total - 1 and delay_s > 0 and auto_send:
            await asyncio.sleep(delay_s)

    # Monitor in-flight survey sessions while updating UI
    if active_background_tasks and auto_send:
        while active_background_tasks and not STOP_SIGNAL:
            yield df, f"🚀 All {total} messages dispatched! Listening for {len(active_background_tasks)} active candidate replies...", render_kpi_html(total, stats["registered"], stats["delivered"], stats["agreed"], stats["migrated"], stats["unregistered"])
            await asyncio.sleep(1.5)

    summary = f"🎉 Campaign Finished! Registered: {stats['registered']} | Delivered: {stats['delivered']} | Agreed: {stats['agreed']} | Migrated: {stats['migrated']}"
    yield df, summary, render_kpi_html(total, stats["registered"], stats["delivered"], stats["agreed"], stats["migrated"], stats["unregistered"])

# Async Handlers
async def on_start_autosend(phone_text, country, msg, delay_val, video_p, timeout_val):
    async for item in execute_batch(phone_text, country, True, msg, delay_val, video_path=video_p, survey_timeout=timeout_val):
        yield item

async def on_start_verify_only(phone_text, country, msg, delay_val):
    async for item in execute_batch(phone_text, country, False, "", 0):
        yield item

def build_app():
    with gr.Blocks(title="TeleSender Pro") as demo:
        # Compact Header
        with gr.Row(elem_classes=["app-header"]):
            with gr.Column(scale=3):
                gr.HTML(
                    """
                    <div class="app-brand">
                        <div>
                            <div class="app-title">⚡ TeleSender Pro · Workingna ➡️ TverKar</div>
                            <div class="app-subtitle">Candidate Outreach, Interactive Survey & Automated Profile Prefill Migration</div>
                        </div>
                    </div>
                    """
                )
            with gr.Column(scale=2):
                header_status = gr.HTML(
                    """
                    <div class="status-pill">
                        <span>Checking sender phone...</span>
                    </div>
                    """
                )

        with gr.Tabs():
            # Main Tab: Dedicated TverKar Campaign
            with gr.Tab("🚀 TverKar Outreach & Migration Campaign"):
                kpi_box = gr.HTML(render_kpi_html(0, 0, 0, 0, 0, 0))

                with gr.Row():
                    # Left Column: Target Numbers & Message Settings
                    with gr.Column(scale=5):
                        with gr.Group():
                            gr.Markdown("### 🎯 Smart Candidate Filter & Batch Selector")
                            with gr.Row():
                                filter_mode = gr.Dropdown(
                                    label="Filter Candidate Status", 
                                    choices=[
                                        "📁 All Numbers in Excel (Original Row Order)",
                                        "✨ Only Unsent (Fresh Candidates)",
                                        "⏳ Incomplete / No Reply (Follow-ups)",
                                        "✅ Completed / Agreed",
                                        "❌ Declined"
                                    ],
                                    value="📁 All Numbers in Excel (Original Row Order)",
                                    scale=3
                                )
                                batch_country = gr.Dropdown(
                                    label="Region", 
                                    choices=["KH", "US", "TH", "VN", "SG", "MY"], 
                                    value="KH",
                                    scale=1
                                )

                            with gr.Row():
                                batch_size_input = gr.Number(
                                    label="Batch Amount (Limit)", 
                                    value=100, 
                                    precision=0, 
                                    minimum=1,
                                    scale=1
                                )
                                offset_input = gr.Number(
                                    label="Start Offset", 
                                    value=0, 
                                    precision=0, 
                                    minimum=0,
                                    scale=1
                                )

                            with gr.Row():
                                btn_preset_25 = gr.Button("25", size="sm", scale=1)
                                btn_preset_50 = gr.Button("50", size="sm", scale=1)
                                btn_preset_100 = gr.Button("100", size="sm", scale=1)
                                btn_preset_200 = gr.Button("200", size="sm", scale=1)
                                btn_preset_all = gr.Button("All", size="sm", scale=1)
                                load_filtered_btn = gr.Button("🎯 Load Filtered Batch", variant="primary", scale=2)

                            db_stats_badge = gr.HTML(render_db_stats_badge())

                            with gr.Accordion("🔌 Or Query directly from Workingna MySQL DB", open=False):
                                with gr.Row():
                                    db_limit = gr.Number(label="Candidate Limit", value=50, precision=0, scale=1)
                                    db_looking = gr.Checkbox(label="Only Looking for Jobs", value=False, scale=1)
                                db_search = gr.Textbox(label="Search Candidate (Name / Phone)", placeholder="Optional keyword...")
                                db_fetch_btn = gr.Button("🔄 Query & Load from Workingna DB", variant="secondary")

                            phone_input = gr.Textbox(
                                label="Target Candidate Phone Numbers (Auto-Deduplicated)", 
                                value=get_default_phone_list(), 
                                lines=5,
                                placeholder="Paste phone numbers (one per line)..."
                            )

                        with gr.Group():
                            video_input = gr.Textbox(
                                label="🎬 1-Tap Video Asset (Compressed)",
                                value=config.default_video_path,
                                placeholder="video/TverKar&WN_using.mp4"
                            )
                            msg_input = gr.Textbox(
                                label="Outreach Message Caption (Supports [ឈ្មោះបេក្ខជន])", 
                                value=DEFAULT_OUTREACH_MESSAGE, 
                                lines=6
                            )

                        with gr.Row():
                            delay_input = gr.Number(
                                label="Delay (s)", 
                                value=15, 
                                precision=0, 
                                minimum=0,
                                scale=1
                            )
                            timeout_box = gr.Number(
                                label="Reply Timeout (s)", 
                                value=180, 
                                precision=0, 
                                minimum=10,
                                scale=1
                            )

                        with gr.Row():
                            send_btn = gr.Button("🚀 Start Outreach & Migration", variant="primary", scale=2)
                            verify_btn = gr.Button("Verify Only", variant="secondary", scale=1)
                            stop_btn = gr.Button("Stop", variant="stop", scale=1)

                    # Right Column: Clean Live Data Table
                    with gr.Column(scale=7):
                        status_ticker = gr.Markdown("**Status**: Ready to launch campaign.")
                        table_output = gr.Dataframe(
                            value=get_empty_df(),
                            headers=["#", "Phone (E.164)", "Candidate", "Workingna Admin URL", "Consent", "Employment", "Expected Salary", "Migration", "Status"],
                            datatype=["number", "str", "str", "str", "str", "str", "str", "str", "str"],
                            interactive=False,
                            wrap=True
                        )

                # Event Bindings for Main Tab
                def on_load_filtered(mode, size, off):
                    text, badge = filter_excel_candidates(mode, batch_size=size, offset=off)
                    return text, badge

                load_filtered_btn.click(
                    fn=on_load_filtered,
                    inputs=[filter_mode, batch_size_input, offset_input],
                    outputs=[phone_input, db_stats_badge]
                )

                # Preset buttons
                btn_preset_25.click(fn=lambda m, o: filter_excel_candidates(m, 25, o), inputs=[filter_mode, offset_input], outputs=[phone_input, db_stats_badge])
                btn_preset_50.click(fn=lambda m, o: filter_excel_candidates(m, 50, o), inputs=[filter_mode, offset_input], outputs=[phone_input, db_stats_badge])
                btn_preset_100.click(fn=lambda m, o: filter_excel_candidates(m, 100, o), inputs=[filter_mode, offset_input], outputs=[phone_input, db_stats_badge])
                btn_preset_200.click(fn=lambda m, o: filter_excel_candidates(m, 200, o), inputs=[filter_mode, offset_input], outputs=[phone_input, db_stats_badge])
                btn_preset_all.click(fn=lambda m, o: filter_excel_candidates(m, None, o), inputs=[filter_mode, offset_input], outputs=[phone_input, db_stats_badge])

                filter_mode.change(
                    fn=on_load_filtered,
                    inputs=[filter_mode, batch_size_input, offset_input],
                    outputs=[phone_input, db_stats_badge]
                )

                db_fetch_btn.click(
                    fn=load_candidates_from_workingna_db,
                    inputs=[db_limit, db_looking, db_search],
                    outputs=[phone_input]
                )
                
                send_btn.click(
                    fn=on_start_autosend,
                    inputs=[
                        phone_input, batch_country, msg_input, delay_input,
                        video_input, timeout_box
                    ],
                    outputs=[table_output, status_ticker, kpi_box]
                )

                verify_btn.click(
                    fn=on_start_verify_only,
                    inputs=[phone_input, batch_country, msg_input, delay_input],
                    outputs=[table_output, status_ticker, kpi_box]
                )

                stop_btn.click(fn=set_stop, outputs=[status_ticker])

            # Tab 2: TverKar Candidate Responses Viewer & Filter Manager
            with gr.Tab("📊 Campaign & Migration Results"):
                gr.Markdown("### 🎯 TverKar Candidate Results & Workingna Admin Links")
                
                with gr.Row():
                    res_search = gr.Textbox(label="🔍 Search Candidate (Phone / Name / Username)", placeholder="Type phone, name or username...", scale=3)
                    res_status = gr.Dropdown(
                        label="Filter Results by Status", 
                        choices=["All", "Agreed", "Declined", "Incomplete", "Unregistered"],
                        value="All", 
                        scale=2
                    )
                    filter_res_btn = gr.Button("🔍 Apply Filter", variant="secondary", scale=1)

                with gr.Row():
                    refresh_tverkar_btn = gr.Button("🔄 Refresh All Results", variant="primary", scale=2)
                    sync_sheets_btn = gr.Button("☁ Sync Local CSV to Google Sheets", variant="secondary", scale=2)
                    open_sheets_btn = gr.Button(
                        "📊 Open Google Sheets ↗", 
                        link=config.google_sheet_url, 
                        variant="secondary",
                        scale=2
                    )
                
                sheets_sync_status = gr.Markdown(
                    f"**Google Sheets Target:** [{config.google_sheet_url}]({config.google_sheet_url})  \n"
                    f"*Status:* {'🟢 Auto-Update Webhook Active' if config.google_sheet_webhook_url else '🟡 Webhook URL not set in .env (Updates saved locally)'}"
                )

                tverkar_table = gr.Dataframe(
                    value=get_tverkar_df(),
                    interactive=False,
                    wrap=True
                )

                def on_manual_sheets_sync():
                    ok, msg, count = sync_bulk_csv_to_google_sheet()
                    if ok:
                        return f"✅ {msg}"
                    else:
                        return f"⚠ {msg}"

                filter_res_btn.click(fn=get_tverkar_df, inputs=[res_search, res_status], outputs=[tverkar_table])
                res_status.change(fn=get_tverkar_df, inputs=[res_search, res_status], outputs=[tverkar_table])
                refresh_tverkar_btn.click(fn=lambda: get_tverkar_df("", "All"), outputs=[tverkar_table])
                sync_sheets_btn.click(fn=on_manual_sheets_sync, outputs=[sheets_sync_status])

            # Tab 3: Pre-Flight Production Risk & System Health Check
            with gr.Tab("🛡️ Production Risk & Health Check"):
                gr.Markdown("### 🛡️ Pre-Flight Production Risk & System Validator")
                gr.Markdown(
                    "Before launching large-scale outreach to hundreds of candidates, run this pre-flight check to verify "
                    "Telegram session authorization, database connections, and Google Sheets webhook health."
                )

                preflight_btn = gr.Button("🛡️ Run Pre-Flight Production Health Check", variant="primary")
                preflight_output = gr.HTML("<div style='color: #94a3b8; padding: 10px;'>Click above to run complete system validation.</div>")

                async def on_run_preflight():
                    from src.telebot.core.health import run_preflight_production_check, render_preflight_html
                    rep = await run_preflight_production_check()
                    return render_preflight_html(rep)

                preflight_btn.click(fn=on_run_preflight, outputs=[preflight_output])

                gr.Markdown(
                    """
                    ---
                    ### 📋 Production Safety & Anti-Ban Guidelines:
                    1. **24/7 Persistent Session Resume**: Candidates can reply at **any time** (now, hours later, or tomorrow). The persistent background listener will automatically continue their survey and complete their migration.
                    2. **Human-like Jitter Delay**: Keep delay between **15s – 35s** to simulate human sending cadence.
                    3. **Recommended Batch Size**: For standard accounts, send in batches of **50 – 100 numbers per hour** to maintain high account reputation.
                    4. **Automated FloodWait Recovery**: If Telegram issues a cooldown, the bot pauses and resumes automatically without losing progress.
                    """
                )

            # Tab 4: Telegram Account & Authentication
            with gr.Tab("📱 Telegram Account & Login"):
                gr.Markdown("### 📱 Telegram Sender Account Management")
                account_info_box = gr.HTML("<div style='color: #94a3b8;'>Loading account details...</div>")

                with gr.Row():
                    auth_phone_input = gr.Textbox(label="Sender Phone Number", value=config.phone, placeholder="+855XXXXXXXX")
                    req_code_btn = gr.Button("📩 Request OTP Login Code", variant="primary")

                with gr.Row():
                    auth_code_input = gr.Textbox(label="Verification Code (OTP)", placeholder="Enter 5-digit code...")
                    auth_pwd_input = gr.Textbox(label="2FA Password (if enabled)", type="password", placeholder="Enter 2FA password...")
                    login_submit_btn = gr.Button("🔐 Sign In & Authenticate", variant="secondary")

                auth_result_status = gr.Markdown("")

                async def on_req_code(phone):
                    ok, msg = await service.send_auth_code(phone.strip())
                    return f"**Status:** {msg}"

                async def get_account_status_html():
                    try:
                        if await service.is_authenticated():
                            me = await service.get_me_info()
                            if me:
                                return f"""
                                <div style='background: #064e3b; border: 1px solid #059669; padding: 14px; border-radius: 8px; color: #ecfdf5;'>
                                    <div style='font-size: 16px; font-weight: 700;'>✅ Active Sender: {me['first_name']} {me['last_name']} (@{me.get('username') or 'NoUsername'})</div>
                                    <div style='font-size: 13px; margin-top: 4px;'>Phone: <b>{me['phone']}</b> | Telegram User ID: <b>{me['id']}</b> | Premium: <b>{me.get('premium', False)}</b></div>
                                </div>
                                """
                    except Exception:
                        pass
                    return """
                    <div style='background: #450a0a; border: 1px solid #dc2626; padding: 14px; border-radius: 8px; color: #fef2f2;'>
                        <div style='font-size: 16px; font-weight: 700;'>❌ Sender Account Not Logged In</div>
                        <div style='font-size: 13px; margin-top: 4px;'>Please enter your phone number above and click 'Request OTP Login Code' to log in.</div>
                    </div>
                    """

                async def on_sign_in(code, pwd):
                    ok, msg, need_2fa = await service.sign_in_with_code(code.strip(), pwd.strip() if pwd else None)
                    hdr = await check_header_status()
                    acc_html = await get_account_status_html()
                    return f"**Status:** {msg}", hdr, acc_html

                req_code_btn.click(fn=on_req_code, inputs=[auth_phone_input], outputs=[auth_result_status])
                login_submit_btn.click(
                    fn=on_sign_in,
                    inputs=[auth_code_input, auth_pwd_input],
                    outputs=[auth_result_status, header_status, account_info_box]
                )

        demo.load(fn=check_header_status, outputs=[header_status])
    return demo

def main():
    app = build_app()
    port = find_available_port(7860, 7890)
    print(f"🚀 Starting TeleSender Pro on http://127.0.0.1:{port}")
    
    launch_kwargs = {
        "server_name": "127.0.0.1",
        "inbrowser": True,
        "css": CUSTOM_CSS,
        "theme": gr.themes.Soft()
    }
    if port != 0:
        launch_kwargs["server_port"] = port
        
    app.launch(**launch_kwargs)

if __name__ == "__main__":
    main()
