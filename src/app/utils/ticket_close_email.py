import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

SMTP_EMAIL    = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_HOST     = os.getenv("SMTP_HOST")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 465))


def _send(msg: MIMEMultipart, to_email: str):
    """Internal helper: sends the composed message via SMTP."""
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ SMTP error: {str(e)}")
        raise e


def send_otp_email(to_email: str, name: str, otp: str):
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = "Admin Panel – Your Password Reset OTP"
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = to_email

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Password Reset OTP</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; padding:0; background:#f1f5f9; }}
    a    {{ color:inherit; }}

    .wrapper {{
      width:100%;
      background:#f1f5f9;
      padding:48px 16px;
    }}
    .container {{
      width:100%;
      max-width:560px;
      margin:0 auto;
    }}

    .brand {{ text-align:center; margin-bottom:24px; }}
    .brand-inner {{
      display:inline-flex;
      align-items:center;
      gap:10px;
    }}
    .brand-icon {{
      width:40px; height:40px;
      border-radius:12px;
      background:linear-gradient(135deg,#0ea5e9,#7c3aed);
      display:inline-flex;
      align-items:center;
      justify-content:center;
      vertical-align:middle;
    }}
    .brand-box {{
      width:16px; height:16px;
      border:2.5px solid #fff;
      border-radius:3px;
      display:block;
    }}
    .brand-name {{
      font-size:17px; font-weight:700;
      color:#0f172a; letter-spacing:0.3px;
      vertical-align:middle;
      margin-left:10px;
    }}
    .brand-name span {{ color:#0ea5e9; }}

    .card {{
      background:#ffffff;
      border-radius:20px;
      overflow:hidden;
      box-shadow:0 4px 32px rgba(15,23,42,0.08);
    }}
    .card-accent {{
      height:5px;
      background:linear-gradient(90deg,#0ea5e9,#7c3aed);
      font-size:0; line-height:0;
    }}
    .card-body   {{ padding:40px; }}
    .card-footer {{
      background:#f8fafc;
      border-top:1px solid #f1f5f9;
      padding:16px 40px;
      text-align:center;
    }}

    .label {{
      margin:0 0 14px;
      font-size:10px; font-weight:700;
      letter-spacing:1.5px; text-transform:uppercase;
      color:#94a3b8;
    }}
    .heading {{
      margin:0 0 8px;
      font-size:24px; font-weight:700;
      color:#0f172a; line-height:1.3;
    }}
    .subtext {{
      margin:0 0 32px;
      font-size:14px; color:#64748b; line-height:1.7;
    }}
    .divider {{
      height:1px; background:#f1f5f9;
      margin-bottom:28px; font-size:0;
    }}
    .footer-text {{
      margin:0;
      font-size:11px; color:#94a3b8; line-height:1.6;
    }}
    .bottom-note {{
      text-align:center; margin-top:20px;
      font-size:11px; color:#94a3b8;
    }}

    .otp-wrap {{
      text-align:center;
      margin:0 0 32px;
    }}
    .otp-box {{
      display:inline-block;
      background:#f0f9ff;
      border:1px solid #bae6fd;
      border-radius:16px;
      padding:24px 40px;
    }}
    .otp-label {{
      margin:0 0 10px;
      font-size:10px; font-weight:700;
      letter-spacing:1.5px; text-transform:uppercase;
      color:#0ea5e9;
    }}
    .otp-code {{
      margin:0;
      font-size:44px; font-weight:900;
      letter-spacing:14px;
      color:#0369a1;
      font-family:'Courier New',Courier,monospace;
    }}
    .otp-expiry {{
      margin:10px 0 0;
      font-size:11px; color:#64748b;
    }}

    .warning {{
      background:#fffbeb;
      border:1px solid #fde68a;
      border-left:4px solid #f59e0b;
      border-radius:0 10px 10px 0;
      padding:14px 16px;
    }}
    .warning-title {{
      margin:0 0 3px;
      font-size:11px; font-weight:700;
      text-transform:uppercase; letter-spacing:0.8px;
      color:#92400e;
    }}
    .warning-body {{
      margin:0;
      font-size:13px; color:#78350f; line-height:1.6;
    }}

    @media only screen and (max-width:600px) {{
      .wrapper   {{ padding:24px 12px !important; }}
      .card-body {{ padding:28px 20px !important; }}
      .card-footer {{ padding:14px 20px !important; }}
      .heading   {{ font-size:20px !important; }}
      .otp-code  {{ font-size:32px !important; letter-spacing:8px !important; }}
      .otp-box   {{ padding:18px 24px !important; }}
    }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="container">

    <div class="brand">
      <div class="brand-inner">
        <div class="brand-icon">
          <span class="brand-box"></span>
        </div>
        <span class="brand-name">Admin<span>Panel</span></span>
      </div>
    </div>

    <div class="card">
      <div class="card-accent">&nbsp;</div>

      <div class="card-body">
        <p class="label">Password Reset</p>
        <h1 class="heading">Hi, {name} 👋</h1>
        <p class="subtext">
          We received a request to reset your admin account password.
          Use the one-time code below to continue. Do not share this code with anyone.
        </p>

        <div class="divider">&nbsp;</div>

        <div class="otp-wrap">
          <div class="otp-box">
            <p class="otp-label">Your OTP Code</p>
            <p class="otp-code">{otp}</p>
            <p class="otp-expiry">⏱ Expires in <strong>10 minutes</strong> &nbsp;·&nbsp; Single use only</p>
          </div>
        </div>

        <div class="warning">
          <p class="warning-title">Didn't request this?</p>
          <p class="warning-body">
            If you didn't request a password reset, you can safely ignore this email.
            Your password will remain unchanged.
          </p>
        </div>
      </div>

      <div class="card-footer">
        <p class="footer-text">
          This is an automated message. Please do not reply to this email.<br/>
          If you need help, contact your system administrator.
        </p>
      </div>
    </div>

    <p class="bottom-note">
      &copy; 2025 AdminPanel &mdash; All rights reserved.
    </p>

  </div>
</div>
</body>
</html>"""

    msg.attach(MIMEText(html, "html"))
    _send(msg, to_email)


def send_ticket_closed_email(
    to_email: str,
    name: str,
    ticket_id: str,
    subject: str,
    team_name: str = "Support",
):
    """
    Sends a rich, detailed email to the user when their support ticket is closed.
    """
    display_name = name or to_email.split("@")[0] or "there"
    display_subject = subject or "your recent inquiry"

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Support Ticket {ticket_id} Has Been Resolved ✓"
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = to_email

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Ticket Resolved</title>
  <style>
    * {{ box-sizing: border-box; margin:0; padding:0; }}
    body {{ background:#f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}

    .wrapper {{
      width:100%;
      background:#f1f5f9;
      padding:48px 16px;
    }}
    .container {{
      width:100%;
      max-width:580px;
      margin:0 auto;
    }}

    /* Brand */
    .brand {{
      text-align:center;
      margin-bottom:28px;
    }}
    .brand-icon {{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:44px; height:44px;
      border-radius:14px;
      background:linear-gradient(135deg,#0ea5e9,#7c3aed);
      vertical-align:middle;
      margin-right:10px;
    }}
    .brand-box {{
      width:18px; height:18px;
      border:2.5px solid #fff;
      border-radius:4px;
      display:block;
    }}
    .brand-name {{
      font-size:18px; font-weight:800;
      color:#0f172a; letter-spacing:0.2px;
      vertical-align:middle;
    }}
    .brand-name span {{ color:#0ea5e9; }}

    /* Card */
    .card {{
      background:#ffffff;
      border-radius:24px;
      overflow:hidden;
      box-shadow:0 4px 40px rgba(15,23,42,0.10);
    }}
    .card-hero {{
      background:linear-gradient(135deg,#052e16 0%,#14532d 50%,#166534 100%);
      padding:40px 40px 36px;
      text-align:center;
      position:relative;
    }}
    .hero-check {{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:72px; height:72px;
      border-radius:50%;
      background:rgba(255,255,255,0.12);
      border:2px solid rgba(255,255,255,0.20);
      margin-bottom:18px;
    }}
    .hero-check-inner {{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:52px; height:52px;
      border-radius:50%;
      background:#22c55e;
    }}
    .check-svg {{
      width:26px; height:26px;
    }}
    .hero-title {{
      font-size:26px; font-weight:800;
      color:#ffffff; margin-bottom:6px;
      letter-spacing:-0.3px;
    }}
    .hero-subtitle {{
      font-size:14px;
      color:rgba(255,255,255,0.70);
      line-height:1.5;
    }}
    .hero-badge {{
      display:inline-block;
      margin-top:16px;
      padding:6px 14px;
      border-radius:50px;
      background:rgba(34,197,94,0.20);
      border:1px solid rgba(34,197,94,0.35);
      font-size:11px; font-weight:700;
      letter-spacing:1.2px; text-transform:uppercase;
      color:#86efac;
    }}

    /* Body */
    .card-body {{
      padding:40px;
    }}
    .greeting {{
      font-size:16px; font-weight:700;
      color:#0f172a;
      margin-bottom:12px;
    }}
    .intro {{
      font-size:14px;
      color:#475569;
      line-height:1.75;
      margin-bottom:28px;
    }}

    /* Ticket info box */
    .ticket-box {{
      background:#f8fafc;
      border:1px solid #e2e8f0;
      border-radius:14px;
      overflow:hidden;
      margin-bottom:28px;
    }}
    .ticket-box-header {{
      background:linear-gradient(90deg,#f0f9ff,#faf5ff);
      border-bottom:1px solid #e2e8f0;
      padding:12px 18px;
      display:flex;
      align-items:center;
      justify-content:space-between;
    }}
    .ticket-box-title {{
      font-size:10px; font-weight:700;
      letter-spacing:1.5px; text-transform:uppercase;
      color:#64748b;
    }}
    .ticket-id-badge {{
      background:#0ea5e9;
      color:#fff;
      font-size:10px; font-weight:800;
      letter-spacing:0.5px;
      padding:3px 10px;
      border-radius:6px;
      font-family:'Courier New',Courier,monospace;
    }}
    .ticket-box-row {{
      display:flex;
      padding:13px 18px;
      border-bottom:1px solid #f1f5f9;
      align-items:flex-start;
    }}
    .ticket-box-row:last-child {{
      border-bottom:none;
    }}
    .row-label {{
      width:110px;
      flex-shrink:0;
      font-size:11px; font-weight:700;
      text-transform:uppercase; letter-spacing:0.8px;
      color:#94a3b8;
      padding-top:1px;
    }}
    .row-value {{
      flex:1;
      font-size:13px; font-weight:500;
      color:#1e293b;
      line-height:1.5;
    }}
    .status-resolved {{
      display:inline-flex;
      align-items:center;
      gap:5px;
      background:#dcfce7;
      color:#16a34a;
      font-size:11px; font-weight:700;
      padding:3px 10px;
      border-radius:20px;
      border:1px solid #bbf7d0;
    }}
    .dot-green {{
      width:6px; height:6px;
      border-radius:50%;
      background:#22c55e;
      display:inline-block;
    }}

    /* Divider */
    .divider {{
      height:1px;
      background:linear-gradient(90deg,transparent,#e2e8f0,transparent);
      margin:28px 0;
    }}

    /* What happened section */
    .section-title {{
      font-size:13px; font-weight:700;
      color:#0f172a;
      margin-bottom:14px;
      display:flex;
      align-items:center;
      gap:6px;
    }}
    .section-title::before {{
      content:'';
      display:inline-block;
      width:3px; height:16px;
      border-radius:2px;
      background:linear-gradient(180deg,#0ea5e9,#7c3aed);
      flex-shrink:0;
    }}
    .steps-list {{
      list-style:none;
      padding:0;
      margin:0 0 28px;
    }}
    .steps-list li {{
      display:flex;
      align-items:flex-start;
      gap:12px;
      padding:10px 0;
      border-bottom:1px dashed #f1f5f9;
      font-size:13px;
      color:#475569;
      line-height:1.6;
    }}
    .steps-list li:last-child {{
      border-bottom:none;
    }}
    .step-num {{
      width:22px; height:22px;
      border-radius:50%;
      background:linear-gradient(135deg,#0ea5e9,#7c3aed);
      color:#fff;
      font-size:10px; font-weight:800;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      flex-shrink:0;
      margin-top:1px;
    }}

    /* CTA */
    .cta-box {{
      background:linear-gradient(135deg,#eff6ff,#faf5ff);
      border:1px solid #dbeafe;
      border-radius:14px;
      padding:22px 24px;
      margin-bottom:28px;
    }}
    .cta-heading {{
      font-size:14px; font-weight:700;
      color:#1e40af;
      margin-bottom:6px;
    }}
    .cta-text {{
      font-size:13px;
      color:#3b82f6;
      line-height:1.6;
    }}

    /* Warning */
    .info-box {{
      background:#fffbeb;
      border:1px solid #fde68a;
      border-left:4px solid #f59e0b;
      border-radius:0 10px 10px 0;
      padding:14px 16px;
      margin-bottom:0;
    }}
    .info-title {{
      font-size:11px; font-weight:700;
      text-transform:uppercase; letter-spacing:0.8px;
      color:#92400e;
      margin-bottom:4px;
    }}
    .info-body {{
      font-size:13px; color:#78350f;
      line-height:1.6;
    }}

    /* Footer */
    .card-footer {{
      background:#f8fafc;
      border-top:1px solid #f1f5f9;
      padding:18px 40px;
      text-align:center;
    }}
    .footer-text {{
      font-size:11px; color:#94a3b8; line-height:1.7;
    }}
    .footer-text a {{
      color:#0ea5e9; text-decoration:none;
    }}

    .bottom-note {{
      text-align:center;
      margin-top:22px;
      font-size:11px; color:#94a3b8;
    }}

    @media only screen and (max-width:600px) {{
      .wrapper {{ padding:24px 12px !important; }}
      .card-hero {{ padding:28px 20px 24px !important; }}
      .card-body {{ padding:28px 20px !important; }}
      .card-footer {{ padding:14px 20px !important; }}
      .hero-title {{ font-size:20px !important; }}
      .ticket-box-row {{ flex-direction:column; gap:4px; }}
      .row-label {{ width:auto !important; }}
    }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="container">

    <!-- Brand -->
    <div class="brand">
      <div style="display:inline-flex;align-items:center;">
        <div class="brand-icon"><span class="brand-box"></span></div>
        <span class="brand-name" style="margin-left:10px;">ProblemPulse</span>
      </div>
    </div>

    <div class="card">

      <!-- Hero -->
      <div class="card-hero">
        <div class="hero-check">
          <div class="hero-check-inner">
            <svg class="check-svg" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </div>
        </div>
        <h1 class="hero-title">Ticket Resolved!</h1>
        <p class="hero-subtitle">Your support request has been successfully addressed<br/>by our {team_name} team.</p>
        <div class="hero-badge">&#10003;&nbsp; Closed &amp; Resolved</div>
      </div>

      <!-- Body -->
      <div class="card-body">

        <p class="greeting">Hi {display_name} 👋</p>
        <p class="intro">
          Great news — our support team has reviewed your ticket and marked it as
          <strong style="color:#16a34a;">resolved</strong>. We hope your issue has been
          fully addressed. Below is a summary of your closed ticket for your records.
        </p>

        <!-- Ticket Info Box -->
        <div class="ticket-box">
          <div class="ticket-box-header">
            <span class="ticket-box-title">Ticket Summary</span>
            <span class="ticket-id-badge">{ticket_id}</span>
          </div>
          <div class="ticket-box-row">
            <span class="row-label">Subject</span>
            <span class="row-value">{display_subject}</span>
          </div>
          <div class="ticket-box-row">
            <span class="row-label">Handled By</span>
            <span class="row-value">{team_name} Team</span>
          </div>
          <div class="ticket-box-row">
            <span class="row-label">Status</span>
            <span class="row-value">
              <span class="status-resolved">
                <span class="dot-green"></span>
                Resolved &amp; Closed
              </span>
            </span>
          </div>
        </div>

        <!-- What happens next -->
        <div class="section-title">What happens next?</div>
        <ul class="steps-list">
          <li>
            <span class="step-num">1</span>
            <span>This ticket is now <strong>closed</strong>. You won't be able to reply to it anymore.</span>
          </li>
          <li>
            <span class="step-num">2</span>
            <span>If your issue <strong>persists</strong> or you have a <strong>new problem</strong>, you can raise a fresh support ticket at any time from your account.</span>
          </li>
          <li>
            <span class="step-num">3</span>
            <span>Your ticket history is always available for reference in your support portal.</span>
          </li>
        </ul>

        <!-- CTA -->
        <div class="cta-box">
          <p class="cta-heading">&#128276; Still having issues?</p>
          <p class="cta-text">
            If your problem wasn't fully resolved, please open a new ticket from the support
            section and our team will be happy to assist you again — no need to wait!
          </p>
        </div>

        <!-- Note -->
        <div class="info-box">
          <p class="info-title">Please Note</p>
          <p class="info-body">
            Do not reply to this email. This is an automated notification sent when your
            ticket status changes. To get further help, please use the in-app support portal
            to create a new ticket.
          </p>
        </div>

      </div>

      <!-- Footer -->
      <div class="card-footer">
        <p class="footer-text">
          This message was sent to <strong>{to_email}</strong> because you have an active account.<br/>
          &copy; 2026 ProblemPulseAi &mdash; All rights reserved.
        </p>
      </div>

    </div>

    <p class="bottom-note">
      Need help? Open a new ticket from your account dashboard.
    </p>

  </div>
</div>
</body>
</html>"""

    msg.attach(MIMEText(html, "html"))
    _send(msg, to_email)