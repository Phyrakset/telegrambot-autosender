import os
import sys
import json
import socket
import random
import asyncio
import pandas as pd
from datetime import datetime
import gradio as gr
from dotenv import load_dotenv

from utils import format_phone_e164, load_phone_numbers
from telegram_service import TelegramService

load_dotenv()

service = TelegramService()
STOP_REQUESTED = False

DEFAULT_BOT_MESSAGE = (
    "Hello! 👋 Thank you for reaching out to us.\n"
    "To get fast assistance and start chatting with our official automated service, please tap the link below:\n"
    "👉 {bot_link}"
)

CUSTOM_CSS = """
.gradio-container { max-width: 1200px !important; margin: auto; }
.header-banner { background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); color: white; padding: 22px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.header-title { font-size: 26px; font-weight: 800; margin: 0; }
.header-sub { font-size: 14px; opacity: 0.9; margin-top: 6px; }
.kpi-container { margin-bottom: 15px; }
.preview-box { background: #0f172a; color: #38bdf8; border: 1px solid #334155; border-radius: 8px; padding: 12px; }
"""

def find_available_port(start_port: int = 7860, max_port: int = 7890) -> int:
    """Finds the first available port in the given range."""
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0  # 0 lets OS allocate any random free port

def get_20_sample_numbers():
    if os.path.exists("phone-list.txt"):
        with open("phone-list.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    return (
        "0968271451\n0183910978\n09342252\n087225303\n012345678\n"
        "010889922\n0977123456\n0885544332\n070998877\n092112233\n"
        "016554433\n098776655\n089223344\n060123456\n0719876543\n"
        "011223344\n095887766\n086445566\n069334455\n077123987"
    )

def render_kpi_cards(total, registered, sent, skipped, failed, is_running=False):
    reg_pct = (registered / total * 100) if total > 0 else 0
    return f"""
    <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:12px;margin-bottom:15px;">
        <div style="background:#1e293b;color:#f8fafc;padding:14px;border-radius:10px;border-left:4px solid #3b82f6;box-shadow:0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:600;">Total Numbers</div>
            <div style="font-size:24px;font-weight:700;margin-top:4px;">{total}</div>
        </div>
        <div style="background:#1e293b;color:#f8fafc;padding:14px;border-radius:10px;border-left:4px solid #10b981;box-shadow:0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:600;">Registered ({reg_pct:.0f}%)</div>
            <div style="font-size:24px;font-weight:700;color:#34d399;margin-top:4px;">{registered}</div>
        </div>
        <div style="background:#1e293b;color:#f8fafc;padding:14px;border-radius:10px;border-left:4px solid #8b5cf6;box-shadow:0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:600;">Messages Sent</div>
            <div style="font-size:24px;font-weight:700;color:#a78bfa;margin-top:4px;">{sent}</div>
        </div>
        <div style="background:#1e293b;color:#f8fafc;padding:14px;border-radius:10px;border-left:4px solid #eab308;box-shadow:0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:600;">Unregistered / Skipped</div>
            <div style="font-size:24px;font-weight:700;color:#facc15;margin-top:4px;">{skipped}</div>
        </div>
        <div style="background:#1e293b;color:#f8fafc;padding:14px;border-radius:10px;border-left:4px solid #ef4444;box-shadow:0 2px 4px rgba(0,0,0,0.1);">
            <div style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:600;">Errors / Failed</div>
            <div style="font-size:24px;font-weight:700;color:#f87171;margin-top:4px;">{failed}</div>
        </div>
    </div>
    """

