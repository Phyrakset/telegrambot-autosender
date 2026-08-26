import os
import sys
import socket
import asyncio
import pandas as pd
import gradio as gr
from telethon import custom, errors
from typing import Optional, Dict, Any, List
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from src.telebot.config import config, AppConfig
from src.telebot.utils.phone import format_phone_e164
from src.telebot.core.service import TelegramService

service = TelegramService()
STOP_SIGNAL = False

DEFAULT_OUTREACH_MESSAGE = config.tverkar_initial_message

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
    grid-template-columns: repeat(5, 1fr);
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
    font-size: 22px;
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
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0

def get_default_phone_list() -> str:
    for candidate in ["phone-list.txt", "phone-list.example.txt"]:
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read().strip()
    return ""

def get_empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["#", "Phone (E.164)", "Registration", "Recipient", "Delivery Status", "Reason"])

def get_tverkar_df() -> pd.DataFrame:
    if os.path.exists(config.tverkar_results_csv):
        try:
            return pd.read_csv(config.tverkar_results_csv, encoding="utf-8-sig")
        except Exception:
            pass
    return pd.DataFrame(columns=[
        "Index", "Timestamp", "Phone (E.164)", "Candidate Name", "Username",
        "Consent Transfer", "Employment Status", "Job Preference / Urgency",
        "Expected Salary", "Preferred Location", "Campaign Status", "Notes"
    ])

def get_survey_df() -> pd.DataFrame:
    if os.path.exists(config.survey_results_csv):
        try:
            return pd.read_csv(config.survey_results_csv, encoding="utf-8-sig")
        except Exception:
            pass
    return pd.DataFrame(columns=["#", "timestamp", "phone_e164", "name", "q1_answer", "q2_answer", "q3_answer", "survey_status", "reason"])

