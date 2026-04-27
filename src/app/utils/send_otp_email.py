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

        print(f"✅ OTP email sent to {to_email}")
    except Exception as e:
        print(f"❌ SMTP error: {str(e)}")
        raise e