async def check_auth_status():
    """Checks and returns the current authentication status badge."""
    try:
        if await service.is_authenticated():
            me = await service.get_me_info()
            if me:
                name = f"{me['first_name']} {me['last_name']}".strip()
                username = f"@{me['username']}" if me['username'] else "No Username"
                return (
                    f"### 🟢 **Telegram Connected & Ready**\n"
                    f"- **Sender Profile**: **{name}** ({username})\n"
                    f"- **Account ID**: `{me['id']}` | **Phone**: `{me['phone']}`"
                )
        return "### 🔴 **Not Authenticated** — Please log in using the *Telegram Account & Credentials* tab."
    except Exception as e:
        return f"### ⚠️ **Connection Notice**: {str(e)}"

async def save_credentials_and_send_code(api_id, api_hash, phone):
    """Saves credentials to .env and triggers login verification code."""
    if not api_id or not api_hash or not phone:
        return "❌ Please enter API ID, API Hash, and Phone Number.", gr.update()
    
    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"TELEGRAM_API_ID={str(api_id).strip()}\n")
        f.write(f"TELEGRAM_API_HASH={str(api_hash).strip()}\n")
        f.write(f"TELEGRAM_PHONE={str(phone).strip()}\n")
        f.write("DEFAULT_COUNTRY=KH\nMIN_DELAY_SECONDS=15\nMAX_DELAY_SECONDS=35\n")
    
    service.reload_env()
    service.client = None

    ok, msg = await service.send_auth_code(phone)
    if ok:
        status_msg = f"✅ {msg}"
    else:
        status_msg = f"❌ {msg}"
    
    auth_badge = await check_auth_status()
    return status_msg, auth_badge

async def verify_code(code, password):
    """Verifies the SMS/Telegram code and optional 2FA password."""
    if not code:
        return "❌ Please enter the code sent to your Telegram app.", gr.update()

    ok, msg, needs_pwd = await service.sign_in_with_code(code, password)
    auth_badge = await check_auth_status()
    if ok:
        return f"✅ {msg}", auth_badge
    elif needs_pwd:
        return f"⚠️ {msg}", auth_badge
    else:
        return f"❌ {msg}", auth_badge

def trigger_stop():
    global STOP_REQUESTED
    STOP_REQUESTED = True
    return "🛑 Stop signal sent. Completing current step then halting..."

def update_preview(msg_template, bot_url):
    formatted = service.format_message_template(msg_template, {"first_name": "Sophea", "username": "sophea_test"}, bot_url)
    return f"```text\n{formatted}\n```"

