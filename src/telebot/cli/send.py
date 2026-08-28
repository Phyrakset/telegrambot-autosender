import os
import sys
import json
import asyncio
import argparse
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict, Any
from tabulate import tabulate
from colorama import init, Fore, Style
from telethon import custom

from src.telebot.config import config
from src.telebot.utils.phone import load_phone_numbers, format_phone_e164
from src.telebot.core.service import TelegramService
from src.telebot.db.workingna import fetch_workingna_candidates, find_candidate_by_phone, get_admin_url
from src.telebot.core.migration import MigrationEngine
from src.telebot.integrations.google_sheets import sync_result_to_google_sheet
from src.telebot.core.storage import ACIDStorageManager

init(autoreset=True)

async def run_auto_send(
    phone_file: Optional[str] = "all_Phone_barstar_service_cashair.xlsx" if os.path.exists("all_Phone_barstar_service_cashair.xlsx") else "phone-list.txt",
    from_db: bool = False,
    db_limit: int = 50,
    db_only_looking: bool = False,
    db_search: Optional[str] = None,
    message_template: Optional[str] = None,
    default_country: str = "KH",
    delay_seconds: int = 2,
    video_path: Optional[str] = None,
    survey_timeout: int = 180,
    campaign_mode: str = "tverkar",
    limit: Optional[int] = None
):
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗")
    print(f"{Fore.CYAN}║   🚀 TELEGRAM OUTREACH & WORKINGNA-TO-TVERKAR MIGRATION ENGINE  ║")
    print(f"{Fore.CYAN}║      Mode: {campaign_mode.upper():<54}║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}\n")

    if message_template is None:
        message_template = config.tverkar_initial_message if campaign_mode == "tverkar" else "Hello {name}! Watch this short introduction video."

    if video_path is None:
        video_path = config.default_video_path

    # Load candidates either from Workingna DB or local phone file
    candidate_items: List[Dict[str, Any]] = []
    if from_db:
        print(f"🔄 Fetching candidates from {Fore.YELLOW}Workingna MySQL DB{Style.RESET_ALL}...")
        try:
            db_candidates = fetch_workingna_candidates(
                limit=db_limit,
                only_looking=db_only_looking,
                has_phone_only=True,
                search=db_search
            )
            for c in db_candidates:
                if c["e164_phone"]:
                    candidate_items.append({
                        "raw": c["raw_phone"],
                        "e164": c["e164_phone"],
                        "name": c["candidate_name"],
                        "admin_url": c["admin_url"],
                        "profile_id": c["profile_id"],
                        "profile_data": c
                    })
            print(f"✔ Successfully loaded {Fore.GREEN}{len(candidate_items)}{Style.RESET_ALL} candidates with phone numbers from Workingna DB.")
        except Exception as e:
            print(f"{Fore.RED}❌ Error loading candidates from Workingna DB: {e}{Style.RESET_ALL}")
            return
    else:
        if not phone_file or not os.path.exists(phone_file):
            print(f"{Fore.RED}❌ Error: Phone list file '{phone_file}' not found.{Style.RESET_ALL}")
            return
        numbers = load_phone_numbers(phone_file, default_region=default_country)
        for num in numbers:
            candidate_items.append({
                "raw": num["raw"],
                "e164": num["e164"],
                "name": None,
                "admin_url": None,
                "profile_id": None,
                "profile_data": None
            })

    if limit and limit > 0 and len(candidate_items) > limit:
        candidate_items = candidate_items[:limit]

    total_count = len(candidate_items)
    if total_count == 0:
        print(f"{Fore.YELLOW}⚠ No target phone numbers found to process.{Style.RESET_ALL}")
        return

    print(f"📁 Target Queue        : {Fore.YELLOW}{total_count}{Style.RESET_ALL} candidates loaded ({'Workingna DB' if from_db else phone_file}){' [Limited to ' + str(limit) + ']' if limit else ''}")
    print(f"⏱️ Safety Delay        : {Fore.YELLOW}{delay_seconds}s{Style.RESET_ALL} between messages")
    if video_path:
        print(f"🎬 Video Attachment    : {Fore.CYAN}{video_path}{Style.RESET_ALL} ({'Found' if os.path.exists(video_path) else 'NOT FOUND!'})")
    print(f"🎯 Campaign Mode       : {Fore.MAGENTA}{campaign_mode.upper()}{Style.RESET_ALL}")
    print(f"💬 Message Preview     :\n{Fore.LIGHTBLACK_EX}--- Message Start ---\n{message_template[:250]}...\n--- Message End ---{Style.RESET_ALL}\n")

    service = TelegramService()
    try:
        await service.connect()
        if not await service.is_authenticated():
            print(f"{Fore.RED}❌ Error: Telegram session is not authorized. Please log in first.{Style.RESET_ALL}")
            return
        me = await service.get_me_info()
        print(f"📱 Active Sender Phone : {Fore.GREEN}{me['first_name']} {me['last_name']} (@{me['username'] or 'NoUsername'}){Style.RESET_ALL} | ID: {me['id']}\n")
    except Exception as e:
        print(f"{Fore.RED}❌ Connection error: {e}{Style.RESET_ALL}")
        return

    cached_media = None
    if video_path and os.path.exists(video_path):
        try:
            print(f"🔄 Preparing & caching video '{video_path}'... ", end="", flush=True)
            cached_media = await service.upload_and_cache_video(video_path)
            print(f"{Fore.GREEN}[CACHED READY]{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[CACHE ERROR: {e}]{Style.RESET_ALL}")

    results = []
    tverkar_campaign_results = []
    if os.path.exists(config.tverkar_results_csv):
        try:
            existing_df = pd.read_csv(config.tverkar_results_csv, encoding="utf-8-sig")
            tverkar_campaign_results = existing_df.to_dict(orient="records")
        except Exception:
            tverkar_campaign_results = []

    table_rows = []
    active_tasks = []
    stats = {
        "total": total_count,
        "registered": 0,
        "unregistered": 0,
        "delivered": 0,
        "failed": 0,
        "survey_completed": 0,
        "consent_agreed": 0,
        "consent_declined": 0,
        "migrated_success": 0
    }

    start_time = datetime.now()

    for index, item in enumerate(candidate_items, 1):
        raw = item["raw"]
        e164 = item["e164"]
        known_name = item.get("name")
        known_admin_url = item.get("admin_url")
        profile_data = item.get("profile_data")

        # If admin_url isn't loaded yet, try looking up candidate by phone in Workingna DB
        if not known_admin_url or not profile_data:
            found_prof = find_candidate_by_phone(e164)
            if found_prof:
                profile_data = found_prof
                known_admin_url = found_prof.get("admin_url") or get_admin_url(found_prof.get("profile_id"))
                if not known_name:
                    known_name = found_prof.get("candidate_name")

        print(f"[{index:02d}/{total_count:02d}] Checking {Fore.BLUE}{e164}{Style.RESET_ALL} (raw: {raw})... ", end="", flush=True)

        try:
            is_reg, info, user_entity = await service.check_phone_registration(e164, candidate_name=known_name, cleanup_contact=False)
            
            if is_reg and info:
                stats["registered"] += 1
                first_n = info.get('first_name', '')
                last_n = info.get('last_name', '')
                full_n = f"{first_n} {last_n}".strip()
                uname = f"@{info['username']}" if info.get('username') else "-"
                disp_name = known_name or (full_n if full_n else (uname if uname != "-" else "Unknown"))

                print(f"{Fore.GREEN}[REGISTERED]{Style.RESET_ALL} -> {disp_name} ({uname})")

                if info.get("is_deleted", False):
                    print(f"       [SKIPPED: Deleted Account]")
                    table_rows.append([index, e164, "Deleted Account", disp_name, uname, "Skipped", "Account deleted"])
                    results.append({
                        "index": index,
                        "raw_phone": raw,
                        "normalized_e164": e164,
                        "registration": "Deleted Account",
                        "recipient": disp_name,
                        "delivery_status": "Skipped",
                        "reason": "Account deleted by user"
                    })
                    await service.delete_contact(info["id"])
                elif user_entity:
                    # Format message using candidate name
                    final_msg = service.format_message_template(
                        message_template,
                        user_info={"first_name": disp_name, "username": info.get("username")}
                    )

                    stats["registered"] += 1
                    stats["delivered"] += 1
                    print(f"{Fore.GREEN}[REGISTERED]{Style.RESET_ALL} -> {disp_name} (@{uname or 'NoUser'}) [ID: {info.get('id')}]")

                    # Worker for individual candidate session
                    async def _handle_candidate_outreach(
                        s_idx: int,
                        s_raw: str,
                        s_e164: str,
                        s_disp: str,
                        s_uname: str,
                        s_info: Dict[str, Any],
                        s_entity: Any,
                        s_admin_url: Optional[str],
                        s_pdata: Optional[Dict[str, Any]],
                        s_msg: str
                    ):
                        try:
                            print(f"       {Fore.MAGENTA}▶ [Async Session #{s_idx}] Outreach dispatched to {s_disp} ({s_e164}). Listening for replies...{Style.RESET_ALL}")
                            survey_ok, answers, survey_reason = await service.conduct_tverkar_campaign_session(
                                s_entity,
                                initial_message=s_msg,
                                media=cached_media,
                                timeout=survey_timeout,
                                phone_identifier=s_e164,
                                user_info=s_info
                            )

                            s_mig_stat = "N/A"
                            s_worker_id = None

                            if answers.get("consent") == "✅ យល់ព្រម (Agreed)":
                                stats["consent_agreed"] += 1
                                print(f"       {Fore.CYAN}🔄 [Async Session #{s_idx}] Initiating TverKar migration for {s_disp}...{Style.RESET_ALL}")
                                mig_stat, w_id, url = MigrationEngine.migrate_consenting_candidate(
                                    phone=s_e164,
                                    survey_answers=answers,
                                    telegram_user_info=s_info,
                                    workingna_profile=s_pdata
                                )
                                s_mig_stat = mig_stat
                                s_worker_id = w_id
                                if not s_admin_url and url:
                                    s_admin_url = url

                                if "SUCCESS" in mig_stat:
                                    stats["migrated_success"] += 1
                                    print(f"       {Fore.GREEN}🎉 [Async Session #{s_idx}] Successfully migrated {s_disp} -> TverKar Worker ID: {w_id}{Style.RESET_ALL}")
                                else:
                                    print(f"       {Fore.YELLOW}⚠ [Async Session #{s_idx}] Migration Notice: {mig_stat}{Style.RESET_ALL}")

                            elif answers.get("consent") == "❌ មិនយល់ព្រម (Declined)":
                                stats["consent_declined"] += 1
                                s_mig_stat = "DECLINED_BY_USER"

                            if survey_ok:
                                stats["survey_completed"] += 1
                                print(f"       {Fore.GREEN}✔ [Async Session #{s_idx}] Survey Finished for {s_disp}! Consent: {answers.get('consent')} | Employment: {answers.get('employment_status')}{Style.RESET_ALL}")
                            else:
                                print(f"       {Fore.YELLOW}⚠ [Async Session #{s_idx}] Survey Incomplete for {s_disp}: {survey_reason}{Style.RESET_ALL}")

                            row_payload = {
                                "Index": s_idx,
                                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "Phone (E.164)": s_e164,
                                "Raw Phone": s_raw,
                                "Candidate Name": s_disp,
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
                                "Migration Status": s_mig_stat,
                                "TverKar Worker ID": s_worker_id or ""
                            }

                            # ACID Atomic Write & Real-Time Cloud Sync
                            await ACIDStorageManager.record_campaign_result(row_payload)
                            table_rows.append([s_idx, s_e164, "Registered", s_disp, s_uname, "Delivered", f"{answers.get('consent', 'Done')} | Mig: {s_mig_stat}"])
                        except Exception as err:
                            stats["failed"] += 1
                            print(f"       {Fore.RED}❌ [Async Session #{s_idx}] Error for {s_disp}: {err}{Style.RESET_ALL}")
                        finally:
                            await service.delete_contact(s_info["id"])

                    # Spawn asynchronous background survey worker
                    task = asyncio.create_task(_handle_candidate_outreach(
                        index, raw, e164, disp_name, uname, info, user_entity, known_admin_url, profile_data, final_msg
                    ))
                    active_tasks.append(task)

                    if index < total_count and delay_seconds > 0:
                        print(f"       ⏳ [Dispatch Queue] Dispatched #{index}. Next candidate in {Fore.MAGENTA}{delay_seconds}s{Style.RESET_ALL}...\n")
                        await asyncio.sleep(delay_seconds)

            else:
                stats["unregistered"] += 1
                print(f"{Fore.YELLOW}[UNREGISTERED / HIDDEN - SKIPPED]{Style.RESET_ALL}")
                reason_text = "Number not registered on Telegram"
                table_rows.append([index, e164, "Unregistered", known_name or "-", "-", "Skipped", reason_text])
                results.append({
                    "index": index,
                    "raw_phone": raw,
                    "normalized_e164": e164,
                    "registration": "Unregistered",
                    "recipient": known_name or "-",
                    "delivery_status": "Skipped",
                    "reason": reason_text
                })
                if index < total_count:
                    await asyncio.sleep(0.3)

        except Exception as e:
            stats["failed"] += 1
            print(f"{Fore.RED}[ERROR: {e}]{Style.RESET_ALL}")
            table_rows.append([index, e164, "Error", known_name or "-", "-", "Error", str(e)])
            results.append({
                "index": index,
                "raw_phone": raw,
                "normalized_e164": e164,
                "registration": "Error",
                "recipient": known_name or "-",
                "delivery_status": "Error",
                "reason": str(e)
            })

    # Wait for any in-flight survey sessions to conclude
    if active_tasks:
        print(f"\n{Fore.CYAN}══════════════════════════════════════════════════════════════════")
        print(f"🚀 ALL INITIAL OUTREACH MESSAGES DISPATCHED!")
        print(f"🔄 Waiting for {len(active_tasks)} active candidate survey sessions to finish...")
        print(f"══════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
        await asyncio.gather(*active_tasks, return_exceptions=True)
        print(f"{Fore.GREEN}✔ All background survey sessions completed!{Style.RESET_ALL}")

    elapsed = (datetime.now() - start_time).total_seconds()

    print("\n" + tabulate(
        table_rows,
        headers=["#", "Phone (E.164)", "Registration", "Name", "Username", "Delivery Status", "Details"],
        tablefmt="grid"
    ))

    print(f"\n{Fore.GREEN}══════════════════════════════════════════════════════════════════")
    print(f"📊 EXECUTION & MIGRATION SUMMARY REPORT")
    print(f"══════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"• Total Numbers Checked : {Fore.YELLOW}{stats['total']}{Style.RESET_ALL}")
    print(f"• Registered Accounts   : {Fore.GREEN}{stats['registered']}{Style.RESET_ALL}")
    print(f"• Messages/Videos Sent  : {Fore.GREEN}{stats['delivered']}{Style.RESET_ALL}")
    print(f"• Consent Agreed (✅)    : {Fore.GREEN}{stats['consent_agreed']}{Style.RESET_ALL}")
    print(f"• Migrated to TverKar   : {Fore.GREEN}{stats['migrated_success']}{Style.RESET_ALL}")
    print(f"• Consent Declined (❌)  : {Fore.RED}{stats['consent_declined']}{Style.RESET_ALL}")
    print(f"• Total Elapsed Time    : {Fore.CYAN}{elapsed:.1f} seconds{Style.RESET_ALL}")
    print(f"{Fore.GREEN}══════════════════════════════════════════════════════════════════{Style.RESET_ALL}\n")

    await service.disconnect()

def main():
    parser = argparse.ArgumentParser(description="Telegram Outreach, Workingna Candidate Query & TverKar Migration Engine")
    parser.add_argument("file", nargs="?", default="all_Phone_barstar_service_cashair.xlsx" if os.path.exists("all_Phone_barstar_service_cashair.xlsx") else "phone-list.txt", help="Path to phone numbers Excel or text file")
    parser.add_argument("--limit", type=int, default=None, help="Limit total candidates to process (e.g. --limit 100)")
    parser.add_argument("--db", action="store_true", help="Fetch candidates directly from Workingna MySQL DB")
    parser.add_argument("--db-limit", type=int, default=50, help="Max candidates to query from Workingna DB")
    parser.add_argument("--db-looking", action="store_true", help="Only query candidates with lookingForJobs=1")
    parser.add_argument("--msg", default=None, help="Custom message text / caption")
    parser.add_argument("--country", default=config.default_country, help="Default ISO country code (e.g. KH)")
    parser.add_argument("--delay", type=int, default=2, help="Delay in seconds between messages (default: 2)")
    parser.add_argument("--video", default=None, help="Path to video file")
    parser.add_argument("--timeout", type=int, default=180, help="Survey response timeout in seconds")

    args = parser.parse_args()
    asyncio.run(run_auto_send(
        phone_file=args.file,
        from_db=args.db,
        db_limit=args.db_limit,
        db_only_looking=args.db_looking,
        message_template=args.msg,
        default_country=args.country,
        delay_seconds=args.delay,
        video_path=args.video,
        survey_timeout=args.timeout,
        campaign_mode="tverkar",
        limit=args.limit
    ))

if __name__ == "__main__":
    main()
