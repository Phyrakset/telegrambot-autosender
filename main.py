"""
TeleSender Pro - Monolithic Application Entry Point
"""
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(
        description="TeleSender Pro - Telegram Lead Outreach & Verification Suite",
        epilog="Examples:\n  python main.py --ui\n  python main.py check phone-list.txt\n  python main.py send phone-list.txt --delay 2",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available Commands")

    # Command: ui
    parser_ui = subparsers.add_parser("ui", help="Launch the Interactive Web Dashboard")
    
    # Command: check
    parser_check = subparsers.add_parser("check", help="Verify phone registration only (CLI)")
    parser_check.add_argument("file", nargs="?", default="phone-list.txt", help="Phone list path")
    parser_check.add_argument("--country", default="KH", help="Default country ISO")

    # Command: send
    parser_send = subparsers.add_parser("send", help="Auto-send TverKar video message & conduct interactive survey (CLI)")
    parser_send.add_argument("file", nargs="?", default="phone-list.txt", help="Phone list path")
    parser_send.add_argument("--msg", default=None, help="Message caption (default: TverKar Khmer message)")
    parser_send.add_argument("--delay", type=int, default=2, help="Delay in seconds between messages")
    parser_send.add_argument("--country", default="KH", help="Default country ISO")
    parser_send.add_argument("--video", default="video/TverKar&WN_using.mp4", help="Path to video file")
    parser_send.add_argument("--timeout", type=int, default=180, help="Survey response timeout in seconds")

    # Top-level --ui flag for shortcut
    parser.add_argument("--ui", action="store_true", help="Launch Web UI directly")

    args = parser.parse_args()

    if args.ui or args.command == "ui" or args.command is None:
        from src.telebot.ui.app import main as ui_main
        ui_main()
    elif args.command == "check":
        import asyncio
        from src.telebot.cli.check import run_check
        asyncio.run(run_check(args.file, args.country))
    elif args.command == "send":
        import asyncio
        from src.telebot.cli.send import run_auto_send
        asyncio.run(run_auto_send(
            phone_file=args.file,
            message_template=args.msg,
            default_country=args.country,
            delay_seconds=args.delay,
            video_path=args.video,
            survey_timeout=args.timeout,
            campaign_mode="tverkar"
        ))


if __name__ == "__main__":
    main()
