import os
import sys
import json
import asyncio
import argparse
import pandas as pd
from datetime import datetime
from tabulate import tabulate
from colorama import init, Fore, Style
from telethon import custom

from src.telebot.config import config
from src.telebot.utils.phone import load_phone_numbers
from src.telebot.core.service import TelegramService

init(autoreset=True)

DEFAULT_MESSAGE = config.tverkar_initial_message

async def run_auto_send(
    phone_file: str = "phone-list.txt",
    message_template: str = None,
    default_country: str = "KH",
    delay_seconds: int = 2,
    video_path: str = "video/TverKar&WN_using.mp4",
    survey_timeout: int = 180,
    campaign_mode: str = "tverkar"
):
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗")
    print(f"{Fore.CYAN}║   🚀 TELEGRAM OUTREACH + VIDEO & INTERACTIVE SURVEY ENGINE       ║")
    print(f"{Fore.CYAN}║      Mode: {campaign_mode.upper():<54}║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}\n")

    if not os.path.exists(phone_file):
        print(f"{Fore.RED}❌ Error: File '{phone_file}' not found.")
        return

    if message_template is None:
        message_template = config.tverkar_initial_message if campaign_mode == "tverkar" else "Hello {name}! Watch this short introduction video."

    if video_path is None:
        video_path = config.default_video_path

    if not survey_questions:
        survey_questions = [DEFAULT_Q1, DEFAULT_Q2, DEFAULT_Q3]

    numbers = load_phone_numbers(phone_file, default_region=default_country)
    total_count = len(numbers)
    print(f"📁 Target Numbers File : {Fore.YELLOW}{phone_file}{Style.RESET_ALL} ({total_count} numbers loaded)")
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
    survey_results = []
    tverkar_campaign_results = []
    if os.path.exists(config.tverkar_results_csv):
        try:
            existing_df = pd.read_csv(config.tverkar_results_csv, encoding="utf-8-sig")
            tverkar_campaign_results = existing_df.to_dict(orient="records")
        except Exception:
            tverkar_campaign_results = []
    table_rows = []
    stats = {
        "total": total_count,
        "registered": 0,
        "unregistered": 0,
        "delivered": 0,
        "privacy_blocked": 0,
        "failed": 0,
        "survey_completed": 0,
        "consent_agreed": 0,
        "consent_declined": 0
    }

    start_time = datetime.now()

    for index, item in enumerate(numbers, 1):
        raw = item["raw"]
        e164 = item["e164"]

        print(f"[{index:02d}/{total_count:02d}] Checking {Fore.BLUE}{e164}{Style.RESET_ALL} (raw: {raw})... ", end="", flush=True)

        try:
            is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
            
            if is_reg and info:
                stats["registered"] += 1
                first_n = info.get('first_name', '')
                last_n = info.get('last_name', '')
                full_n = f"{first_n} {last_n}".strip()
                uname = f"@{info['username']}" if info.get('username') else "-"
                disp_name = full_n if full_n else (uname if uname != "-" else "Unknown")

                print(f"{Fore.GREEN}[REGISTERED]{Style.RESET_ALL} -> {disp_name} ({uname})")

                if info.get("is_deleted", False):
                    print(f"       [SKIPPED: Deleted Account]")
                    table_rows.append([index, e164, "Deleted Account", disp_name, uname, "Skipped", "Account deleted by user"])
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
                    final_msg = service.format_message_template(message_template, user_info=info)
                    
                    btn_consent = [
                        [custom.Button.text("✅ យល់ព្រម ", resize=True, single_use=True), custom.Button.text("❌ មិនយល់ព្រមទេ", resize=True, single_use=True)]
                    ] if campaign_mode == "tverkar" else None

                    print(f"       {Fore.MAGENTA}▶ Engaging TverKar Video Outreach & Interactive Survey (timeout: {survey_timeout}s)...{Style.RESET_ALL}")
                    survey_ok, answers, survey_reason = await service.conduct_tverkar_campaign_session(
                        user_entity,
                        initial_message=final_msg,
                        media=cached_media,
                        timeout=survey_timeout,
                        phone_identifier=e164,
                        user_info=info
                    )

                    stats["delivered"] += 1
                    if answers.get("consent") == "✅ យល់ព្រម (Agreed)":
                        stats["consent_agreed"] += 1
                    elif answers.get("consent") == "❌ មិនយល់ព្រម (Declined)":
                        stats["consent_declined"] += 1

                    if survey_ok:
                        stats["survey_completed"] += 1
                        print(f"       {Fore.GREEN}✔ TverKar Session Finished! Status: {answers.get('consent')} | Employment: {answers.get('employment_status')}{Style.RESET_ALL}")
                    else:
                        print(f"       {Fore.YELLOW}⚠ Session Complete: {survey_reason}{Style.RESET_ALL}")

                    tverkar_campaign_results.append({
                        "Index": index,
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Phone (E.164)": e164,
                        "Raw Phone": raw,
                        "Candidate Name": disp_name,
                        "Username": uname,
                        "User ID": info.get("id"),
                        "Consent Transfer": answers.get("consent", ""),
                        "Employment Status": answers.get("employment_status", ""),
                        "Job Preference / Urgency": answers.get("job_preference", ""),
                        "Expected Salary": answers.get("expected_salary", ""),
                        "Preferred Location": answers.get("preferred_location", ""),
                        "Voice Notes": "; ".join(answers.get("voice_files", [])),
                        "Dialogue Summary": " | ".join(answers.get("raw_dialogue", [])),
                        "Campaign Status": "Completed" if survey_ok else "Incomplete",
                        "Notes": survey_reason
                    })

                    table_rows.append([index, e164, "Registered", disp_name, uname, "Delivered", f"✔ {answers.get('consent', 'Done')}"])
                    results.append({
                        "index": index,
                        "raw_phone": raw,
                        "normalized_e164": e164,
                        "registration": "Registered",
                        "recipient": disp_name,
                        "delivery_status": "Delivered",
                        "reason": survey_reason
                    })
                    await service.delete_contact(info["id"])

                    if index < total_count and delay_seconds > 0:
                        print(f"       Delay: waiting {Fore.MAGENTA}{delay_seconds}s{Style.RESET_ALL} before next number...\n")
                        await asyncio.sleep(delay_seconds)

            else:
                stats["unregistered"] += 1
                print(f"{Fore.YELLOW}[UNREGISTERED / HIDDEN - SKIPPED]{Style.RESET_ALL}")
                reason_text = "Number not registered on Telegram"
                table_rows.append([index, e164, "Unregistered", "-", "-", "Skipped", reason_text])
                results.append({
                    "index": index,
                    "raw_phone": raw,
                    "normalized_e164": e164,
                    "registration": "Unregistered",
                    "recipient": "-",
                    "delivery_status": "Skipped",
                    "reason": reason_text
                })
                if index < total_count:
                    await asyncio.sleep(0.3)

        except Exception as e:
            stats["failed"] += 1
            print(f"{Fore.RED}[ERROR: {e}]{Style.RESET_ALL}")
            table_rows.append([index, e164, "Error", "-", "-", "Error", str(e)])
            results.append({
                "index": index,
                "raw_phone": raw,
                "normalized_e164": e164,
                "registration": "Error",
                "recipient": "-",
                "delivery_status": "Error",
                "reason": str(e)
            })

    elapsed = (datetime.now() - start_time).total_seconds()

    print("\n" + tabulate(
        table_rows,
        headers=["#", "Phone (E.164)", "Registration", "Name", "Username", "Delivery Status", "Reason / Details"],
        tablefmt="grid"
    ))

    print(f"\n{Fore.GREEN}══════════════════════════════════════════════════════════════════")
    print(f"📊 EXECUTION SUMMARY REPORT")
    print(f"══════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"• Total Numbers Checked : {Fore.YELLOW}{stats['total']}{Style.RESET_ALL}")
    print(f"• Registered Accounts   : {Fore.GREEN}{stats['registered']}{Style.RESET_ALL}")
    print(f"• Messages/Videos Sent  : {Fore.GREEN}{stats['delivered']}{Style.RESET_ALL}")
    if campaign_mode == "tverkar":
        print(f"• Consent Agreed (✅)    : {Fore.GREEN}{stats['consent_agreed']}{Style.RESET_ALL}")
        print(f"• Consent Declined (❌)  : {Fore.RED}{stats['consent_declined']}{Style.RESET_ALL}")
        print(f"• Sessions Completed    : {Fore.MAGENTA}{stats['survey_completed']}{Style.RESET_ALL}")
    elif enable_survey:
        print(f"• Surveys Completed     : {Fore.MAGENTA}{stats['survey_completed']}{Style.RESET_ALL}")
    print(f"• Privacy Restricted    : {Fore.YELLOW}{stats['privacy_blocked']}{Style.RESET_ALL}")
    print(f"• Unregistered / Skipped: {Fore.YELLOW}{stats['unregistered']}{Style.RESET_ALL}")
    print(f"• Failed Errors         : {Fore.RED}{stats['failed']}{Style.RESET_ALL}")
    print(f"• Total Elapsed Time    : {Fore.CYAN}{elapsed:.1f} seconds{Style.RESET_ALL}")
    print(f"{Fore.GREEN}══════════════════════════════════════════════════════════════════{Style.RESET_ALL}\n")

    with open(config.results_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"JSON Log saved to: {Fore.CYAN}{config.results_json}{Style.RESET_ALL}")

    try:
        df = pd.DataFrame(results)
        df.rename(columns={
            "index": "#",
            "normalized_e164": "Phone (E.164)",
            "registration": "Registration",
            "recipient": "Recipient",
            "delivery_status": "Delivery Status",
            "reason": "Reason"
        }, inplace=True)
        df.to_csv(config.results_csv, index=False, encoding="utf-8-sig")
        print(f"Delivery CSV saved to: {Fore.CYAN}{config.results_csv}{Style.RESET_ALL}")
    except Exception as e:
        print(f"Notice: CSV export note: {e}")

    if campaign_mode == "tverkar" and tverkar_campaign_results:
        try:
            tverkar_df = pd.DataFrame(tverkar_campaign_results)
            tverkar_df.to_csv(config.tverkar_results_csv, index=False, encoding="utf-8-sig")
            print(f"🎯 TverKar Candidate Results saved to: {Fore.GREEN}{config.tverkar_results_csv}{Style.RESET_ALL}")
        except Exception as e:
            print(f"Notice: TverKar CSV export error: {e}")

    elif enable_survey and survey_results:
        try:
            survey_df = pd.DataFrame(survey_results)
            survey_df.to_csv(config.survey_results_csv, index=False, encoding="utf-8-sig")
            print(f"Survey Responses saved to: {Fore.MAGENTA}{config.survey_results_csv}{Style.RESET_ALL}")
        except Exception as e:
            print(f"Notice: Survey CSV export note: {e}")

    await service.disconnect()

def main():
    parser = argparse.ArgumentParser(description="Telegram Outreach, Video Sender & Survey Engine")
    parser.add_argument("file", nargs="?", default="phone-list.txt", help="Path to phone numbers text file")
    parser.add_argument("--msg", default=None, help="Custom message text / caption")
    parser.add_argument("--country", default=config.default_country, help="Default ISO country code (e.g. KH)")
    parser.add_argument("--delay", type=int, default=2, help="Delay in seconds between messages (default: 2)")
    parser.add_argument("--video", default=None, help="Path to video file (default: video/TverKar&WN_using.mp4)")
    parser.add_argument("--campaign", default="tverkar", choices=["tverkar", "standard", "none"], help="Campaign workflow mode")
    parser.add_argument("--survey", action="store_true", help="Enable standard 3-question survey flow")
    parser.add_argument("--timeout", type=int, default=180, help="Survey response timeout in seconds (default: 180)")
    parser.add_argument("--q1", default=DEFAULT_Q1, help="Survey Question 1")
    parser.add_argument("--q2", default=DEFAULT_Q2, help="Survey Question 2")
    parser.add_argument("--q3", default=DEFAULT_Q3, help="Survey Question 3")
    
    args = parser.parse_args()

    questions = [args.q1, args.q2, args.q3]

    try:
        asyncio.run(run_auto_send(
            phone_file=args.file,
            message_template=args.msg,
            default_country=args.country,
            delay_seconds=args.delay,
            video_path=args.video,
            enable_survey=args.survey,
            survey_questions=questions,
            survey_timeout=args.timeout,
            campaign_mode=args.campaign
        ))
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️ Process interrupted by user. Exiting safely...{Style.RESET_ALL}")

if __name__ == "__main__":
    main()

