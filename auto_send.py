import os
import sys
import json
import random
import asyncio
from tabulate import tabulate
from colorama import init, Fore, Style
from dotenv import load_dotenv

from utils import load_phone_numbers
from telegram_service import TelegramService

init(autoreset=True)
load_dotenv()

DEFAULT_MESSAGE = "Hello! This is an automated notification."

async def run_auto_send(
    phone_file: str = "phone-list.txt",
    message_text: str = DEFAULT_MESSAGE,
    default_country: str = "KH"
):
    min_delay = int(os.getenv("MIN_DELAY_SECONDS", "15"))
    max_delay = int(os.getenv("MAX_DELAY_SECONDS", "35"))

    print(f"{Fore.CYAN}==================================================")
    print(f"{Fore.CYAN}  TELEGRAM AUTO-SEND TO REGISTERED PHONES")
    print(f"{Fore.CYAN}==================================================")
    print(f"Message content: '{Fore.YELLOW}{message_text}{Style.RESET_ALL}'")
    print(f"Safety Delay Range: {min_delay}s - {max_delay}s between dispatches\n")

    if not os.path.exists(phone_file):
        print(f"{Fore.RED}Error: File '{phone_file}' not found.")
        return

    numbers = load_phone_numbers(phone_file, default_region=default_country)
    print(f"Loaded {Fore.YELLOW}{len(numbers)}{Style.RESET_ALL} numbers from '{phone_file}'.\n")

    service = TelegramService()
    try:
        await service.connect()
    except Exception as e:
        print(f"{Fore.RED}Failed to connect: {e}")
        return

    results = []
    table_rows = []

    for index, item in enumerate(numbers, 1):
        raw = item["raw"]
        e164 = item["e164"]

        print(f"[{index}/{len(numbers)}] Checking {Fore.BLUE}{e164}{Style.RESET_ALL} (raw: {raw})... ", end="", flush=True)

        try:
            # We don't immediately delete contact before sending because we need the entity reference
            is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
            
            if is_reg and user_entity:
                print(f"{Fore.GREEN}[REGISTERED]{Style.RESET_ALL} -> {info['first_name']} (@{info['username'] or 'None'})")
                print(f"    Sending message... ", end="", flush=True)

                success, status_info = await service.send_message_to_user(user_entity, message_text)
                
                if success:
                    print(f"{Fore.GREEN}[SENT SUCCESS] (Msg ID: {status_info}){Style.RESET_ALL}")
                    table_rows.append([e164, "REGISTERED", info["first_name"], f"@{info['username']}", "SENT", status_info])
                    results.append({"phone": e164, "status": "SENT", "msg_id": status_info, "user": info})
                else:
                    print(f"{Fore.RED}[SEND FAILED: {status_info}]{Style.RESET_ALL}")
                    table_rows.append([e164, "REGISTERED", info["first_name"], f"@{info['username']}", "FAILED", status_info])
                    results.append({"phone": e164, "status": "FAILED", "error": status_info, "user": info})

                # Cleanup contact after sending
                try:
                    await service.client(service.client.build_delete_contacts_request([user_entity.id]))
                except Exception:
                    pass

                # Apply anti-spam jitter delay if there are more numbers to process
                if index < len(numbers):
                    delay = random.randint(min_delay, max_delay)
                    print(f"    {Fore.MAGENTA}Sleeping {delay}s for anti-flood protection...{Style.RESET_ALL}")
                    await asyncio.sleep(delay)

            else:
                print(f"{Fore.YELLOW}[NOT REGISTERED / HIDDEN - SKIPPED]{Style.RESET_ALL}")
                table_rows.append([e164, "NOT_REGISTERED", "-", "-", "SKIPPED", "-"])
                results.append({"phone": e164, "status": "NOT_REGISTERED"})

        except Exception as e:
            print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
            table_rows.append([e164, "ERROR", "-", "-", "ERROR", str(e)])
            results.append({"phone": e164, "status": "ERROR", "error": str(e)})

    print("\n" + tabulate(
        table_rows,
        headers=["Phone Number", "Registration", "Name", "Username", "Delivery", "Details"],
        tablefmt="grid"
    ))

    # Save log
    output_log = "auto_send_results.json"
    with open(output_log, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n{Fore.GREEN}Delivery report exported to '{output_log}'.")

    await service.disconnect()

if __name__ == "__main__":
    file_arg = sys.argv[1] if len(sys.argv) > 1 else "phone-list.txt"
    custom_msg = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MESSAGE
    country_arg = os.getenv("DEFAULT_COUNTRY", "KH")
    asyncio.run(run_auto_send(file_arg, custom_msg, country_arg))
