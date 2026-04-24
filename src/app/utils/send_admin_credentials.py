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
PANEL_URL     = os.getenv("ADMIN_PANEL_URL", "https://admin-ppai.vercel.app/login")


def send_admin_credentials(to_email: str, full_name: str, password: str, role: str):
    role_label  = "Super Admin" if role == "super_admin" else "Admin"
    role_color  = "#7c3aed"    if role == "super_admin" else "#0ea5e9"
    role_bg     = "#f5f3ff"    if role == "super_admin" else "#f0f9ff"
    role_border = "#ddd6fe"    if role == "super_admin" else "#bae6fd"

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = "Welcome to the Admin Panel - Your Login Credentials"
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = to_email

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Admin Credentials</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; padding:0; background:#f1f5f9; }}
    img  {{ border:0; display:block; }}
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
    .card-body  {{ padding:40px; }}
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
      margin:0 0 28px;
      font-size:14px; color:#64748b; line-height:1.7;
    }}
    .divider {{
      height:1px; background:#f1f5f9;
      margin-bottom:24px; font-size:0;
    }}
    .footer-text {{
      margin:0;
      font-size:11px; color:#94a3b8; line-height:1.6;
    }}
    .bottom-note {{
      text-align:center; margin-top:20px;
      font-size:11px; color:#94a3b8;
    }}

    .badge {{
      display:inline-block;
      background:{role_bg};
      color:{role_color};
      border:1px solid {role_border};
      border-radius:999px;
      font-size:11px; font-weight:700;
      letter-spacing:1px; text-transform:uppercase;
      padding:5px 16px;
      margin-bottom:28px;
    }}

    .field {{
      background:#f8fafc;
      border:1px solid #e2e8f0;
      border-radius:12px;
      padding:14px 18px;
      margin-bottom:10px;
      width:100%;
    }}
    .field-pw {{
      border-left:4px solid {role_color};
      border-radius:0 12px 12px 0;
      margin-bottom:28px;
    }}
    .field-label {{
      margin:0 0 4px;
      font-size:10px; font-weight:600;
      text-transform:uppercase; letter-spacing:0.8px;
      color:#94a3b8;
    }}
    .field-value {{
      margin:0;
      font-size:15px; font-weight:600;
      color:#0f172a;
      font-family:'Courier New',Courier,monospace;
      word-break:break-all;
    }}
    .field-value-pw {{
      font-size:16px; font-weight:700;
      color:{role_color};
      letter-spacing:2px;
    }}

    .btn-wrap {{ text-align:center; margin-bottom:24px; }}
    .btn {{
      display:inline-block;
      background:linear-gradient(135deg,#0ea5e9,#7c3aed);
      color:#ffffff !important;
      font-size:14px; font-weight:700;
      text-decoration:none;
      border-radius:12px;
      padding:14px 36px;
      letter-spacing:0.3px;
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
      .wrapper     {{ padding:24px 12px !important; }}
      .card-body   {{ padding:28px 20px !important; }}
      .card-footer {{ padding:14px 20px !important; }}
      .heading     {{ font-size:20px !important; }}
      .btn         {{ padding:13px 24px !important; font-size:13px !important; display:block !important; text-align:center !important; }}
      .field       {{ padding:12px 14px !important; }}
      .field-value    {{ font-size:13px !important; }}
      .field-value-pw {{ font-size:14px !important; letter-spacing:1px !important; }}
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
        <span class="brand-name" style="margin-left:10px;">
          Admin<span>Panel</span>
        </span>
      </div>
    </div>

    <div class="card">
      <div class="card-accent">&nbsp;</div>

      <div class="card-body">
        <p class="label">Account Access</p>
        <h1 class="heading">Welcome, {full_name}</h1>
        <p class="subtext">
          Your admin account has been created. Use the credentials below
          to sign in and change your password on first login.
        </p>

        <div>
          <span class="badge">{role_label}</span>
        </div>

        <div class="divider">&nbsp;</div>

        <p class="label">Login Credentials</p>

        <div class="field">
          <p class="field-label">Email Address</p>
          <p class="field-value">{to_email}</p>
        </div>

        <div class="field field-pw">
          <p class="field-label">Temporary Password</p>
          <p class="field-value field-value-pw">{password}</p>
        </div>

        <div class="btn-wrap">
          <a href="{PANEL_URL}" class="btn">Sign in to Admin Panel</a>
        </div>

        <div class="warning">
          <p class="warning-title">Security Notice</p>
          <p class="warning-body">
            Change your password immediately after your first login.
            Keep these credentials confidential — do not share them with anyone.
          </p>
        </div>
      </div>

      <div class="card-footer">
        <p class="footer-text">
          This is an automated message. Please do not reply to this email.<br/>
          If you did not expect this, contact your system administrator.
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

        print(f"✅ Credentials email sent to {to_email}")
    except Exception as e:
        print(f"❌ SMTP error: {str(e)}")
        raise e