"""Login and Session Management Service.

Implements credential verification, rate limiting, temporary account locking,
dummy Argon2id hash timing attack defense, refresh token rotation, token family reuse
detection, and audit persistence in accordance with login_page.md.
"""

import hashlib
import re
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from loguru import logger

from app.config.settings import Settings
from app.stores.auth_store import AuthStore
from app.services.auth.password_service import PasswordService
from app.services.auth.token_service import TokenService
from app.core.exceptions import AppError
from app.schemas.auth import (
    LoginRequest,
    LoginSuccessResponse,
    LoginSuccessData,
    LoginUser,
    AuthenticationResult,
    ApiMeta,
    ApiFieldError,
)


class LoginError(AppError):
    """Exception raised for domain-level login and session failures."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: Optional[list[ApiFieldError]] = None,
        retry_after: Optional[int] = None,
        clear_refresh_cookie: bool = False,
    ):
        super().__init__(
            status_code=status_code,
            code=code,
            message=message,
            field_errors=field_errors,
            retry_after=retry_after,
            clear_refresh_cookie=clear_refresh_cookie,
        )


EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


class LoginService:
    """Service handling credential verification, lockout, rate limiting, and session tokens."""

    # In-memory IP rate limiter tracking: {ip_str: [timestamp, ...]}
    _ip_attempts: dict[str, list[float]] = {}

    def __init__(
        self,
        settings: Settings,
        auth_store: AuthStore,
        password_service: Optional[PasswordService] = None,
        token_service: Optional[TokenService] = None,
    ):
        self.settings = settings
        self.auth_store = auth_store
        self.password_service = password_service or PasswordService()
        self.token_service = token_service or TokenService(settings)

        # Pre-computed dummy Argon2id hash for timing attack defense on unknown emails
        self._dummy_hash = self.password_service.hash_password("DummyTimingDefensePassword#1234")

    def _check_ip_rate_limit(self, ip_address: Optional[str]) -> None:
        """Enforce rate limits per IP address."""
        if not ip_address:
            return

        now = time.time()
        window_sec = self.settings.auth_ip_rate_limit_window_minutes * 60
        max_attempts = self.settings.auth_ip_rate_limit_max_attempts

        # Clean old attempts for this IP
        attempts = [t for t in self._ip_attempts.get(ip_address, []) if now - t < window_sec]
        if len(attempts) >= max_attempts:
            oldest_relevant = attempts[0]
            retry_after = max(1, int(window_sec - (now - oldest_relevant)))
            raise LoginError(
                status_code=429,
                code="RATE_LIMIT_EXCEEDED",
                message="Too many login attempts. Please try again later.",
                retry_after=retry_after,
            )

        attempts.append(now)
        self._ip_attempts[ip_address] = attempts

    @classmethod
    def reset_rate_limits(cls) -> None:
        """Utility for testing: reset IP rate limiter cache."""
        cls._ip_attempts.clear()

    def _validate_request(self, request: LoginRequest) -> tuple[str, list[ApiFieldError]]:
        """Validate email and password constraints."""
        field_errors: list[ApiFieldError] = []

        # Email validation
        raw_email = (request.biEmail or "").strip()
        normalized_email = raw_email.lower()

        if not raw_email:
            field_errors.append(
                ApiFieldError(field="biEmail", code="REQUIRED_FIELD", message="BI Email is required.")
            )
        elif len(normalized_email) > 320:
            field_errors.append(
                ApiFieldError(
                    field="biEmail",
                    code="EMAIL_TOO_LONG",
                    message="Email must not exceed 320 characters.",
                )
            )
        elif not EMAIL_REGEX.match(normalized_email):
            field_errors.append(
                ApiFieldError(
                    field="biEmail",
                    code="INVALID_EMAIL_FORMAT",
                    message="Please provide a valid company email address.",
                )
            )

        # Password validation
        if not request.password:
            field_errors.append(
                ApiFieldError(field="password", code="REQUIRED_FIELD", message="Password is required.")
            )
        elif len(request.password) > 128:
            field_errors.append(
                ApiFieldError(
                    field="password",
                    code="PASSWORD_TOO_LONG",
                    message="Password must not exceed 128 characters.",
                )
            )

        return normalized_email, field_errors

    def authenticate(
        self,
        request: LoginRequest,
        correlation_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict[str, Any]:
        """Authenticate user credentials and create an authenticated session."""
        # 1. Rate limiting by IP
        self._check_ip_rate_limit(ip_address)

        # 2. Validate request
        normalized_email, field_errors = self._validate_request(request)
        if field_errors:
            raise LoginError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="Invalid login request.",
                field_errors=field_errors,
            )

        # 3. Retrieve user & security record
        user_rec = self.auth_store.get_user_with_security_by_email(normalized_email)

        # 4. Unknown email safe handling (dummy hash verify + audit)
        if not user_rec:
            # Constant-time operation dummy verify
            self.password_service.verify_password(self._dummy_hash, request.password)
            self.auth_store.record_audit_event(
                event_type="AUTHENTICATION",
                action="LOGIN_FAILED",
                outcome="FAILURE",
                correlation_id=correlation_id,
                error_code="INVALID_CREDENTIALS",
                resource_type="USER",
                details={"reason": "UNKNOWN_EMAIL"},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise LoginError(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="The email address or password is incorrect.",
            )

        user_id = user_rec["userId"]

        # 5. Check account status
        if user_rec["status"] == "DISABLED":
            self.auth_store.record_audit_event(
                actor_user_id=user_id,
                event_type="AUTHENTICATION",
                action="LOGIN_FAILED",
                outcome="FAILURE",
                correlation_id=correlation_id,
                error_code="ACCOUNT_DISABLED",
                resource_type="USER",
                resource_id=user_id,
                details={"reason": "ACCOUNT_DISABLED"},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise LoginError(
                status_code=403,
                code="ACCOUNT_DISABLED",
                message="This account is disabled. Please contact your system administrator.",
            )

        if not user_rec["roleIsActive"]:
            self.auth_store.record_audit_event(
                actor_user_id=user_id,
                event_type="AUTHENTICATION",
                action="LOGIN_FAILED",
                outcome="FAILURE",
                correlation_id=correlation_id,
                error_code="ROLE_INACTIVE",
                resource_type="USER",
                resource_id=user_id,
                details={"reason": "ROLE_INACTIVE"},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise LoginError(
                status_code=403,
                code="ROLE_INACTIVE",
                message="Your account role is inactive. Please contact support.",
            )

        # 6. Check temporary lock status
        if user_rec["isLocked"]:
            lock_expires_at = user_rec.get("lockExpiresAt")
            if lock_expires_at:
                try:
                    exp_dt = datetime.fromisoformat(lock_expires_at)
                    now_dt = datetime.now(timezone.utc)
                    if now_dt >= exp_dt:
                        # Expired lock: clear atomically
                        self.auth_store.clear_expired_lock(user_id)
                    else:
                        # Lock is still active
                        self.auth_store.record_audit_event(
                            actor_user_id=user_id,
                            event_type="AUTHENTICATION",
                            action="LOGIN_FAILED",
                            outcome="FAILURE",
                            correlation_id=correlation_id,
                            error_code="ACCOUNT_LOCKED",
                            resource_type="USER",
                            resource_id=user_id,
                            details={"reason": "ACCOUNT_LOCKED", "lockExpiresAt": lock_expires_at},
                            ip_address=ip_address,
                            user_agent=user_agent,
                        )
                        raise LoginError(
                            status_code=423,
                            code="ACCOUNT_LOCKED",
                            message="This account is temporarily locked. Use password recovery or try again later.",
                        )
                except (ValueError, TypeError):
                    raise LoginError(
                        status_code=423,
                        code="ACCOUNT_LOCKED",
                        message="This account is temporarily locked. Use password recovery or try again later.",
                    )
            else:
                # Permanent or admin lock
                raise LoginError(
                    status_code=423,
                    code="ACCOUNT_LOCKED",
                    message="This account is temporarily locked. Use password recovery or try again later.",
                )

        # 7. Verify submitted password against Argon2id hash
        is_valid_pw = self.password_service.verify_password(
            user_rec["passwordHash"], request.password
        )

        if not is_valid_pw:
            # Increment failed attempts atomically
            lock_result = self.auth_store.record_failed_login(
                user_id=user_id,
                max_failed_attempts=self.settings.auth_max_failed_attempts,
                lock_minutes=self.settings.auth_lockout_duration_minutes,
            )

            self.auth_store.record_audit_event(
                actor_user_id=user_id,
                event_type="AUTHENTICATION",
                action="LOGIN_FAILED",
                outcome="FAILURE",
                correlation_id=correlation_id,
                error_code="INVALID_CREDENTIALS",
                resource_type="USER",
                resource_id=user_id,
                details={
                    "reason": "INVALID_PASSWORD",
                    "failedAttempts": lock_result["failedLoginAttempts"],
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

            if lock_result["newlyLocked"]:
                self.auth_store.record_audit_event(
                    actor_user_id=user_id,
                    event_type="AUTHENTICATION",
                    action="ACCOUNT_LOCKED",
                    outcome="SUCCESS",
                    correlation_id=correlation_id,
                    resource_type="USER",
                    resource_id=user_id,
                    details={
                        "lockReason": "FAILED_LOGIN_THRESHOLD",
                        "lockExpiresAt": lock_result["lockExpiresAt"],
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                raise LoginError(
                    status_code=423,
                    code="ACCOUNT_LOCKED",
                    message="This account is temporarily locked. Use password recovery or try again later.",
                )

            raise LoginError(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="The email address or password is incorrect.",
            )

        # 8. Success: Reset failed attempts & clear lock
        self.auth_store.reset_failed_attempts_and_update_login(user_id)

        # 9. Create session and tokens
        raw_refresh_token = secrets.token_urlsafe(32)
        refresh_token_hash = hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()
        session_id = str(uuid.uuid4())
        token_family_id = str(uuid.uuid4())

        expire_days = (
            self.settings.auth_remember_me_expire_days
            if request.rememberMe
            else self.settings.auth_refresh_token_expire_days
        )
        now_dt = datetime.now(timezone.utc)
        expires_at_dt = now_dt + timedelta(days=expire_days)
        expires_at_str = expires_at_dt.isoformat()
        cookie_max_age = expire_days * 86400

        self.auth_store.create_session(
            session_id=session_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            token_family_id=token_family_id,
            remember_me=request.rememberMe,
            expires_at=expires_at_str,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # 10. Audit event LOGIN_SUCCEEDED
        self.auth_store.record_audit_event(
            actor_user_id=user_id,
            event_type="AUTHENTICATION",
            action="LOGIN_SUCCEEDED",
            outcome="SUCCESS",
            correlation_id=correlation_id,
            resource_type="USER",
            resource_id=user_id,
            details={"sessionId": session_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # 11. Generate short-lived JWT access token
        access_token, expires_in = self.token_service.create_access_token(
            user_id=user_id,
            bi_email=user_rec["biEmail"],
            role=user_rec["role"],
            session_id=session_id,
        )

        response = LoginSuccessResponse(
            success=True,
            data=LoginSuccessData(
                user=LoginUser(
                    userId=user_id,
                    firstName=user_rec["firstName"],
                    lastName=user_rec["lastName"],
                    biEmail=user_rec["biEmail"],
                    role=user_rec["role"],
                ),
                authentication=AuthenticationResult(
                    accessToken=access_token,
                    tokenType="Bearer",
                    expiresIn=expires_in,
                ),
            ),
            meta=ApiMeta(correlationId=correlation_id),
        )

        return {
            "response": response,
            "raw_refresh_token": raw_refresh_token,
            "cookie_max_age": cookie_max_age,
        }

    def refresh_session(
        self,
        raw_refresh_token: Optional[str],
        correlation_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict[str, Any]:
        """Rotate the refresh token and issue a new access token."""
        if not raw_refresh_token:
            raise LoginError(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="Refresh token is missing.",
                clear_refresh_cookie=True,
            )

        token_hash = hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()
        session = self.auth_store.get_session_by_token_hash(token_hash)

        if not session:
            raise LoginError(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="Invalid refresh token session.",
                clear_refresh_cookie=True,
            )

        # Token reuse detection
        if session.get("revokedAt"):
            logger.warning(
                f"Refresh token reuse detected for session {session['sessionId']} (family {session['tokenFamilyId']})"
            )
            self.auth_store.revoke_token_family(
                session["tokenFamilyId"], reason="REUSE_DETECTED"
            )
            self.auth_store.record_audit_event(
                actor_user_id=session["userId"],
                event_type="AUTHENTICATION",
                action="REFRESH_TOKEN_REUSE_DETECTED",
                outcome="FAILURE",
                correlation_id=correlation_id,
                error_code="REUSE_DETECTED",
                resource_type="USER",
                resource_id=session["userId"],
                details={"compromisedFamily": session["tokenFamilyId"]},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise LoginError(
                status_code=401,
                code="SESSION_REVOKED",
                message="Session invalidation: token reuse detected. Please log in again.",
                clear_refresh_cookie=True,
            )

        # Check session expiry
        try:
            exp_dt = datetime.fromisoformat(session["expiresAt"])
            if datetime.now(timezone.utc) >= exp_dt:
                raise LoginError(
                    status_code=401,
                    code="SESSION_EXPIRED",
                    message="Your session has expired. Please log in again.",
                    clear_refresh_cookie=True,
                )
        except (ValueError, TypeError):
            raise LoginError(
                status_code=401,
                code="SESSION_EXPIRED",
                message="Your session has expired. Please log in again.",
                clear_refresh_cookie=True,
            )

        # Verify user & role status
        if session.get("userStatus") != "ACTIVE":
            raise LoginError(
                status_code=403,
                code="ACCOUNT_DISABLED",
                message="This account is disabled.",
                clear_refresh_cookie=True,
            )
        if not session.get("roleIsActive"):
            raise LoginError(
                status_code=403,
                code="ROLE_INACTIVE",
                message="Account role is inactive.",
                clear_refresh_cookie=True,
            )

        # Rotate session
        new_raw_refresh_token = secrets.token_urlsafe(32)
        new_token_hash = hashlib.sha256(new_raw_refresh_token.encode("utf-8")).hexdigest()
        new_session_id = str(uuid.uuid4())

        remember_me = bool(session.get("rememberMe"))
        expire_days = (
            self.settings.auth_remember_me_expire_days
            if remember_me
            else self.settings.auth_refresh_token_expire_days
        )
        new_expires_at = (datetime.now(timezone.utc) + timedelta(days=expire_days)).isoformat()
        cookie_max_age = expire_days * 86400

        self.auth_store.rotate_session(
            old_session_id=session["sessionId"],
            new_session_id=new_session_id,
            user_id=session["userId"],
            new_refresh_token_hash=new_token_hash,
            token_family_id=session["tokenFamilyId"],
            remember_me=remember_me,
            new_expires_at=new_expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Audit TOKEN_REFRESHED
        self.auth_store.record_audit_event(
            actor_user_id=session["userId"],
            event_type="AUTHENTICATION",
            action="TOKEN_REFRESHED",
            outcome="SUCCESS",
            correlation_id=correlation_id,
            resource_type="USER",
            resource_id=session["userId"],
            details={
                "oldSessionId": session["sessionId"],
                "newSessionId": new_session_id,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Issue new JWT
        access_token, expires_in = self.token_service.create_access_token(
            user_id=session["userId"],
            bi_email=session["biEmail"],
            role=session["role"],
            session_id=new_session_id,
        )

        response = LoginSuccessResponse(
            success=True,
            data=LoginSuccessData(
                user=LoginUser(
                    userId=session["userId"],
                    firstName=session["firstName"],
                    lastName=session["lastName"],
                    biEmail=session["biEmail"],
                    role=session["role"],
                ),
                authentication=AuthenticationResult(
                    accessToken=access_token,
                    tokenType="Bearer",
                    expiresIn=expires_in,
                ),
            ),
            meta=ApiMeta(correlationId=correlation_id),
        )

        return {
            "response": response,
            "raw_refresh_token": new_raw_refresh_token,
            "cookie_max_age": cookie_max_age,
        }

    def logout(
        self,
        session_id: Optional[str],
        user_id: Optional[str],
        correlation_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Revoke the current session and log the event."""
        if session_id:
            self.auth_store.revoke_session(
                session_id=session_id,
                user_id=user_id,
                reason="USER_LOGOUT",
            )

        if user_id:
            self.auth_store.record_audit_event(
                actor_user_id=user_id,
                event_type="AUTHENTICATION",
                action="LOGOUT",
                outcome="SUCCESS",
                correlation_id=correlation_id,
                resource_type="USER",
                resource_id=user_id,
                details={"sessionId": session_id} if session_id else {},
                ip_address=ip_address,
                user_agent=user_agent,
            )