# Real-Time Streaming Processor for Batch Operations
async def process_batch_streaming(
    phone_text, 
    country_code, 
    auto_send, 
    message_text, 
    bot_link, 
    min_delay, 
    max_delay, 
    progress=gr.Progress()
):
    global STOP_REQUESTED
    STOP_REQUESTED = False

    if not phone_text:
        yield pd.DataFrame(), "❌ Phone list is empty.", render_kpi_cards(0, 0, 0, 0, 0), None
        return

    lines = [line.strip() for line in phone_text.splitlines() if line.strip() and not line.startswith("#")]
    total = len(lines)
    if total == 0:
        yield pd.DataFrame(), "❌ No valid phone numbers found.", render_kpi_cards(0, 0, 0, 0, 0), None
        return

    # Check connection
    try:
        await service.connect()
        if not await service.is_authenticated():
            yield pd.DataFrame(), "❌ Telegram session not authorized. Please log in on Tab 3 first.", render_kpi_cards(0, 0, 0, 0, 0), None
            return
    except Exception as e:
        yield pd.DataFrame(), f"❌ Connection Error: {str(e)}", render_kpi_cards(0, 0, 0, 0, 0), None
        return

    results = []
    stats = {"total": total, "registered": 0, "sent": 0, "skipped": 0, "failed": 0}
    progress(0, desc=f"Initializing test batch of {total} numbers...")

    # Initial empty dataframe render
    initial_rows = []
    for idx, raw_phone in enumerate(lines, 1):
        e164 = format_phone_e164(raw_phone, default_region=country_code)
        initial_rows.append({
            "#": idx,
            "Raw Input": raw_phone,
            "Normalized (E.164)": e164,
            "Registered": "⏳ Queued",
            "Name": "-",
            "Username": "-",
            "Delivery Status": "Pending" if auto_send else "Queued",
            "Details": ""
        })
    
    df = pd.DataFrame(initial_rows)
    yield df, f"⚡ Starting batch processing ({total} numbers)...", render_kpi_cards(total, 0, 0, 0, 0, is_running=True), None

    for i, raw_phone in enumerate(lines):
        if STOP_REQUESTED:
            yield df, f"🛑 **Processing Halted by User** at item {i}/{total}.", render_kpi_cards(total, stats['registered'], stats['sent'], stats['skipped'], stats['failed'], is_running=False), "auto_send_results.csv"
            return

        e164 = format_phone_e164(raw_phone, default_region=country_code)
        df.at[i, "Registered"] = "🔍 Checking..."
        df.at[i, "Details"] = "Querying Telegram MTProto..."
        yield df, f"Processing [{i+1}/{total}]: {e164}...", render_kpi_cards(total, stats['registered'], stats['sent'], stats['skipped'], stats['failed'], is_running=True), None

        try:
            is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
            if is_reg and info:
                stats["registered"] += 1
                name = f"{info['first_name']} {info['last_name']}".strip()
                username = f"@{info['username']}" if info['username'] else "-"
                
                df.at[i, "Registered"] = "✅ YES"
                df.at[i, "Name"] = name
                df.at[i, "Username"] = username

                if auto_send and user_entity:
                    df.at[i, "Delivery Status"] = "🚀 Sending..."
                    yield df, f"Dispatching message to {name}...", render_kpi_cards(total, stats['registered'], stats['sent'], stats['skipped'], stats['failed'], is_running=True), None
                    
                    final_msg = service.format_message_template(message_text, user_info=info, bot_link=bot_link)
                    success, send_info = await service.send_message_to_user(user_entity, final_msg)

                    if success:
                        stats["sent"] += 1
                        df.at[i, "Delivery Status"] = "✅ SENT"
                        df.at[i, "Details"] = f"Msg ID: {send_info}"
                    else:
                        stats["failed"] += 1
                        df.at[i, "Delivery Status"] = "❌ FAILED"
                        df.at[i, "Details"] = str(send_info)

                    # Delete contact after send
                    await service.delete_contact(info["id"])

                    # Anti-spam delay
                    if i < total - 1:
                        sleep_time = random.randint(int(min_delay), int(max_delay))
                        df.at[i, "Details"] = f"Sent (Waiting {sleep_time}s anti-flood delay)"
                        yield df, f"Sleeping {sleep_time}s to protect sender account...", render_kpi_cards(total, stats['registered'], stats['sent'], stats['skipped'], stats['failed'], is_running=True), None
                        await asyncio.sleep(sleep_time)
                else:
                    df.at[i, "Delivery Status"] = "🔍 Verified"
                    df.at[i, "Details"] = f"ID: {info['id']}"
                    await service.delete_contact(info["id"])
                    await asyncio.sleep(1.0)

            else:
                stats["skipped"] += 1
                df.at[i, "Registered"] = "❌ NO"
                df.at[i, "Delivery Status"] = "⏭️ SKIPPED"
                df.at[i, "Details"] = "Unregistered or privacy hidden"
                await asyncio.sleep(0.8)

        except Exception as e:
            stats["failed"] += 1
            df.at[i, "Registered"] = "⚠️ ERROR"
            df.at[i, "Delivery Status"] = "⚠️ ERROR"
            df.at[i, "Details"] = str(e)

        progress((i + 1) / total, desc=f"Processed {i + 1}/{total} numbers")
        yield df, f"Processed {i + 1}/{total} phone numbers", render_kpi_cards(total, stats['registered'], stats['sent'], stats['skipped'], stats['failed'], is_running=(i < total - 1)), None

    # Save to CSV and JSON on completion
    csv_path = "auto_send_results.csv"
    json_path = "auto_send_results.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(df.to_dict(orient="records"), f, indent=2, ensure_ascii=False)

    summary_text = (
        f"🎉 **Batch Complete!** Processed **{total}** numbers. "
        f"Found **{stats['registered']}** registered profiles, sent **{stats['sent']}** messages. "
        f"Report exported to `{csv_path}`."
    )
    yield df, summary_text, render_kpi_cards(total, stats['registered'], stats['sent'], stats['skipped'], stats['failed'], is_running=False), csv_path

