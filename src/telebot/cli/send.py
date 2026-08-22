import os
import sys
import json
import asyncio
import argparse
import pandas as pd
from datetime import datetime
from tabulate import tabulate
from colorama import init, Fore, Style

from src.telebot.config import config
from src.telebot.utils.phone import load_phone_numbers
from src.telebot.core.service import TelegramService

init(autoreset=True)

DEFAULT_MESSAGE = "Hello! This is an official follow-up message regarding our services. Please let us know if you have any questions or need assistance."

async def run_auto_send(
    phone_file: str = "phone-list.txt",
    message_template: str = DEFAULT_MESSAGE,
    default_country: str = "KH",
    delay_seconds: int = 2
):
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗")
    print(f"{Fore.CYAN}║     🚀 TELEGRAM DIRECT OUTREACH (PHONE TO PHONE SENDER)          ║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}\n")

    if not os.path.exists(phone_file):
        print(f"{Fore.RED}❌ Error: File '{phone_file}' not found.")
        return

    numbers = load_phone_numbers(phone_file, default_region=default_country)
    total_count = len(numbers)
    print(f"📁 Target Numbers File : {Fore.YELLOW}{phone_file}{Style.RESET_ALL} ({total_count} numbers loaded)")
    print(f"⏱️ Safety Delay        : {Fore.YELLOW}{delay_seconds}s{Style.RESET_ALL} between messages")
    print(f"💬 Message Content     :\n{Fore.LIGHTBLACK_EX}--- Message Start ---\n{message_template}\n--- Message End ---{Style.RESET_ALL}\n")

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

    results = []
    table_rows = []
    stats = {
        "total": total_count,
        "registered": 0,
        "unregistered": 0,
        "delivered": 0,
        "privacy_blocked": 0,
        "failed": 0
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
                disp_name = full_n if (full_n and full_n != "TempCheck") else "-"

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
                        "details": "Account deleted by user"
                    })
                    await service.delete_contact(info["id"])
                elif user_entity:
                    final_msg = service.format_message_template(message_template, user_info=info)
                    print(f"       Sending message from phone... ", end="", flush=True)
                    success, status_type, status_info = await service.send_message_to_user(user_entity, final_msg)

                    if success:
                        stats["delivered"] += 1
                        print(f"{Fore.GREEN}[SENT SUCCESS] (Msg ID: {status_info}){Style.RESET_ALL}")
                        table_rows.append([index, e164, "Registered", disp_name, uname, "Delivered", f"Msg ID: {status_info}"])
                        results.append({
                            "index": index,
                            "raw_phone": raw,
                            "normalized_e164": e164,
                            "registration": "Registered",
                            "recipient": disp_name,
                            "delivery_status": "Delivered",
                            "details": f"Msg ID: {status_info}"
                        })
                    elif status_type == "PRIVACY_RESTRICTED":
                        stats["privacy_blocked"] += 1
                        print(f"{Fore.YELLOW}[PRIVACY RESTRICTED]{Style.RESET_ALL}")
                        table_rows.append([index, e164, "Registered", disp_name, uname, "Privacy Restricted", "Blocked: User privacy settings"])
                        results.append({
                            "index": index,
                            "raw_phone": raw,
                            "normalized_e164": e164,
                            "registration": "Registered",
                            "recipient": disp_name,
                            "delivery_status": "Privacy Restricted",
                            "details": "Blocked: User privacy settings"
                        })
                    else:
                        stats["failed"] += 1
                        print(f"{Fore.RED}[FAILED: {status_info}]{Style.RESET_ALL}")
                        table_rows.append([index, e164, "Registered", disp_name, uname, "Failed", status_info])
                        results.append({
                            "index": index,
                            "raw_phone": raw,
                            "normalized_e164": e164,
                            "registration": "Registered",
                            "recipient": disp_name,
                            "delivery_status": "Failed",
                            "details": status_info
                        })

                    await service.delete_contact(info["id"])

                    if index < total_count and delay_seconds > 0:
                        print(f"       Delay: waiting {Fore.MAGENTA}{delay_seconds}s{Style.RESET_ALL} before next number...\n")
                        await asyncio.sleep(delay_seconds)

            else:
                stats["unregistered"] += 1
                print(f"{Fore.YELLOW}[UNREGISTERED / HIDDEN - SKIPPED]{Style.RESET_ALL}")
                table_rows.append([index, e164, "Unregistered", "-", "-", "Skipped", "Number not registered on Telegram"])
                results.append({
                    "index": index,
                    "raw_phone": raw,
                    "normalized_e164": e164,
                    "registration": "Unregistered",
                    "recipient": "-",
                    "delivery_status": "Skipped",
                    "details": "Number not registered on Telegram"
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
                "details": str(e)
            })

    elapsed = (datetime.now() - start_time).total_seconds()

    print("\n" + tabulate(
        table_rows,
        headers=["#", "Phone (E.164)", "Registration", "Name", "Username", "Delivery Status", "Details"],
        tablefmt="grid"
    ))

    print(f"\n{Fore.GREEN}══════════════════════════════════════════════════════════════════")
    print(f"📊 EXECUTION SUMMARY REPORT")
    print(f"══════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"• Total Numbers Checked : {Fore.YELLOW}{stats['total']}{Style.RESET_ALL}")
    print(f"• Registered Accounts   : {Fore.GREEN}{stats['registered']}{Style.RESET_ALL}")
    print(f"• Messages Delivered    : {Fore.GREEN}{stats['delivered']}{Style.RESET_ALL}")
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
        df.to_csv(config.results_csv, index=False, encoding="utf-8-sig")
        print(f"CSV Spreadsheet saved to: {Fore.CYAN}{config.results_csv}{Style.RESET_ALL}")
    except Exception as e:
        print(f"Notice: CSV export note: {e}")

    await service.disconnect()

def main():
    parser = argparse.ArgumentParser(description="Telegram Phone-to-Phone Auto-Sender")
    parser.add_argument("file", nargs="?", default="phone-list.txt", help="Path to phone numbers text file")
    parser.add_argument("--msg", default=DEFAULT_MESSAGE, help="Custom message text")
    parser.add_argument("--country", default=config.default_country, help="Default ISO country code (e.g. KH)")
    parser.add_argument("--delay", type=int, default=2, help="Delay in seconds between messages (default: 2)")
    
    args = parser.parse_args()

    try:
        asyncio.run(run_auto_send(
            phone_file=args.file,
            message_template=args.msg,
            default_country=args.country,
            delay_seconds=args.delay
        ))
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️ Process interrupted by user. Exiting safely...{Style.RESET_ALL}")

if __name__ == "__main__":
    main()
