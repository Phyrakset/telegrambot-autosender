import os
import sys
import json
import random
import asyncio
import argparse
import pandas as pd
from datetime import datetime
from tabulate import tabulate
from colorama import init, Fore, Style
from dotenv import load_dotenv

from utils import load_phone_numbers, format_phone_e164
from telegram_service import TelegramService

init(autoreset=True)
load_dotenv()

DEFAULT_MESSAGE = "Hello! 👋 Thank you for connecting with us.\nTo get immediate support and start chatting with our official assistant, please tap the link below:\n👉 {bot_link}"

async def run_auto_send(
    phone_file: str = "phone-list.txt",
    message_template: str = DEFAULT_MESSAGE,
    bot_link: str = "",
    default_country: str = "KH",
    min_delay: int = 15,
    max_delay: int = 35
):
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗")
    print(f"{Fore.CYAN}║     🚀 TELEGRAM AUTO-MESSENGER FOR REGISTERED PHONES             ║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}\n")

    if not os.path.exists(phone_file):
        print(f"{Fore.RED}❌ Error: File '{phone_file}' not found.")
        return

    numbers = load_phone_numbers(phone_file, default_region=default_country)
    total_count = len(numbers)
    print(f"📁 Target File: {Fore.YELLOW}{phone_file}{Style.RESET_ALL} ({total_count} phone numbers loaded)")
    print(f"⏱️ Safety Jitter Delay: {Fore.YELLOW}{min_delay}s - {max_delay}s{Style.RESET_ALL} between messages")
    if bot_link:
        print(f"🤖 Bot Redirect Link: {Fore.CYAN}{bot_link}{Style.RESET_ALL}")
    print(f"💬 Message Template:\n{Fore.LIGHTBLACK_EX}--- Start Message ---\n{message_template}\n--- End Message ---{Style.RESET_ALL}\n")

    service = TelegramService()
    try:
        await service.connect()
        if not await service.is_authenticated():
            print(f"{Fore.RED}❌ Error: Telegram session is not authorized. Please run 'python app.py' to log in first.{Style.RESET_ALL}")
            return
        me = await service.get_me_info()
        print(f"👤 Sender Account: {Fore.GREEN}{me['first_name']} {me['last_name']} (@{me['username'] or 'NoUsername'}){Style.RESET_ALL} | ID: {me['id']}\n")
    except Exception as e:
        print(f"{Fore.RED}❌ Connection error: {e}{Style.RESET_ALL}")
        return

    results = []
    table_rows = []
    stats = {
        "total": total_count,
        "registered": 0,
        "not_registered": 0,
        "sent": 0,
        "failed": 0,
        "error": 0
    }

    start_time = datetime.now()

    for index, item in enumerate(numbers, 1):
        raw = item["raw"]
        e164 = item["e164"]

        print(f"[{index:02d}/{total_count:02d}] 🔍 Checking {Fore.BLUE}{e164}{Style.RESET_ALL} (raw: {raw})... ", end="", flush=True)

        try:
            # Check registration without deleting immediately so we retain target entity
            is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
            
            if is_reg and user_entity:
                stats["registered"] += 1
                name = f"{info['first_name']} {info['last_name']}".strip()
                username = f"@{info['username']}" if info['username'] else "-"
                print(f"{Fore.GREEN}[REGISTERED]{Style.RESET_ALL} -> {name} ({username})")

                # Format personalized message
                final_msg = service.format_message_template(message_template, user_info=info, bot_link=bot_link)
                
                print(f"       ✉️ Dispatching message... ", end="", flush=True)
                success, status_info = await service.send_message_to_user(user_entity, final_msg)

                if success:
                    stats["sent"] += 1
                    print(f"{Fore.GREEN}[SENT SUCCESS] (Msg ID: {status_info}){Style.RESET_ALL}")
                    table_rows.append([index, e164, "✅ REGISTERED", name, username, "✅ SENT", f"Msg #{status_info}"])
                    results.append({
                        "index": index,
                        "raw_phone": raw,
                        "normalized_e164": e164,
                        "registered": True,
                        "telegram_id": info["id"],
                        "name": name,
                        "username": info["username"],
                        "delivery_status": "SENT",
                        "details": f"Msg ID: {status_info}",
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    stats["failed"] += 1
                    print(f"{Fore.RED}[SEND FAILED: {status_info}]{Style.RESET_ALL}")
                    table_rows.append([index, e164, "✅ REGISTERED", name, username, "❌ FAILED", status_info])
                    results.append({
                        "index": index,
                        "raw_phone": raw,
                        "normalized_e164": e164,
                        "registered": True,
                        "telegram_id": info["id"],
                        "name": name,
                        "username": info["username"],
                        "delivery_status": "FAILED",
                        "details": status_info,
                        "timestamp": datetime.now().isoformat()
                    })

                # Clean up temporary contact
                await service.delete_contact(info["id"])

                # Anti-spam delay between sends
                if index < total_count:
                    delay = random.randint(min_delay, max_delay)
                    print(f"       ⏳ Anti-flood delay: sleeping for {Fore.MAGENTA}{delay}s{Style.RESET_ALL}...\n")
                    await asyncio.sleep(delay)

            else:
                stats["not_registered"] += 1
                print(f"{Fore.YELLOW}[NOT REGISTERED / HIDDEN - SKIPPED]{Style.RESET_ALL}")
                table_rows.append([index, e164, "❌ NO", "-", "-", "⏭️ SKIPPED", "Not found or privacy restricted"])
                results.append({
                    "index": index,
                    "raw_phone": raw,
                    "normalized_e164": e164,
                    "registered": False,
                    "telegram_id": "",
                    "name": "",
                    "username": "",
                    "delivery_status": "SKIPPED",
                    "details": "Not found / privacy restricted",
                    "timestamp": datetime.now().isoformat()
                })
                # Small 1s pacing pause for non-registered
                if index < total_count:
                    await asyncio.sleep(1.0)

        except Exception as e:
            stats["error"] += 1
            print(f"{Fore.RED}[ERROR: {e}]{Style.RESET_ALL}")
            table_rows.append([index, e164, "⚠️ ERROR", "-", "-", "⚠️ ERROR", str(e)])
            results.append({
                "index": index,
                "raw_phone": raw,
                "normalized_e164": e164,
                "registered": False,
                "telegram_id": "",
                "name": "",
                "username": "",
                "delivery_status": "ERROR",
                "details": str(e),
                "timestamp": datetime.now().isoformat()
            })

    elapsed = (datetime.now() - start_time).total_seconds()

    # Display clean summary table
    print("\n" + tabulate(
        table_rows,
        headers=["#", "Phone (E.164)", "Registered?", "Name", "Username", "Delivery", "Details"],
        tablefmt="grid"
    ))

    # Print summary metrics box
    print(f"\n{Fore.GREEN}══════════════════════════════════════════════════════════════════")
    print(f"📊 EXECUTION SUMMARY REPORT")
    print(f"══════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"• Total Numbers Checked : {Fore.YELLOW}{stats['total']}{Style.RESET_ALL}")
    print(f"• Registered Accounts   : {Fore.GREEN}{stats['registered']}{Style.RESET_ALL} ({(stats['registered']/stats['total']*100 if stats['total'] else 0):.1f}%)")
    print(f"• Messages Sent         : {Fore.GREEN}{stats['sent']}{Style.RESET_ALL}")
    print(f"• Messages Failed       : {Fore.RED}{stats['failed']}{Style.RESET_ALL}")
    print(f"• Skipped / Unregistered: {Fore.YELLOW}{stats['not_registered']}{Style.RESET_ALL}")
    print(f"• Errors Encountered    : {Fore.RED}{stats['error']}{Style.RESET_ALL}")
    print(f"• Total Elapsed Time    : {Fore.CYAN}{elapsed:.1f} seconds{Style.RESET_ALL}")
    print(f"{Fore.GREEN}══════════════════════════════════════════════════════════════════{Style.RESET_ALL}\n")

    # Export to JSON and CSV
    output_json = "auto_send_results.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"💾 JSON Log saved to: {Fore.CYAN}{output_json}{Style.RESET_ALL}")

    try:
        output_csv = "auto_send_results.csv"
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"📊 CSV Spreadsheet saved to: {Fore.CYAN}{output_csv}{Style.RESET_ALL}")
    except Exception as e:
        print(f"Notice: CSV export note: {e}")

    await service.disconnect()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Auto-Sender to Registered Phone Numbers")
    parser.add_argument("file", nargs="?", default="phone-list.txt", help="Path to phone numbers text file")
    parser.add_argument("--msg", default=DEFAULT_MESSAGE, help="Custom message text")
    parser.add_argument("--bot-link", default="", help="Telegram Bot link (e.g. https://t.me/MyCompanyBot)")
    parser.add_argument("--country", default=os.getenv("DEFAULT_COUNTRY", "KH"), help="Default ISO country code (e.g. KH)")
    parser.add_argument("--min-delay", type=int, default=int(os.getenv("MIN_DELAY_SECONDS", "15")), help="Min delay seconds")
    parser.add_argument("--max-delay", type=int, default=int(os.getenv("MAX_DELAY_SECONDS", "35")), help="Max delay seconds")
    
    args = parser.parse_args()

    try:
        asyncio.run(run_auto_send(
            phone_file=args.file,
            message_template=args.msg,
            bot_link=args.bot_link,
            default_country=args.country,
            min_delay=args.min_delay,
            max_delay=args.max_delay
        ))
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️ Process interrupted by user. Exiting safely...{Style.RESET_ALL}")