def render_kpi_html(total: int, reg: int, sent: int, privacy: int, unreg: int) -> str:
    return f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">Total Numbers</div>
            <div class="kpi-value" style="color: #60a5fa;">{total}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Registered Accounts</div>
            <div class="kpi-value" style="color: #34d399;">{reg}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Delivered / Sent</div>
            <div class="kpi-value" style="color: #a78bfa;">{sent}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Privacy Restricted</div>
            <div class="kpi-value" style="color: #fbbf24;">{privacy}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Unregistered</div>
            <div class="kpi-value" style="color: #94a3b8;">{unreg}</div>
        </div>
    </div>
    """

async def check_header_status() -> str:
    try:
        if await service.is_authenticated():
            me = await service.get_me_info()
            if me:
                name = f"{me['first_name']} {me['last_name']}".strip()
                uname = f"@{me['username']}" if me['username'] else "NoUser"
                return f"""
                <div class="status-pill" style="border: 1px solid #059669; background: #064e3b; color: #a7f3d0;">
                    <span style="height:8px;width:8px;border-radius:50%;background:#10b981;display:inline-block;"></span>
                    <span>Sender Phone: {name} ({uname})</span>
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
            <span>Session Offline</span>
        </div>
        """

def set_stop():
    global STOP_SIGNAL
    STOP_SIGNAL = True
    return "Stopping after current step..."

# Core Batch Processor (Dedicated TverKar Campaign)
async def execute_batch(
    phone_text: str,
    country_code: str,
    auto_send: bool = True,
    message_text: str = "",
    delay_s: float = 2.0,
    video_path: Optional[str] = None,
    survey_timeout: int = 180
):
    global STOP_SIGNAL
    STOP_SIGNAL = False
    
    lines = [line.strip() for line in phone_text.splitlines() if line.strip() and not line.strip().startswith("#")]
    total = len(lines)
    if total == 0:
        yield get_empty_df(), "Error: No valid phone numbers provided.", render_kpi_html(0, 0, 0, 0, 0)
        return

    try:
        yield get_empty_df(), "Connecting to Telegram MTProto...", render_kpi_html(total, 0, 0, 0, 0)
        is_auth = await service.is_authenticated()
        if not is_auth:
            yield get_empty_df(), "Error: Telegram account is NOT logged in. Go to Settings tab to login first.", render_kpi_html(total, 0, 0, 0, 0)
            return
    except Exception as e:
        yield get_empty_df(), f"Connection Error: {str(e)}", render_kpi_html(total, 0, 0, 0, 0)
        return

    # Cache Video Asset
    cached_media = None
    if auto_send and video_path and os.path.exists(video_path):
        try:
            yield get_empty_df(), f"Uploading & caching video '{video_path}' to Telegram...", render_kpi_html(total, 0, 0, 0, 0)
            cached_media = await service.upload_and_cache_video(video_path)
        except Exception:
            pass

    rows = []
    for i, raw in enumerate(lines, 1):
        e164 = format_phone_e164(raw, default_region=country_code)
        rows.append({
            "#": i,
            "Phone (E.164)": e164,
            "Candidate": "-",
            "Consent": "Queued",
            "Employment": "-",
            "Urgency / Change": "-",
            "Expected Salary": "-",
            "Location": "-",
            "Status": "Pending" if auto_send else "Queued"
        })

    df = pd.DataFrame(rows)
    tverkar_campaign_results = []
    if os.path.exists(config.tverkar_results_csv):
        try:
            existing_df = pd.read_csv(config.tverkar_results_csv, encoding="utf-8-sig")
            tverkar_campaign_results = existing_df.to_dict(orient="records")
        except Exception:
            tverkar_campaign_results = []
    stats = {"registered": 0, "delivered": 0, "privacy_blocked": 0, "unregistered": 0, "failed": 0, "survey_done": 0}
    
    action_label = "Running TverKar Outreach & Survey" if auto_send else "Checking registrations"
    yield df, f"Starting {action_label} for {total} target numbers (Delay: {delay_s}s)...", render_kpi_html(total, 0, 0, 0, 0)

    for idx, raw in enumerate(lines):
        if STOP_SIGNAL:
            yield df, f"Halted by user at #{idx}/{total}.", render_kpi_html(total, stats["registered"], stats["delivered"], stats["privacy_blocked"], stats["unregistered"])
            return

        e164 = format_phone_e164(raw, default_region=country_code)
        df.at[idx, "Status"] = "Checking..."
        try:
            is_reg, info, user_entity = await service.check_phone_registration(e164, cleanup_contact=False)
            if is_reg and info:
                stats["registered"] += 1
                full_n = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
                uname = f"@{info.get('username')}" if info.get('username') else ""
                recipient_str = full_n or uname or f"User ID: {info['id']}"
                
                df.at[idx, "Candidate"] = recipient_str

                if auto_send:
                    df.at[idx, "Status"] = "Sending & Surveying..."
                    final_msg = service.format_message_template(message_text, user_info=info)

                    yield df, f"Engaging TverKar campaign with {recipient_str}...", render_kpi_html(total, stats["registered"], stats["delivered"], stats["privacy_blocked"], stats["unregistered"])
                    
                    survey_ok, answers, survey_reason = await service.conduct_tverkar_campaign_session(
                        user_entity,
                        initial_message=final_msg,
                        media=cached_media,
                        timeout=int(survey_timeout or 180),
                        phone_identifier=e164,
                        user_info=info
                    )

                    stats["delivered"] += 1
                    df.at[idx, "Consent"] = answers.get("consent", "Agreed" if survey_ok else "Declined")
                    df.at[idx, "Employment"] = answers.get("employment_status", "-")
                    df.at[idx, "Urgency / Change"] = answers.get("job_preference", "-")
                    df.at[idx, "Expected Salary"] = answers.get("expected_salary", "-")
                    df.at[idx, "Location"] = answers.get("preferred_location", "-")
                    
                    if survey_ok:
                        stats["survey_done"] += 1
                        df.at[idx, "Status"] = "Completed"
                    else:
                        df.at[idx, "Status"] = f"Incomplete ({survey_reason})"

                    tverkar_campaign_results.append({
                        "Index": idx + 1,
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Phone (E.164)": e164,
                        "Raw Phone": raw,
                        "Candidate Name": recipient_str,
                        "Username": uname,
                        "User ID": info.get("id"),
                        "Consent Transfer": answers.get("consent", ""),
                        "Employment Status": answers.get("employment_status", ""),
                        "Job Preference / Urgency": answers.get("job_preference", ""),
                        "Expected Salary": answers.get("expected_salary", ""),
                        "Preferred Location": answers.get("preferred_location", ""),
                        "Voice Notes": "; ".join(answers.get("voice_files", [])),
                        "Dialogue Summary": " | ".join(answers.get("raw_dialogue", [])),
                        "Campaign Status": "Completed" if survey_ok else "Incomplete",
                        "Notes": survey_reason
                    })
                    
                    # Persist CSV in real-time
                    try:
                        tver_df = pd.DataFrame(tverkar_campaign_results)
                        tver_df.to_csv(config.tverkar_results_csv, index=False, encoding="utf-8-sig")
                    except Exception:
                        pass
                    
                    await service.delete_contact(info["id"])
            else:
                stats["unregistered"] += 1
                df.at[idx, "Candidate"] = "-"
                df.at[idx, "Consent"] = "-"
                df.at[idx, "Employment"] = "-"
                df.at[idx, "Urgency / Change"] = "-"
                df.at[idx, "Expected Salary"] = "-"
                df.at[idx, "Location"] = "-"
                df.at[idx, "Status"] = "Unregistered"
        except errors.FloodWaitError as e:
            df.at[idx, "Status"] = f"FloodWait: {e.seconds}s"
            break
        except Exception as e:
            df.at[idx, "Status"] = f"Error: {str(e)}"
            
        yield df, f"Completed [{idx + 1}/{total}]", render_kpi_html(total, stats["registered"], stats["delivered"], stats["privacy_blocked"], stats["unregistered"])
        if idx < total - 1 and delay_s > 0 and auto_send:
            await asyncio.sleep(delay_s)

    summary = f"🎉 Campaign Finished! Registered: {stats['registered']} | Delivered: {stats['delivered']}"
    yield df, summary, render_kpi_html(total, stats["registered"], stats["delivered"], stats["privacy_blocked"], stats["unregistered"])

# Async Handlers
async def on_start_autosend(phone_text, country, msg, delay_val, video_p, timeout_val):
    async for item in execute_batch(phone_text, country, True, msg, delay_val, video_path=video_p, survey_timeout=timeout_val):
        yield item

async def on_start_verify_only(phone_text, country, msg, delay_val):
    async for item in execute_batch(phone_text, country, False, "", 0):
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
            return f"Registered: {name} ({uname}) · ID: {info['id']} · Activity: {info['status']}"
        return f"Not Registered / Private: {e164}"
    except Exception as e:
        return f"Error: {e}"

async def on_single_send(phone_str, msg, country, video_path=""):
    if not phone_str:
        return "Phone number is required."
    e164 = format_phone_e164(phone_str, default_region=country)
    try:
        await service.connect()
        is_reg, info, entity = await service.check_phone_registration(e164, cleanup_contact=False)
        if not is_reg or not entity:
            return f"❌ Cannot send: {e164} is not registered on Telegram."
        
        final_msg = service.format_message_template(msg or "", user_info=info)

        if video_path and os.path.exists(video_path.strip()):
            cached_media = await service.upload_and_cache_video(video_path.strip())
            ok, status_type, res = await service.send_media_to_user(entity, cached_media, caption=final_msg)
        else:
            ok, status_type, res = await service.send_message_to_user(entity, final_msg)

        await service.delete_contact(info["id"])
        if ok:
            media_tag = " (with Video)" if (video_path and os.path.exists(video_path.strip())) else ""
            return f"✅ Sent successfully{media_tag}! (Message ID: {res}) to {info.get('first_name', '')} ({e164})"
        elif status_type == "PRIVACY_RESTRICTED":
            return f"⚠️ Cannot Send: Recipient privacy settings block stranger messages/media."
        return f"❌ Failed ({status_type}): {res}"
    except Exception as e:
        return f"❌ Send Error: {e}"


# Tab 3 Login Handlers
async def on_request_code(api_id, api_hash, phone):
    if not api_id or not api_hash or not phone:
        return "Please fill in API ID, API Hash, and Phone Number.", await check_header_status()
    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"TELEGRAM_API_ID={str(api_id).strip()}\n")
        f.write(f"TELEGRAM_API_HASH={str(api_hash).strip()}\n")
        f.write(f"TELEGRAM_PHONE={str(phone).strip()}\n")
        f.write("DEFAULT_COUNTRY=KH\nMIN_DELAY_SECONDS=2\nMAX_DELAY_SECONDS=2\n")
    service.reload_env()
    service.client = None
    ok, msg = await service.send_auth_code(phone)
    status_text = f"{msg}" if ok else f"Error: {msg}"
    return status_text, await check_header_status()

async def on_verify_login(code, pwd):
    if not code:
        return "Please enter the verification code.", await check_header_status()
    ok, msg, needs_pwd = await service.sign_in_with_code(code, pwd)
    badge = await check_header_status()
    if ok:
        return f"{msg}", badge
    elif needs_pwd:
        return f"{msg}", badge
    return f"Error: {msg}", badge

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
                            <div class="app-subtitle">Direct Phone-to-Phone Lead Outreach, Video Sender & Survey Suite</div>
                        </div>
                    </div>
                    """
                )
            with gr.Column(scale=2):
                header_status = gr.HTML(
                    """
                    <div class="status-pill">
                        <span>Checking sender phone...</span>
                    </div>
                    """
                )

        with gr.Tabs():
            # Main Tab: Dedicated TverKar Campaign
            with gr.Tab("🚀 TverKar Outreach & Survey Campaign"):
                kpi_box = gr.HTML(render_kpi_html(19, 0, 0, 0, 0))

                with gr.Row():
                    # Left Column: Target Numbers & Message Settings
                    with gr.Column(scale=4):
                        with gr.Group():
                            with gr.Row():
                                batch_country = gr.Dropdown(
                                    label="Region", 
                                    choices=["KH", "US", "TH", "VN", "SG", "MY"], 
                                    value="KH",
                                    scale=1
                                )
                                reload_btn = gr.Button("🔄 Load Numbers List", size="sm", scale=1)

                            phone_input = gr.Textbox(
                                label="Target Phone Numbers", 
                                value=get_default_phone_list(), 
                                lines=5,
                                placeholder="Paste phone numbers (one per line)..."
                            )

                        with gr.Group():
                            video_input = gr.Textbox(
                                label="🎬 1-Tap Video Asset (2.69 MB Compressed)",
                                value=config.default_video_path,
                                placeholder="video/TverKar&WN_using.mp4"
                            )
                            msg_input = gr.Textbox(
                                label="Outreach Message Caption (Supports [ឈ្មោះបេក្ខជន])", 
                                value=DEFAULT_OUTREACH_MESSAGE, 
                                lines=7
                            )

                        with gr.Row():
                            delay_input = gr.Number(
                                label="Anti-Flood Delay (s)", 
                                value=2, 
                                precision=0, 
                                minimum=0,
                                scale=1
                            )
                            timeout_box = gr.Number(
                                label="Candidate Reply Timeout (s)", 
                                value=180, 
                                precision=0, 
                                minimum=10,
                                scale=1
                            )

                        with gr.Row():
                            send_btn = gr.Button("🚀 Start Outreach Campaign", variant="primary", scale=2)
                            verify_btn = gr.Button("Verify Numbers Only", variant="secondary", scale=1)
                            stop_btn = gr.Button("Stop", variant="stop", scale=1)

                    # Right Column: Clean Live Data Table
                    with gr.Column(scale=6):
                        status_ticker = gr.Markdown("**Status**: Ready to launch TverKar Outreach Campaign.")
                        table_output = gr.Dataframe(
                            value=get_empty_df(),
                            headers=["#", "Phone (E.164)", "Candidate", "Consent", "Employment", "Urgency / Change", "Expected Salary", "Location", "Status"],
                            datatype=["number", "str", "str", "str", "str", "str", "str", "str", "str"],
                            interactive=False,
                            wrap=True
                        )

                # Event Bindings for Main Tab
                reload_btn.click(fn=get_default_phone_list, outputs=[phone_input])
                
                send_btn.click(
                    fn=on_start_autosend,
                    inputs=[
                        phone_input, batch_country, msg_input, delay_input,
                        video_input, timeout_box
                    ],
                    outputs=[table_output, status_ticker, kpi_box]
                )

                verify_btn.click(
                    fn=on_start_verify_only,
                    inputs=[phone_input, batch_country, msg_input, delay_input],
                    outputs=[table_output, status_ticker, kpi_box]
                )

                stop_btn.click(fn=set_stop, outputs=[status_ticker])

            # Tab 2: TverKar Candidate Responses Viewer
            with gr.Tab("📊 Candidate Survey Responses"):
                gr.Markdown("### 🎯 TverKar CV Transfer Responses (`tverkar_campaign_results.csv`)")
                with gr.Row():
                    refresh_tverkar_btn = gr.Button("🔄 Refresh Results Table", variant="primary")
                tverkar_table = gr.Dataframe(
                    value=get_tverkar_df(),
                    interactive=False,
                    wrap=True
                )
                refresh_tverkar_btn.click(fn=get_tverkar_df, outputs=[tverkar_table])

            # Tab 3: Single Lookup & Test Send
            with gr.Tab("🔍 Single Lookup & Direct Send"):
                with gr.Row():
                    with gr.Column():
                        s_phone = gr.Textbox(label="Phone Number to Test", value="0968271451")
                        s_country = gr.Dropdown(label="Country", choices=["KH", "US", "TH", "VN"], value="KH")
                        s_check_btn = gr.Button("Check Registration", variant="primary")
                        s_result = gr.Markdown()
                    
                    with gr.Column():
                        s_video = gr.Textbox(
                            label="🎬 Video Path (Optional)",
                            value=config.default_video_path,
                            placeholder="e.g. video/TverKar&WN_using.mp4"
                        )
                        s_msg = gr.Textbox(label="Message / Video Caption", value=DEFAULT_OUTREACH_MESSAGE, lines=5)
                        s_send_btn = gr.Button("🚀 Send Video & Text Now", variant="secondary")
                        s_send_res = gr.Markdown()

                s_check_btn.click(fn=on_single_lookup, inputs=[s_phone, s_country], outputs=[s_result])
                s_send_btn.click(fn=on_single_send, inputs=[s_phone, s_msg, s_country, s_video], outputs=[s_send_res])

            # Tab 4: Account & Session
            with gr.Tab("⚙️ Account & Login"):
                with gr.Row():
                    api_id = gr.Textbox(label="API ID", value=os.getenv("TELEGRAM_API_ID", ""))
                    api_hash = gr.Textbox(label="API Hash", value=os.getenv("TELEGRAM_API_HASH", ""), type="password")
                phone_num = gr.Textbox(label="Sender Phone", value=os.getenv("TELEGRAM_PHONE", "+855"))
                req_btn = gr.Button("Request Login Code")
                req_status = gr.Markdown()

                with gr.Row():
                    code_in = gr.Textbox(label="Verification Code")
                    pwd_in = gr.Textbox(label="2FA Password", type="password")
                login_btn = gr.Button("Authenticate Session")
                login_res = gr.Markdown()

                req_btn.click(fn=on_request_code, inputs=[api_id, api_hash, phone_num], outputs=[req_status, header_status])
                login_btn.click(fn=on_verify_login, inputs=[code_in, pwd_in], outputs=[login_res, header_status])

        demo.load(fn=check_header_status, outputs=[header_status])
    return demo

def main():
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

if __name__ == "__main__":
    main()
