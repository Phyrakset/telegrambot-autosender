import os
import sys
import json
import asyncio
import argparse
from tabulate import tabulate
from colorama import init, Fore, Style

from src.telebot.config import config
from src.telebot.utils.phone import load_phone_numbers
from src.telebot.core.service import TelegramService

init(autoreset=True)

async def run_check(phone_file: str = "phone-list.txt", default_country: str = "KH"):
    print(f"{Fore.CYAN}==================================================")
    print(f"{Fore.CYAN}  TELEGRAM PHONE NUMBER REGISTRATION CHECKER")
    print(f"{Fore.CYAN}==================================================\n")

    if not os.path.exists(phone_file):
        print(f"{Fore.RED}Error: File '{phone_file}' not found.")
        return

    numbers = load_phone_numbers(phone_file, default_region=default_country)
    print(f"Loaded {Fore.YELLOW}{len(numbers)}{Style.RESET_ALL} phone numbers from '{phone_file}'.\n")

    service = TelegramService()
    try:
        await service.connect()
    except Exception as e:
        print(f"{Fore.RED}Failed to connect to Telegram: {e}")
        return

    results = []
    table_rows = []

    for item in numbers:
        raw = item["raw"]
        e164 = item["e164"]
        print(f"Checking {Fore.BLUE}{e164}{Style.RESET_ALL} (raw: {raw})... ", end="", flush=True)

        try:
            is_reg, info, _ = await service.check_phone_registration(e164)
            if is_reg and info:
                first_n = info.get('first_name', '')
                last_n = info.get('last_name', '')
                full_n = f"{first_n} {last_n}".strip()
                uname = f"@{info['username']}" if info.get('username') else "-"
                disp_name = full_n if (full_n and full_n != "TempCheck") else "-"

                print(f"{Fore.GREEN}[REGISTERED]{Style.RESET_ALL} - {disp_name} ({uname})")
                table_rows.append([
                    e164, 
                    "Registered", 
                    info["id"], 
                    disp_name, 
                    uname, 
                    info.get("status", "-")
                ])
                results.append({"phone": e164, "raw": raw, "registered": True, "user_info": info})
            else:
                print(f"{Fore.YELLOW}[UNREGISTERED / HIDDEN]{Style.RESET_ALL}")
                table_rows.append([e164, "Unregistered", "-", "-", "-", "-"])
                results.append({"phone": e164, "raw": raw, "registered": False, "user_info": None})
        except Exception as e:
            print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {e}")
            table_rows.append([e164, "Error", "-", "-", "-", str(e)])
            results.append({"phone": e164, "raw": raw, "registered": False, "error": str(e)})

        await asyncio.sleep(0.5)

    print("\n" + tabulate(
        table_rows, 
        headers=["Phone Number", "Registered?", "Telegram ID", "First Name", "Username", "Status"], 
        tablefmt="grid"
    ))

    output_json = "check_results.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n{Fore.GREEN}Results exported to '{output_json}'.")

    await service.disconnect()

def main():
    parser = argparse.ArgumentParser(description="Check Telegram Phone Registration")
    parser.add_argument("file", nargs="?", default="phone-list.txt", help="Path to phone numbers file")
    parser.add_argument("--country", default=config.default_country, help="Default ISO country code")
    args = parser.parse_args()
    asyncio.run(run_check(args.file, args.country))

if __name__ == "__main__":
    main()