# Tab 2: Single Phone Handlers
async def handle_single_check(phone_str, country_code):
    if not phone_str:
        return "❌ Please enter a phone number.", "", gr.update(interactive=False)

    e164 = format_phone_e164(phone_str, default_region=country_code)
    try:
        is_reg, info, _ = await service.check_phone_registration(e164, cleanup_contact=False)
        if is_reg and info:
            name = f"{info['first_name']} {info['last_name']}".strip()
            username = f"@{info['username']}" if info['username'] else "No username"
            result_md = (
                f"### ✅ **Phone is Registered on Telegram!**\n"
                f"- **Normalized (E.164)**: `{e164}`\n"
                f"- **Full Name**: **{name}**\n"
                f"- **Username**: `{username}`\n"
                f"- **Telegram User ID**: `{info['id']}`\n"
                f"- **Account Status**: `{info['status']}`"
            )
            return result_md, e164, gr.update(interactive=True)
        else:
            result_md = (
                f"### ⚠️ **Not Registered or Privacy Hidden**\n"
                f"- **Normalized (E.164)**: `{e164}`\n"
                f"- Telegram did not find an active public account for this number."
            )
            return result_md, e164, gr.update(interactive=False)
    except Exception as e:
        return f"❌ Error: {str(e)}", e164, gr.update(interactive=False)

async def handle_single_send(phone_str, message_text, bot_link, country_code):
    if not phone_str or not message_text:
        return "❌ Phone number and message are required."

    e164 = format_phone_e164(phone_str, default_region=country_code)
    try:
        is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
        if not is_reg or not user_entity:
            return f"⚠️ Cannot send: `{e164}` is not registered on Telegram."

        final_msg = service.format_message_template(message_text, user_info=info, bot_link=bot_link)
        success, details = await service.send_message_to_user(user_entity, final_msg)
        await service.delete_contact(info["id"])
        
        if success:
            return f"✅ **Message Sent Successfully!** (Telegram Message ID: `{details}`)"
        else:
            return f"❌ **Send Failed**: {details}"
    except Exception as e:
        return f"❌ Error sending message: {str(e)}"

