import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))

def send_otp_email(to_email: str, otp: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Password Reset OTP"
    msg["From"] = SMTP_EMAIL
    msg["To"] = to_email

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: auto; padding: 32px; border-radius: 16px; background: #f8fafc; border: 1px solid #e2e8f0;">
        <h2 style="color: #0f172a; margin-bottom: 8px;">Password Reset</h2>
        <p style="color: #64748b; font-size: 14px;">Use the OTP below to reset your password. It expires in <strong>10 minutes</strong>.</p>
        <div style="margin: 32px 0; text-align: center;">
            <span style="font-size: 40px; font-weight: 900; letter-spacing: 12px; color: #0ea5e9;">{otp}</span>
        </div>
        <p style="color: #94a3b8; font-size: 12px;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        if SMTP_PORT == 465:
            # SSL
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        else:
            # TLS (port 587)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, to_email, msg.as_string())

        print(f"✅ OTP email sent to {to_email}")
    except Exception as e:
        print(f"❌ SMTP error: {str(e)}")
        raise e