import os
import sys
import random
import asyncio
import pandas as pd
import gradio as gr
from dotenv import load_dotenv

from utils import format_phone_e164
from telegram_service import TelegramService

load_dotenv()

service = TelegramService()

# Helper to load existing phone-list.txt if present
def get_initial_phone_list():
    if os.path.exists("phone-list.txt"):
        with open("phone-list.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    return "09342252\n0183910978\n0968271451\n087225303"

async def check_auth_status():
    """Checks and returns the current authentication status badge."""
    try:
        if await service.is_authenticated():
            me = await service.get_me_info()
            if me:
                name = f"{me['first_name']} {me['last_name']}".strip()
                username = f"@{me['username']}" if me['username'] else "No Username"
                return (
                    f"### 🟢 **Connected to Telegram**\n"
                    f"- **Account**: {name} ({username})\n"
                    f"- **User ID**: `{me['id']}` | **Phone**: `{me['phone']}`"
                )
        return "### 🔴 **Not Connected** (Please configure API credentials & log in below)"
    except Exception as e:
        return f"### ⚠️ **Connection Status**: {str(e)}"

async def save_credentials_and_send_code(api_id, api_hash, phone):
    """Saves credentials to .env and triggers login verification code."""
    if not api_id or not api_hash or not phone:
        return "❌ Please enter API ID, API Hash, and Phone Number.", gr.update()
    
    # Save to .env
    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"TELEGRAM_API_ID={str(api_id).strip()}\n")
        f.write(f"TELEGRAM_API_HASH={str(api_hash).strip()}\n")
        f.write(f"TELEGRAM_PHONE={str(phone).strip()}\n")
        f.write("DEFAULT_COUNTRY=KH\nMIN_DELAY_SECONDS=15\nMAX_DELAY_SECONDS=35\n")
    
    service.reload_env()
    service.client = None  # Reset client with new credentials

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

# Tab 2: Single Phone Test
async def handle_single_check(phone_str, country_code):
    if not phone_str:
        return "❌ Please enter a phone number.", "", ""

    e164 = format_phone_e164(phone_str, default_region=country_code)
    try:
        is_reg, info, _ = await service.check_phone_registration(e164, cleanup_contact=False)
        if is_reg and info:
            name = f"{info['first_name']} {info['last_name']}".strip()
            username = f"@{info['username']}" if info['username'] else "None"
            result_md = (
                f"### ✅ **Phone is Registered on Telegram!**\n"
                f"- **Normalized (E.164)**: `{e164}`\n"
                f"- **Full Name**: {name}\n"
                f"- **Username**: {username}\n"
                f"- **Telegram ID**: `{info['id']}`\n"
                f"- **Status / Activity**: {info['status']}"
            )
            return result_md, e164, gr.update(interactive=True)
        else:
            result_md = (
                f"### ⚠️ **Not Registered or Hidden by Privacy**\n"
                f"- Normalized: `{e164}`\n"
                f"- Telegram did not find an active account for this number."
            )
            return result_md, e164, gr.update(interactive=False)
    except Exception as e:
        return f"❌ Error: {str(e)}", e164, gr.update(interactive=False)

async def handle_single_send(phone_str, message_text, country_code):
    if not phone_str or not message_text:
        return "❌ Phone number and message are required."

    e164 = format_phone_e164(phone_str, default_region=country_code)
    try:
        is_reg, _, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
        if not is_reg or not user_entity:
            return f"⚠️ Cannot send: {e164} is not registered on Telegram."

        success, details = await service.send_message_to_user(user_entity, message_text)
        if success:
            return f"✅ **Message Sent Successfully!** (Message ID: `{details}`)"
        else:
            return f"❌ **Send Failed**: {details}"
    except Exception as e:
        return f"❌ Error sending message: {str(e)}"

# Tab 3: Batch Operations
async def process_batch_numbers(phone_text, country_code, auto_send, message_text, min_delay, max_delay, progress=gr.Progress()):
    if not phone_text:
        return pd.DataFrame(), "❌ Phone list is empty."

    lines = [line.strip() for line in phone_text.splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        return pd.DataFrame(), "❌ No valid phone numbers found."

    results = []
    total = len(lines)
    progress(0, desc=f"Processing {total} numbers...")

    for i, raw_phone in enumerate(lines):
        e164 = format_phone_e164(raw_phone, default_region=country_code)
        row = {
            "Raw Input": raw_phone,
            "Normalized (E.164)": e164,
            "Registered": "Checking...",
            "Name": "-",
            "Username": "-",
            "Delivery Status": "Skipped" if not auto_send else "Pending",
            "Details": ""
        }

        try:
            is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=not auto_send)
            if is_reg and info:
                row["Registered"] = "✅ YES"
                row["Name"] = f"{info['first_name']} {info['last_name']}".strip()
                row["Username"] = f"@{info['username']}" if info['username'] else "-"

                if auto_send and user_entity:
                    success, send_info = await service.send_message_to_user(user_entity, message_text)
                    if success:
                        row["Delivery Status"] = "✅ SENT"
                        row["Details"] = f"Msg ID: {send_info}"
                    else:
                        row["Delivery Status"] = "❌ FAILED"
                        row["Details"] = str(send_info)

                    # Delete contact after send
                    try:
                        await service.client(service.client.build_delete_contacts_request([user_entity.id]))
                    except Exception:
                        pass

                    # Anti-spam delay
                    if i < total - 1:
                        sleep_time = random.randint(int(min_delay), int(max_delay))
                        await asyncio.sleep(sleep_time)
                else:
                    row["Delivery Status"] = "Check Only"
                    row["Details"] = "Verified"
            else:
                row["Registered"] = "❌ NO"
                row["Delivery Status"] = "SKIPPED"
                row["Details"] = "Not found or privacy restricted"

        except Exception as e:
            row["Registered"] = "⚠️ ERROR"
            row["Delivery Status"] = "ERROR"
            row["Details"] = str(e)

        results.append(row)
        progress((i + 1) / total, desc=f"Processed {i + 1}/{total}...")
        if not auto_send:
            await asyncio.sleep(0.5)

    df = pd.DataFrame(results)
    summary_msg = f"🎉 Finished processing {total} phone numbers!"
    return df, summary_msg