# UI Construction
def build_ui():
    with gr.Blocks(title="Telegram Auto-Messenger & Lead Qualifier") as demo:
        gr.HTML(
            """
            <div class="header-banner">
                <div class="header-title">⚡ Telegram Phone Registration & Auto-Messenger Suite</div>
                <div class="header-sub">Automated contact resolution via MTProto & direct messaging pipeline with Bot link onboarding and flood protection.</div>
            </div>
            """
        )

        with gr.Row():
            auth_status_box = gr.Markdown("### 🔄 Checking Telegram Session Status...")

        with gr.Tabs():
            # Tab 1: Primary Batch Auto-Messenger (Target Demo for Monday)
            with gr.Tab("🚀 Batch Auto-Messenger (Production Demo)"):
                kpi_display = gr.HTML(render_kpi_cards(20, 0, 0, 0, 0))

                with gr.Row():
                    # Left Column: Inputs & Controls
                    with gr.Column(scale=1):
                        gr.Markdown("### 📝 1. Target Phone Numbers")
                        batch_phone_text = gr.Textbox(
                            label="Phone Numbers (One per line)", 
                            value=get_20_sample_numbers(), 
                            lines=8,
                            placeholder="Enter local or international phone numbers..."
                        )
                        
                        with gr.Row():
                            load_20_btn = gr.Button("📋 Reset / Load 20 Test Numbers", size="sm", variant="secondary")
                            batch_country = gr.Dropdown(
                                label="Country Code", 
                                choices=["KH", "US", "TH", "VN", "SG", "MY"], 
                                value="KH",
                                scale=1
                            )

                        gr.Markdown("---")
                        gr.Markdown("### 💬 2. Message & Bot Configuration")
                        bot_link_input = gr.Textbox(
                            label="Official Bot Link / Username", 
                            value="https://t.me/YourOfficialBot", 
                            placeholder="e.g. https://t.me/YourSupportBot"
                        )
                        batch_msg_template = gr.Textbox(
                            label="Message Content Template", 
                            value=DEFAULT_BOT_MESSAGE, 
                            lines=4
                        )
                        
                        with gr.Accordion("👁️ Message Preview for Recipient", open=False):
                            preview_display = gr.Markdown(f"```text\n{DEFAULT_BOT_MESSAGE.replace('{bot_link}', 'https://t.me/YourOfficialBot')}\n```")

                        gr.Markdown("---")
                        gr.Markdown("### 🛡️ 3. Anti-Flood Jitter Delay")
                        with gr.Row():
                            min_delay = gr.Slider(minimum=5, maximum=60, value=15, step=1, label="Min Delay (sec)")
                            max_delay = gr.Slider(minimum=10, maximum=120, value=30, step=1, label="Max Delay (sec)")

                        with gr.Row():
                            check_batch_btn = gr.Button("🔍 1. Check Numbers Only", variant="secondary")
                            send_batch_btn = gr.Button("🚀 2. Auto-Send to Registered", variant="primary")
                        
                        stop_batch_btn = gr.Button("🛑 Emergency Stop", variant="stop")

                    # Right Column: Real-time Live Streaming Table & Export
                    with gr.Column(scale=2):
                        gr.Markdown("### 📊 Real-Time Execution Table")
                        batch_status_msg = gr.Markdown("Ready. Click **Auto-Send to Registered** to begin.")
                        
                        results_table = gr.Dataframe(
                            headers=["#", "Raw Input", "Normalized (E.164)", "Registered", "Name", "Username", "Delivery Status", "Details"],
                            datatype=["number", "str", "str", "str", "str", "str", "str", "str"],
                            interactive=False,
                            wrap=True
                        )

                        download_csv = gr.File(label="📥 Download Exported CSV Report", interactive=False)

                # Event handlers for Tab 1
                load_20_btn.click(fn=get_20_sample_numbers, outputs=[batch_phone_text])
                
                bot_link_input.change(
                    fn=update_preview,
                    inputs=[batch_msg_template, bot_link_input],
                    outputs=[preview_display]
                )
                batch_msg_template.change(
                    fn=update_preview,
                    inputs=[batch_msg_template, bot_link_input],
                    outputs=[preview_display]
                )

                check_batch_btn.click(
                    fn=lambda p, c, m, b: process_batch_streaming(p, c, auto_send=False, message_text="", bot_link="", min_delay=0, max_delay=0),
                    inputs=[batch_phone_text, batch_country, batch_msg_template, bot_link_input],
                    outputs=[results_table, batch_status_msg, kpi_display, download_csv]
                )

                send_batch_btn.click(
                    fn=lambda p, c, m, b, mi, ma: process_batch_streaming(p, c, auto_send=True, message_text=m, bot_link=b, min_delay=mi, max_delay=ma),
                    inputs=[batch_phone_text, batch_country, batch_msg_template, bot_link_input, min_delay, max_delay],
                    outputs=[results_table, batch_status_msg, kpi_display, download_csv]
                )

                stop_batch_btn.click(fn=trigger_stop, outputs=[batch_status_msg])

            # Tab 2: Single Phone Quick Inspector
            with gr.Tab("🔍 Single Phone Lookup & Test"):
                with gr.Row():
                    with gr.Column():
                        single_phone = gr.Textbox(label="Phone Number", placeholder="e.g. 0968271451 or +855968271451", value="0968271451")
                        single_country = gr.Dropdown(label="Default Region", choices=["KH", "US", "TH", "VN", "SG", "MY"], value="KH")
                        check_single_btn = gr.Button("🔍 Check Registration", variant="primary")
                    with gr.Column():
                        single_result_box = gr.Markdown("Enter a phone number and click Check Registration.")

                gr.Markdown("---")
                gr.Markdown("### Direct Message Test")
                with gr.Row():
                    with gr.Column():
                        single_bot_link = gr.Textbox(label="Bot Link", value="https://t.me/YourOfficialBot")
                        single_test_msg = gr.Textbox(label="Message Template", value=DEFAULT_BOT_MESSAGE, lines=3)
                        send_single_btn = gr.Button("✉️ Send Message Now", variant="secondary")
                    with gr.Column():
                        single_send_result = gr.Markdown()

                check_single_btn.click(
                    handle_single_check,
                    inputs=[single_phone, single_country],
                    outputs=[single_result_box, single_phone, send_single_btn]
                )

                send_single_btn.click(
                    handle_single_send,
                    inputs=[single_phone, single_test_msg, single_bot_link, single_country],
                    outputs=[single_send_result]
                )

            # Tab 3: Telegram Login & Account Session
            with gr.Tab("🔐 Telegram Account & Credentials"):
                gr.Markdown(
                    """
                    ### 📱 Connect Sender Account
                    Credentials are saved safely to your local `.env`. Sessions are stored in `telebot_session.session`.
                    """
                )
                with gr.Row():
                    api_id_input = gr.Textbox(
                        label="Telegram API ID", 
                        value=os.getenv("TELEGRAM_API_ID", ""), 
                        placeholder="e.g. 12345678"
                    )
                    api_hash_input = gr.Textbox(
                        label="Telegram API Hash", 
                        value=os.getenv("TELEGRAM_API_HASH", ""), 
                        placeholder="e.g. 0123456789abcdef0123456789abcdef", 
                        type="password"
                    )
                
                phone_input = gr.Textbox(
                    label="Sender Account Phone Number (with Country Code)", 
                    value=os.getenv("TELEGRAM_PHONE", "+855"), 
                    placeholder="+855XXXXXXXX"
                )

                send_code_btn = gr.Button("📲 1. Request Login Verification Code", variant="primary")
                code_status = gr.Markdown()

                with gr.Row():
                    code_input = gr.Textbox(label="Enter Verification Code", placeholder="Code sent to Telegram / SMS")
                    pwd_input = gr.Textbox(label="2FA Password (If enabled on account)", type="password")

                login_btn = gr.Button("🔓 2. Verify & Authenticate Session", variant="secondary")
                login_status = gr.Markdown()

                send_code_btn.click(
                    save_credentials_and_send_code,
                    inputs=[api_id_input, api_hash_input, phone_input],
                    outputs=[code_status, auth_status_box]
                )

                login_btn.click(
                    verify_code,
                    inputs=[code_input, pwd_input],
                    outputs=[login_status, auth_status_box]
                )

        demo.load(check_auth_status, outputs=[auth_status_box])
    return demo

if __name__ == "__main__":
    app = build_ui()
    available_port = find_available_port(7860, 7890)
    print(f"🚀 Starting Telegram Auto-Sender Web App on http://127.0.0.1:{available_port} ...")
    
    launch_kwargs = {
        "server_name": "127.0.0.1",
        "inbrowser": True,
        "css": CUSTOM_CSS,
        "theme": gr.themes.Soft()
    }
    if available_port != 0:
        launch_kwargs["server_port"] = available_port
        
    app.launch(**launch_kwargs)
