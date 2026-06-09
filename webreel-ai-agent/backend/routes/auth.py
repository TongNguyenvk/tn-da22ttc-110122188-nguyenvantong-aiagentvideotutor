"""
Authentication routes: register, login, Google Sign-In, profile.
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request, BackgroundTasks
from backend.middleware import limiter
from datetime import timedelta
import logging
import os

from backend.models.user import (
    UserCreate,
    UserLogin,
    GoogleAuthRequest,
    UserResponse,
    TokenResponse,
    UserInDB,
    RegisterResponse,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    ChangePasswordResponse
)
from backend.crud.users import (
    create_user,
    get_user_by_email,
    get_user_by_google_id,
    create_google_user,
    link_google_account,
    update_last_login,
    verify_email_token,
    generate_new_verification_token,
    save_password_reset_token,
    get_user_by_reset_token,
    reset_password_with_token,
    change_user_password,
    get_user_by_id
)
from backend.utils.email import send_verification_email, send_password_reset_email
from backend.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")


def _build_user_response(user: dict) -> UserResponse:
    """Build UserResponse from a user dict (shared helper)."""
    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        name=user["name"],
        auth_provider=user.get("auth_provider", "local"),
        avatar_url=user.get("avatar_url"),
        role=user.get("role", "user"),
        tier=user["tier"],
        status=user["status"],
        email_verified=user["email_verified"],
        quota=user["quota"],
        created_at=user["created_at"],
        last_login=user.get("last_login"),
    )


def _build_token_response(user: dict) -> TokenResponse:
    """Build TokenResponse with JWT for a user."""
    access_token = create_access_token(
        data={"sub": user["user_id"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(
        access_token=access_token,
        user=_build_user_response(user),
    )


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(user_data: UserCreate, background_tasks: BackgroundTasks):
    """
    Register a new user account and send verification email.
    """
    # Check if email already exists
    existing_user = await get_user_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Hash password
    password_hash = hash_password(user_data.password)
    
    # Create user
    user_dict = {
        "email": user_data.email,
        "name": user_data.name,
        "password_hash": password_hash,
        "auth_provider": "local",
        "tier": "free",
        "status": "pending_verification",
        "email_verified": False,
    }
    
    user = await create_user(user_dict)
    
    # Send verification email via background task
    background_tasks.add_task(
        send_verification_email,
        user["email"],
        user["name"],
        user["verification_token"]
    )
    
    logger.info(f"New user registered (pending verification): {user['email']} (user_id: {user['user_id']})")
    
    return RegisterResponse(
        message="Dang ky thanh cong. Vui long kiem tra email de xac thuc tai khoan.",
        email=user["email"]
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, credentials: UserLogin):
    """
    Login with email and password.
    
    Returns JWT access token valid for 7 days.
    """
    # Get user by email
    user = await get_user_by_email(credentials.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check if Google-only user (no password set)
    if user.get("auth_provider") == "google" and not user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tai khoan nay su dung Google Sign-In. Vui long dang nhap bang Google."
        )
    
    # Verify password
    if not user.get("password_hash") or not verify_password(
        credentials.password, user["password_hash"]
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check if account is suspended or pending verification
    if user.get("status") == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Contact support."
        )
        
    if user.get("status") == "pending_verification" or not user.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email chua duoc xac thuc. Vui long kiem tra email de xac thuc tai khoan."
        )
    
    # Update last login
    await update_last_login(user["user_id"])
    
    logger.info(f"User logged in: {user['email']}")
    
    return _build_token_response(user)


@router.post("/google", response_model=TokenResponse)
async def google_auth(request: GoogleAuthRequest):
    """
    Authenticate with Google ID Token.
    
    Flow:
    1. Verify Google ID Token via google.oauth2.id_token
    2. Extract email, name, picture, sub
    3. If google_id exists -> login (returning user)
    4. If email exists (local user) -> link Google account, auth_provider = "both"
    5. Else -> create new user, auth_provider = "google"
    """
    if not GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured on this server",
        )
    
    # Verify the Google ID Token
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        
        idinfo = google_id_token.verify_oauth2_token(
            request.credential,
            google_requests.Request(),
            GOOGLE_OAUTH_CLIENT_ID,
            clock_skew_in_seconds=60,
        )
    except ValueError as e:
        logger.warning(f"Google token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token",
        )
    
    # Extract user info from verified token
    google_id = idinfo["sub"]
    email = idinfo.get("email", "")
    name = idinfo.get("name", email.split("@")[0])
    avatar_url = idinfo.get("picture")
    email_verified = idinfo.get("email_verified", False)
    
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account does not have an email address",
        )
    
    # Case 1: Returning Google user (google_id already in DB)
    user = await get_user_by_google_id(google_id)
    if user:
        if user.get("status") == "suspended":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account suspended. Contact support.",
            )
        await update_last_login(user["user_id"])
        logger.info(f"Google user logged in: {email}")
        return _build_token_response(user)
    
    # Case 2: Email exists as local user -> link Google account
    existing_user = await get_user_by_email(email)
    if existing_user:
        if existing_user.get("status") == "suspended":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account suspended. Contact support.",
            )
        await link_google_account(existing_user["user_id"], google_id, avatar_url)
        await update_last_login(existing_user["user_id"])
        
        # Refresh user data after linking
        existing_user["auth_provider"] = "both"
        existing_user["google_id"] = google_id
        existing_user["email_verified"] = True
        if avatar_url:
            existing_user["avatar_url"] = avatar_url
        
        logger.info(f"Google account linked to local user: {email}")
        return _build_token_response(existing_user)
    
    # Case 3: Brand new user -> create with Google provider
    google_data = {
        "email": email,
        "name": name,
        "google_id": google_id,
        "avatar_url": avatar_url,
    }
    user = await create_google_user(google_data)
    
    logger.info(f"New Google user created: {email} (user_id: {user['user_id']})")
    return _build_token_response(user)


@router.get("/me", response_model=UserResponse)
async def get_profile(user: dict = Depends(get_current_user)):
    """
    Get current user profile.
    
    Requires: Authorization header with Bearer token
    """
    return _build_user_response(user)


@router.get("/verify-email/{token}")
async def verify_email(token: str):
    """Verify user's email via the token sent in the registration email."""
    success = await verify_email_token(token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token xac thuc khong hop le hoac da het han."
        )
    return {"message": "Xac thuc email thanh cong."}