def build_ui():
    custom_css = """
    .gradio-container { max-width: 1100px !important; margin: auto; }
    .status-box { padding: 12px; border-radius: 8px; background: #f8fafc; border: 1px solid #e2e8f0; }
    """

    with gr.Blocks(title="Telegram Contact Checker & Auto-Sender", css=custom_css, theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            """
            # 📱 Telegram Phone Registration & Auto-Messenger
            Check if phone numbers are registered on Telegram and safely send automated messages via MTProto.
            """
        )

        auth_status_box = gr.Markdown("### Checking connection status...")

        with gr.Tabs():
            # Tab 1: Auth
            with gr.Tab("🔐 Telegram Login & Credentials"):
                gr.Markdown(
                    """
                    ### 1. Configure Telegram API
                    Get your free **API ID** and **API Hash** from [my.telegram.org](https://my.telegram.org) -> **API development tools**.
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
                    label="Your Telegram Account Phone Number (with Country Code)", 
                    value=os.getenv("TELEGRAM_PHONE", "+855"), 
                    placeholder="+855XXXXXXXX"
                )

                send_code_btn = gr.Button("📲 Save & Request Verification Code", variant="primary")
                code_status = gr.Markdown()

                with gr.Row():
                    code_input = gr.Textbox(label="Enter Verification Code", placeholder="Received in Telegram / SMS")
                    pwd_input = gr.Textbox(label="2FA Password (If enabled)", type="password")

                login_btn = gr.Button("🔓 Verify & Log In", variant="secondary")
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

            # Tab 2: Single Phone Test
            with gr.Tab("🔍 Single Phone Lookup & Test"):
                with gr.Row():
                    with gr.Column():
                        single_phone = gr.Textbox(label="Phone Number to Test", placeholder="e.g. 0968271451 or +855968271451", value="0968271451")
                        country_select = gr.Dropdown(label="Default Country Code", choices=["KH", "US", "TH", "VN", "SG", "MY"], value="KH")
                        check_single_btn = gr.Button("🔍 Check Registration", variant="primary")
                    
                    with gr.Column():
                        single_result_box = gr.Markdown("Enter a phone number to check registration.")

                gr.Markdown("---")
                gr.Markdown("### Send Test Message to This User")
                with gr.Row():
                    with gr.Column():
                        test_msg = gr.Textbox(label="Message Text", value="Hello! This is a test notification from Telegram Auto-Send.", lines=3)
                        send_single_btn = gr.Button("✉️ Send Message Now", variant="secondary")
                    with gr.Column():
                        send_result_box = gr.Markdown()

                check_single_btn.click(
                    handle_single_check,
                    inputs=[single_phone, country_select],
                    outputs=[single_result_box, single_phone, send_single_btn]
                )

                send_single_btn.click(
                    handle_single_send,
                    inputs=[single_phone, test_msg, country_select],
                    outputs=[send_result_box]
                )

            # Tab 3: Batch Phone List
            with gr.Tab("📋 Batch Phone List & Auto-Sender"):
                with gr.Row():
                    with gr.Column(scale=1):
                        batch_phone_text = gr.Textbox(
                            label="Phone Numbers (One per line)", 
                            value=get_initial_phone_list(), 
                            lines=8
                        )
                        batch_country = gr.Dropdown(label="Default Country Code", choices=["KH", "US", "TH", "VN", "SG"], value="KH")
                        batch_msg = gr.Textbox(label="Message Content (for Auto-Send)", value="Hello! Thank you for connecting with us.", lines=3)

                        with gr.Row():
                            min_delay = gr.Slider(minimum=5, maximum=60, value=15, step=1, label="Min Delay (sec)")
                            max_delay = gr.Slider(minimum=10, maximum=120, value=35, step=1, label="Max Delay (sec)")

                        with gr.Row():
                            check_batch_btn = gr.Button("🔍 Check Numbers Only", variant="secondary")
                            send_batch_btn = gr.Button("🚀 Auto-Send to Registered", variant="primary")

                    with gr.Column(scale=2):
                        batch_status_msg = gr.Markdown("Ready to process.")
                        results_table = gr.Dataframe(
                            headers=["Raw Input", "Normalized (E.164)", "Registered", "Name", "Username", "Delivery Status", "Details"],
                            datatype=["str", "str", "str", "str", "str", "str", "str"],
                            interactive=False
                        )

                check_batch_btn.click(
                    fn=lambda p, c: process_batch_numbers(p, c, auto_send=False, message_text="", min_delay=0, max_delay=0),
                    inputs=[batch_phone_text, batch_country],
                    outputs=[results_table, batch_status_msg]
                )

                send_batch_btn.click(
                    fn=lambda p, c, m, mi, ma: process_batch_numbers(p, c, auto_send=True, message_text=m, min_delay=mi, max_delay=ma),
                    inputs=[batch_phone_text, batch_country, batch_msg, min_delay, max_delay],
                    outputs=[results_table, batch_status_msg]
                )

        demo.load(check_auth_status, outputs=[auth_status_box])
    return demo

if __name__ == "__main__":
    app = build_ui()
    app.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
