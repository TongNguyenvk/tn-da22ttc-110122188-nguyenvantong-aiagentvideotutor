"""
Email utility for sending verification and password reset emails.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import logging
import asyncio

logger = logging.getLogger(__name__)

def send_email_sync(to_email: str, subject: str, html_content: str) -> bool:
    """Send an email using standard smtplib."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port_str = os.getenv("SMTP_PORT", "587")
    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        smtp_port = 587
        
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    
    if not smtp_user or not smtp_password:
        logger.warning("SMTP credentials not configured. Skipping email send.")
        return False
        
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"WebReel Team <{smtp_user}>"
    msg["To"] = to_email
    
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        # Connect using TLS
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False

async def send_email_async(to_email: str, subject: str, html_content: str) -> bool:
    """Send an email asynchronously by running in a thread pool."""
    return await asyncio.to_thread(send_email_sync, to_email, subject, html_content)

async def send_verification_email(email: str, name: str, token: str) -> bool:
    """Prepare and send email verification link."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    verify_link = f"{frontend_url}/verify-email?token={token}"
    
    # Log the verification URL to console for local development convenience
    logger.info(f"--- EMAIL VERIFICATION LINK FOR {email} ---")
    logger.info(f"Link: {verify_link}")
    logger.info("------------------------------------------")
    
    subject = "WebReel - Xác thực địa chỉ email của bạn"
    
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
      <h2 style="color: #6366f1; text-align: center;">Chào mừng bạn đến với WebReel!</h2>
      <p>Xin chào <strong>{name}</strong>,</p>
      <p>Cảm ơn bạn đã đăng ký tài khoản tại WebReel. Vui lòng nhấp vào nút dưới đây để xác thực địa chỉ email của bạn:</p>
      <div style="text-align: center; margin: 30px 0;">
        <a href="{verify_link}" style="background-color: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Xác thực Email</a>
      </div>
      <p style="font-size: 13px; color: #666;">Liên kết này có hiệu lực trong vòng 24 giờ. Nếu nút trên không hoạt động, bạn có thể sao chép và dán liên kết sau vào trình duyệt:</p>
      <p style="font-size: 13px; color: #6366f1; word-break: break-all;">{verify_link}</p>
      <hr style="border: none; border-top: 1px solid #eaeaea; margin: 20px 0;">
      <p style="font-size: 12px; color: #999; text-align: center;">Đây là email tự động, vui lòng không trả lời email này.</p>
    </div>
    """
    
    return await send_email_async(email, subject, html_content)


async def send_password_reset_email(email: str, name: str, token: str) -> bool:
    """Prepare and send password reset link."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    reset_link = f"{frontend_url}/reset-password?token={token}"
    
    # Log the verification URL to console for local development convenience
    logger.info(f"--- PASSWORD RESET LINK FOR {email} ---")
    logger.info(f"Link: {reset_link}")
    logger.info("------------------------------------------")
    
    subject = "WebReel - Yêu cầu đặt lại mật khẩu"
    
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
      <h2 style="color: #6366f1; text-align: center;">Yêu cầu đặt lại mật khẩu</h2>
      <p>Xin chào <strong>{name}</strong>,</p>
      <p>Chúng tôi đã nhận được yêu cầu đặt lại mật khẩu cho tài khoản WebReel của bạn. Vui lòng click vào nút dưới đây để tiến hành đặt lại mật khẩu:</p>
      <div style="text-align: center; margin: 30px 0;">
        <a href="{reset_link}" style="background-color: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Đặt lại mật khẩu</a>
      </div>
      <p style="font-size: 13px; color: #666;">Liên kết này có hiệu lực trong vòng 1 giờ. Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email.</p>
      <p style="font-size: 13px; color: #6366f1; word-break: break-all;">{reset_link}</p>
      <hr style="border: none; border-top: 1px solid #eaeaea; margin: 20px 0;">
      <p style="font-size: 12px; color: #999; text-align: center;">Đây là email tự động, vui lòng không trả lời email này.</p>
    </div>
    """
    
    return await send_email_async(email, subject, html_content)