@router.post("/resend-verification")
@limiter.limit("5/minute")
async def resend_verification(request: Request, body: ResendVerificationRequest, background_tasks: BackgroundTasks):
    """Resend verification email for an unverified account."""
    user = await get_user_by_email(body.email)
    
    # Generic message for security (prevent email enumeration)
    success_msg = {"message": "Neu email hop le, email xac thuc moi da duoc gui."}
    
    if not user:
        return success_msg
        
    if user.get("status") == "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tai khoan da duoc xac minh truoc do. Vui long dang nhap."
        )
        
    if user.get("status") == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tai khoan da bi khoa."
        )
        
    new_token = await generate_new_verification_token(body.email)
    if not new_token:
        return success_msg
        
    background_tasks.add_task(
        send_verification_email,
        user["email"],
        user["name"],
        new_token
    )
    
    logger.info(f"Verification email resent to {user['email']}")
    return success_msg


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest, background_tasks: BackgroundTasks):
    """
    Initiate password reset request.
    """
    user = await get_user_by_email(body.email)
    
    # Generic message for security (prevent email harvesting/enumeration)
    success_msg = {
        "message": "Nếu email hợp lệ và tồn tại, chúng tôi đã gửi hướng dẫn đặt lại mật khẩu đến email đó."
    }
    
    if not user:
        return success_msg
        
    # Check if Google-only user
    if user.get("auth_provider") == "google" and not user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tài khoản này đăng nhập bằng Google. Vui lòng sử dụng Google Sign-In."
        )
        
    if user.get("status") == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị khóa."
        )
        
    # Generate token
    import secrets
    from datetime import datetime, timezone, timedelta
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    
    # Save token to user document
    await save_password_reset_token(body.email, token, expires)
    
    # Send reset email
    background_tasks.add_task(
        send_password_reset_email,
        user["email"],
        user["name"],
        token
    )
    
    logger.info(f"Password reset initiated for: {user['email']}")
    return success_msg


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """
    Reset user password using token.
    """
    user = await get_user_by_reset_token(body.token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã đặt lại mật khẩu không hợp lệ hoặc đã hết hạn."
        )
        
    expires = user.get("reset_token_expires")
    if expires:
        from datetime import datetime, timezone
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mã đặt lại mật khẩu đã hết hạn."
            )
            
    # Hash password
    new_password_hash = hash_password(body.new_password)
    
    # Update password and clear token
    await reset_password_with_token(user["user_id"], new_password_hash)
    
    logger.info(f"Password reset successfully for user: {user['email']}")
    return {"message": "Đặt lại mật khẩu thành công. Vui lòng đăng nhập với mật khẩu mới."}


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(body: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    """
    Thay đổi hoặc thiết lập mật khẩu người dùng.
    """
    user_id = current_user["user_id"]
    has_password = current_user.get("password_hash") is not None
    set_both_provider = False

    if has_password:
        if not body.old_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mật khẩu cũ là bắt buộc."
            )
        # Verify old password
        if not verify_password(body.old_password, current_user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mật khẩu cũ không chính xác."
            )
        # Verify new password is different from current password
        if verify_password(body.new_password, current_user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mật khẩu mới phải khác mật khẩu cũ."
            )
    else:
        # User registered with Google and doesn't have local password yet
        if current_user.get("auth_provider") == "google":
            set_both_provider = True

    # Hash new password
    new_password_hash = hash_password(body.new_password)

    # Save to database
    success = await change_user_password(user_id, new_password_hash, set_both_provider)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật mật khẩu. Vui lòng thử lại sau."
        )

    # Get updated user info
    updated_user = await get_user_by_id(user_id)
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải thông tin người dùng đã cập nhật."
        )

    logger.info(f"Password changed/set successfully for user: {current_user['email']}")
    
    msg = "Thiết lập mật khẩu thành công." if not has_password else "Thay đổi mật khẩu thành công."
    return ChangePasswordResponse(
        message=msg,
        user=_build_user_response(updated_user)
    )



