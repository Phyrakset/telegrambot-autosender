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
STOP_SIGNAL = False

DEFAULT_BOT_MESSAGE = (
    "Hello! 👋 Thank you for reaching out.\n"
    "To start chatting with our official assistant, tap the link below:\n"
    "👉 {bot_link}"
)

CUSTOM_CSS = """
/* Modern SaaS Minimalist Theme */
.gradio-container {
    max-width: 1250px !important;
    margin: 0 auto !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
}
.app-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    background: #0f172a;
    border-radius: 12px;
    margin-bottom: 16px;
    border: 1px solid #1e293b;
}
.app-brand {
    display: flex;
    align-items: center;
    gap: 10px;
}
.app-title {
    font-size: 18px;
    font-weight: 700;
    color: #f8fafc;
    margin: 0;
    letter-spacing: -0.3px;
}
.app-subtitle {
    font-size: 12px;
    color: #94a3b8;
    margin: 0;
}
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 16px;
}
.kpi-card {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 10px;
    padding: 14px 16px;
}
.kpi-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
}
.kpi-value {
    font-size: 24px;
    font-weight: 700;
    margin-top: 4px;
    color: #f8fafc;
}
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    background: #1e293b;
    color: #e2e8f0;
}
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
    return 0

def get_default_phone_list():
    if os.path.exists("phone-list.txt"):
        with open("phone-list.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    return (
        "0968271451\n0183910978\n09342252\n087225303\n012345678\n"
        "010889922\n0977123456\n0885544332\n070998877\n092112233\n"
        "016554433\n098776655\n089223344\n060123456\n0719876543\n"
        "011223344\n095887766\n086445566\n069334455\n077123987"
    )

def render_kpi_html(total: int = 20, registered: int = 0, delivered: int = 0, skipped: int = 0):
    return f"""
    <div class="kpi-grid">
        <div class="kpi-card" style="border-left: 3px solid #3b82f6;">
            <div class="kpi-label">Target Numbers</div>
            <div class="kpi-value">{total}</div>
        </div>
        <div class="kpi-card" style="border-left: 3px solid #10b981;">
            <div class="kpi-label">Registered Accounts</div>
            <div class="kpi-value" style="color:#34d399;">{registered}</div>
        </div>
        <div class="kpi-card" style="border-left: 3px solid #8b5cf6;">
            <div class="kpi-label">Delivered Messages</div>
            <div class="kpi-value" style="color:#a78bfa;">{delivered}</div>
        </div>
        <div class="kpi-card" style="border-left: 3px solid #f59e0b;">
            <div class="kpi-label">Skipped / Private</div>
            <div class="kpi-value" style="color:#fbbf24;">{skipped}</div>
        </div>
    </div>
    """

def get_empty_df():
    return pd.DataFrame(columns=["#", "Phone (E.164)", "Registration", "Recipient", "Delivery Status", "Details"])

async def check_header_status():
    """Returns clean compact account status HTML."""
    try:
        if await service.is_authenticated():
            me = await service.get_me_info()
            if me:
                name = f"{me['first_name']} {me['last_name']}".strip()
                uname = f"@{me['username']}" if me['username'] else f"+{me['phone']}"
                return f"""
                <div class="status-pill" style="border: 1px solid #059669; background: #064e3b; color: #a7f3d0;">
                    <span style="height:8px;width:8px;border-radius:50%;background:#10b981;display:inline-block;"></span>
                    <span>{name} ({uname})</span>
                </div>
                """
        return """
        <div class="status-pill" style="border: 1px solid #dc2626; background: #450a0a; color: #fecaca;">
            <span style="height:8px;width:8px;border-radius:50%;background:#ef4444;display:inline-block;"></span>
            <span>Disconnected · Log In Required</span>
        </div>
        """
    except Exception:
        return """
        <div class="status-pill" style="border: 1px solid #d97706; background: #451a03; color: #fde68a;">
            <span>⚠️ Session Offline</span>
        </div>
        """

def set_stop():
    global STOP_SIGNAL
    STOP_SIGNAL = True
    return "🛑 Stopping after current step..."

# Core Batch Processor
async def execute_batch(
    phone_text: str,
    country_code: str,
    auto_send: bool,
    message_text: str,
    bot_link: str,
    min_delay: int,
    max_delay: int
):
    global STOP_SIGNAL
    STOP_SIGNAL = False

    cols = ["#", "Phone (E.164)", "Registration", "Recipient", "Delivery Status", "Details"]
    if not phone_text or not phone_text.strip():
        yield get_empty_df(), "⚠️ Phone list is empty.", render_kpi_html(0, 0, 0, 0)
        return

    lines = [line.strip() for line in phone_text.splitlines() if line.strip() and not line.startswith("#")]
    total = len(lines)
    if total == 0:
        yield get_empty_df(), "⚠️ No valid phone numbers found.", render_kpi_html(0, 0, 0, 0)
        return

    try:
        await service.connect()
        if not await service.is_authenticated():
            yield get_empty_df(), "❌ Not logged in. Please authenticate in Account Settings tab first.", render_kpi_html(total, 0, 0, 0)
            return
    except Exception as e:
        yield get_empty_df(), f"❌ Connection Error: {e}", render_kpi_html(total, 0, 0, 0)
        return

    # Pre-populate table rows
    rows = []
    for i, raw in enumerate(lines, 1):
        e164 = format_phone_e164(raw, default_region=country_code)
        rows.append({
            "#": i,
            "Phone (E.164)": e164,
            "Registration": "⏳ Queued",
            "Recipient": "-",
            "Delivery Status": "Pending" if auto_send else "Queued",
            "Details": ""
        })

    df = pd.DataFrame(rows)
    stats = {"registered": 0, "delivered": 0, "skipped": 0, "failed": 0}
    
    action_label = "Auto-Sending messages" if auto_send else "Checking registrations"
    yield df, f"⚡ Starting campaign: {action_label} for {total} numbers...", render_kpi_html(total, 0, 0, 0)

    for idx, raw in enumerate(lines):
        if STOP_SIGNAL:
            yield df, f"🛑 Campaign stopped by user at #{idx}/{total}.", render_kpi_html(total, stats["registered"], stats["delivered"], stats["skipped"])
            return

        e164 = format_phone_e164(raw, default_region=country_code)
        df.at[idx, "Registration"] = "🔍 Checking..."
        df.at[idx, "Details"] = "Querying MTProto..."
        yield df, f"Processing [{idx + 1}/{total}]: {e164}", render_kpi_html(total, stats["registered"], stats["delivered"], stats["skipped"])

        try:
            is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
            if is_reg and info:
                stats["registered"] += 1
                name = f"{info['first_name']} {info['last_name']}".strip()
                uname = f"@{info['username']}" if info['username'] else "-"
                
                df.at[idx, "Registration"] = "✅ Registered"
                df.at[idx, "Recipient"] = f"{name} ({uname})"

                if auto_send and user_entity:
                    df.at[idx, "Delivery Status"] = "🚀 Sending..."
                    yield df, f"Sending message to {name}...", render_kpi_html(total, stats["registered"], stats["delivered"], stats["skipped"])

                    final_msg = service.format_message_template(message_text, user_info=info, bot_link=bot_link)
                    success, detail = await service.send_message_to_user(user_entity, final_msg)

                    if success:
                        stats["delivered"] += 1
                        df.at[idx, "Delivery Status"] = "✅ Delivered"
                        df.at[idx, "Details"] = f"Msg #{detail}"
                    else:
                        stats["failed"] += 1
                        df.at[idx, "Delivery Status"] = "❌ Failed"
                        df.at[idx, "Details"] = str(detail)

                    await service.delete_contact(info["id"])

                    # Anti-spam jitter delay
                    if idx < total - 1:
                        sleep_s = random.randint(int(min_delay), int(max_delay))
                        df.at[idx, "Details"] = f"Delivered (Waiting {sleep_s}s)"
                        yield df, f"Anti-flood sleep: {sleep_s}s before next contact...", render_kpi_html(total, stats["registered"], stats["delivered"], stats["skipped"])
                        await asyncio.sleep(sleep_s)
                else:
                    df.at[idx, "Delivery Status"] = "Verified"
                    df.at[idx, "Details"] = f"ID: {info['id']}"
                    await service.delete_contact(info["id"])
                    await asyncio.sleep(0.8)
            else:
                stats["skipped"] += 1
                df.at[idx, "Registration"] = "❌ Unregistered"
                df.at[idx, "Delivery Status"] = "⏭️ Skipped"
                df.at[idx, "Details"] = "Not found / hidden"
                await asyncio.sleep(0.5)

        except Exception as err:
            stats["failed"] += 1
            df.at[idx, "Registration"] = "⚠️ Error"
            df.at[idx, "Delivery Status"] = "Error"
            df.at[idx, "Details"] = str(err)

        yield df, f"Completed {idx + 1} of {total} numbers", render_kpi_html(total, stats["registered"], stats["delivered"], stats["skipped"])

    # Auto-export CSV
    try:
        df.to_csv("auto_send_results.csv", index=False, encoding="utf-8-sig")
    except Exception:
        pass

    summary = f"🎉 Campaign Finished! Checked {total} numbers · {stats['registered']} registered · {stats['delivered']} messages sent."
    yield df, summary, render_kpi_html(total, stats["registered"], stats["delivered"], stats["skipped"])

# Async Handlers for Buttons
async def on_start_autosend(phone_text, country, msg, bot_link, min_d, max_d):
    async for item in execute_batch(phone_text, country, True, msg, bot_link, min_d, max_d):
        yield item

async def on_start_verify_only(phone_text, country, msg, bot_link, min_d, max_d):
    async for item in execute_batch(phone_text, country, False, "", "", 0, 0):
        yield item

# Tab 2 Single Lookups
async def on_single_lookup(phone_str, country):
    if not phone_str:
        return "Please enter a phone number."
    e164 = format_phone_e164(phone_str, default_region=country)
    try:
        is_reg, info, _ = await service.check_phone_registration(e164, cleanup_contact=False)
        if is_reg and info:
            name = f"{info['first_name']} {info['last_name']}".strip()
            uname = f"@{info['username']}" if info['username'] else "None"
            return f"✅ **Registered**: {name} ({uname}) · ID: `{info['id']}` · Activity: `{info['status']}`"
        return f"❌ **Not Registered / Private**: `{e164}`"
    except Exception as e:
        return f"⚠️ Error: {e}"

async def on_single_send(phone_str, msg, bot_link, country):
    if not phone_str or not msg:
        return "Phone number and message are required."
    e164 = format_phone_e164(phone_str, default_region=country)
    try:
        is_reg, info, entity = await service.check_phone_registration(e164, cleanup_contact=False)
        if not is_reg or not entity:
            return f"❌ Cannot send: `{e164}` is not registered."
        final_msg = service.format_message_template(msg, user_info=info, bot_link=bot_link)
        ok, res = await service.send_message_to_user(entity, final_msg)
        await service.delete_contact(info["id"])
        return f"✅ **Sent successfully!** (Message ID: `{res}`)" if ok else f"❌ **Failed**: {res}"
    except Exception as e:
        return f"⚠️ Send Error: {e}"

# Tab 3 Login Handlers
async def on_request_code(api_id, api_hash, phone):
    if not api_id or not api_hash or not phone:
        return "Please fill in API ID, API Hash, and Phone Number.", await check_header_status()
    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"TELEGRAM_API_ID={str(api_id).strip()}\n")
        f.write(f"TELEGRAM_API_HASH={str(api_hash).strip()}\n")
        f.write(f"TELEGRAM_PHONE={str(phone).strip()}\n")
        f.write("DEFAULT_COUNTRY=KH\nMIN_DELAY_SECONDS=15\nMAX_DELAY_SECONDS=35\n")
    service.reload_env()
    service.client = None
    ok, msg = await service.send_auth_code(phone)
    status_text = f"✅ {msg}" if ok else f"❌ {msg}"
    return status_text, await check_header_status()

async def on_verify_login(code, pwd):
    if not code:
        return "Please enter the verification code.", await check_header_status()
    ok, msg, needs_pwd = await service.sign_in_with_code(code, pwd)
    badge = await check_header_status()
    if ok:
        return f"✅ {msg}", badge
    elif needs_pwd:
        return f"⚠️ {msg}", badge
    return f"❌ {msg}", badge

def build_app():
    with gr.Blocks(title="TeleSender Pro") as demo:
        # Compact Header
        with gr.Row(elem_classes=["app-header"]):
            with gr.Column(scale=3):
                gr.HTML(
                    """
                    <div class="app-brand">
                        <div>
                            <div class="app-title">⚡ TeleSender Pro</div>
                            <div class="app-subtitle">Automated Lead Qualifier & Telegram Direct Outreach</div>
                        </div>
                    </div>
                    """
                )
            with gr.Column(scale=2):
                header_status = gr.HTML(
                    """
                    <div class="status-pill">
                        <span>Checking session...</span>
                    </div>
                    """
                )

        with gr.Tabs():
            # Main Tab: Campaign Automation
            with gr.Tab("🚀 Broadcast Campaign"):
                kpi_box = gr.HTML(render_kpi_html(20, 0, 0, 0))

                with gr.Row():
                    # Left Column: Configuration & Actions
                    with gr.Column(scale=4):
                        with gr.Group():
                            with gr.Row():
                                batch_country = gr.Dropdown(
                                    label="Region", 
                                    choices=["KH", "US", "TH", "VN", "SG", "MY"], 
                                    value="KH",
                                    scale=1
                                )
                                reload_btn = gr.Button("🔄 Load 20 Test Numbers", size="sm", scale=1)

                            phone_input = gr.Textbox(
                                label="Phone Numbers", 
                                value=get_default_phone_list(), 
                                lines=7,
                                placeholder="Paste phone numbers (one per line)..."
                            )

                        with gr.Group():
                            bot_link_input = gr.Textbox(
                                label="Official Bot Link", 
                                value="https://t.me/YourOfficialBot",
                                placeholder="https://t.me/YourBot"
                            )
                            msg_input = gr.Textbox(
                                label="Message Template", 
                                value=DEFAULT_BOT_MESSAGE, 
                                lines=3
                            )

                        with gr.Row():
                            min_delay = gr.Slider(5, 45, value=15, step=1, label="Min Delay (s)")
                            max_delay = gr.Slider(10, 60, value=30, step=1, label="Max Delay (s)")

                        with gr.Row():
                            send_btn = gr.Button("🚀 Start Auto-Send", variant="primary", scale=2)
                            verify_btn = gr.Button("🔍 Verify Only", variant="secondary", scale=1)
                            stop_btn = gr.Button("⏹ Stop", variant="stop", scale=1)

                    # Right Column: Clean Live Data Table
                    with gr.Column(scale=6):
                        status_ticker = gr.Markdown("**Status**: Ready to launch.")
                        table_output = gr.Dataframe(
                            value=get_empty_df(),
                            headers=["#", "Phone (E.164)", "Registration", "Recipient", "Delivery Status", "Details"],
                            datatype=["number", "str", "str", "str", "str", "str"],
                            interactive=False,
                            wrap=True
                        )

                # Event Bindings for Main Tab
                reload_btn.click(fn=get_default_phone_list, outputs=[phone_input])
                
                send_btn.click(
                    fn=on_start_autosend,
                    inputs=[phone_input, batch_country, msg_input, bot_link_input, min_delay, max_delay],
                    outputs=[table_output, status_ticker, kpi_box]
                )

                verify_btn.click(
                    fn=on_start_verify_only,
                    inputs=[phone_input, batch_country, msg_input, bot_link_input, min_delay, max_delay],
                    outputs=[table_output, status_ticker, kpi_box]
                )

                stop_btn.click(fn=set_stop, outputs=[status_ticker])

            # Tab 2: Single Lookup
            with gr.Tab("🔍 Single Lookup"):
                with gr.Row():
                    with gr.Column():
                        s_phone = gr.Textbox(label="Phone Number", value="0968271451")
                        s_country = gr.Dropdown(label="Country", choices=["KH", "US", "TH", "VN"], value="KH")
                        s_check_btn = gr.Button("🔍 Check Registration", variant="primary")
                        s_result = gr.Markdown()
                    
                    with gr.Column():
                        s_bot = gr.Textbox(label="Bot Link", value="https://t.me/YourOfficialBot")
                        s_msg = gr.Textbox(label="Message", value=DEFAULT_BOT_MESSAGE, lines=3)
                        s_send_btn = gr.Button("✉️ Send Message", variant="secondary")
                        s_send_res = gr.Markdown()

                s_check_btn.click(fn=on_single_lookup, inputs=[s_phone, s_country], outputs=[s_result])
                s_send_btn.click(fn=on_single_send, inputs=[s_phone, s_msg, s_bot, s_country], outputs=[s_send_res])

            # Tab 3: Account & Session
            with gr.Tab("⚙️ Account & Login"):
                with gr.Row():
                    api_id = gr.Textbox(label="API ID", value=os.getenv("TELEGRAM_API_ID", ""))
                    api_hash = gr.Textbox(label="API Hash", value=os.getenv("TELEGRAM_API_HASH", ""), type="password")
                phone_num = gr.Textbox(label="Sender Phone", value=os.getenv("TELEGRAM_PHONE", "+855"))
                req_btn = gr.Button("📲 Request Login Code")
                req_status = gr.Markdown()

                with gr.Row():
                    code_in = gr.Textbox(label="Verification Code")
                    pwd_in = gr.Textbox(label="2FA Password", type="password")
                login_btn = gr.Button("🔓 Authenticate Session")
                login_res = gr.Markdown()

                req_btn.click(fn=on_request_code, inputs=[api_id, api_hash, phone_num], outputs=[req_status, header_status])
                login_btn.click(fn=on_verify_login, inputs=[code_in, pwd_in], outputs=[login_res, header_status])

        demo.load(fn=check_header_status, outputs=[header_status])
    return demo

if __name__ == "__main__":
    app = build_app()
    port = find_available_port(7860, 7890)
    print(f"🚀 Starting TeleSender Pro on http://127.0.0.1:{port}")
    
    launch_kwargs = {
        "server_name": "127.0.0.1",
        "inbrowser": True,
        "css": CUSTOM_CSS,
        "theme": gr.themes.Soft()
    }
    if port != 0:
        launch_kwargs["server_port"] = port
        
    app.launch(**launch_kwargs)
