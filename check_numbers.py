import os
import sys
import json
import asyncio
from tabulate import tabulate
from colorama import init, Fore, Style

from utils import load_phone_numbers
from telegram_service import TelegramService

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
                print(f"{Fore.GREEN}[REGISTERED]{Style.RESET_ALL} - {info['first_name']} (@{info['username'] or 'None'})")
                table_rows.append([
                    e164, 
                    "YES", 
                    info["id"], 
                    info["first_name"], 
                    f"@{info['username']}" if info['username'] else "-", 
                    info["status"]
                ])
                results.append({"phone": e164, "raw": raw, "registered": True, "user_info": info})
            else:
                print(f"{Fore.YELLOW}[NOT REGISTERED / HIDDEN]{Style.RESET_ALL}")
                table_rows.append([e164, "NO", "-", "-", "-", "-"])
                results.append({"phone": e164, "raw": raw, "registered": False, "user_info": None})
        except Exception as e:
            print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {e}")
            table_rows.append([e164, "ERROR", "-", "-", "-", str(e)])
            results.append({"phone": e164, "raw": raw, "registered": False, "error": str(e)})

        # Small 1-2s delay between checks to keep API pace steady
        await asyncio.sleep(1.5)

    print("\n" + tabulate(
        table_rows, 
        headers=["Phone Number", "Registered?", "Telegram ID", "First Name", "Username", "Status"], 
        tablefmt="grid"
    ))

    # Save results to JSON
    output_json = "check_results.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n{Fore.GREEN}Results exported to '{output_json}'.")

    await service.disconnect()

if __name__ == "__main__":
    file_arg = sys.argv[1] if len(sys.argv) > 1 else "phone-list.txt"
    country_arg = os.getenv("DEFAULT_COUNTRY", "KH")
    asyncio.run(run_check(file_arg, country_arg))
