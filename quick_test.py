import os
import sys
import asyncio
from colorama import init, Fore, Style
from dotenv import load_dotenv

from utils import format_phone_e164
from telegram_service import TelegramService

init(autoreset=True)
load_dotenv()

async def test_single_number(phone_input: str, message: str = "Test message from Telegram Auto-Send"):
    default_country = os.getenv("DEFAULT_COUNTRY", "KH")
    e164 = format_phone_e164(phone_input, default_country)
    
    print(f"\n{Fore.CYAN}--- Single Phone Test ---{Style.RESET_ALL}")
    print(f"Input: {phone_input} -> Normalized E.164: {Fore.YELLOW}{e164}{Style.RESET_ALL}")

    service = TelegramService()
    try:
        await service.connect()
    except Exception as e:
        print(f"{Fore.RED}Login/Connection error: {e}")
        return

    print(f"Checking registration status for {e164}...")
    is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)

    if not is_reg or not user_entity:
        print(f"{Fore.YELLOW}Result: Phone {e164} is NOT registered on Telegram or is hidden by privacy settings.{Style.RESET_ALL}")
        await service.disconnect()
        return

    print(f"{Fore.GREEN}Result: User is REGISTERED!{Style.RESET_ALL}")
    print(f"  - Telegram User ID: {info['id']}")
    print(f"  - Name: {info['first_name']} {info['last_name']}")
    print(f"  - Username: @{info['username'] or 'None'}")
    print(f"  - Status: {info['status']}")

    confirm = input(f"\nDo you want to send test message '{message}' to this user? (y/n): ").strip().lower()
    if confirm == "y":
        print("Sending message...")
        success, details = await service.send_message_to_user(user_entity, message)
        if success:
            print(f"{Fore.GREEN}Message sent successfully! (ID: {details}){Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}Message send failed: {details}{Style.RESET_ALL}")
    else:
        print("Skipped sending message.")

    await service.disconnect()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python quick_test.py <phone_number> [optional_message]")
        print("Example: python quick_test.py 0968271451 \"Hello world\"")
        sys.exit(1)
    
    target_phone = sys.argv[1]
    msg = sys.argv[2] if len(sys.argv) > 2 else "Test message from Telegram Auto-Send"
    asyncio.run(test_single_number(target_phone, msg))
