"""Signup Service — validates and orchestrates user account creation."""

import re
import uuid
from typing import Optional, Any
from loguru import logger

from app.config.settings import Settings
from app.stores.auth_store import AuthStore
from app.core.exceptions import AppError
from app.schemas.auth import (
    SignupRequest,
    SignupSuccessResponse,
    SignupSuccessData,
    AuthenticatedUser,
    AuthenticationResult,
    ApiMeta,
    ApiFieldError,
)
from app.services.auth.password_service import PasswordService
from app.services.auth.token_service import TokenService


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
NO_CONTROL_CHARS = re.compile(r"^[^\x00-\x1F\x7F]*$")


class SignupError(AppError):
    """Base exception for signup flow errors."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: Optional[list[ApiFieldError]] = None,
    ):
        super().__init__(
            status_code=status_code,
            code=code,
            message=message,
            field_errors=field_errors or [],
        )


class SignupService:
    """Implements the core business logic for user registration."""

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

    def validate_and_register(
        self,
        request: SignupRequest,
        correlation_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> SignupSuccessResponse:
        """Validate signup request, persist user & credentials, and issue JWT."""
        field_errors: list[ApiFieldError] = []

        # 1. First & Last Name validation
        first_name = request.firstName.strip()
        last_name = request.lastName.strip()

        if not first_name:
            field_errors.append(ApiFieldError(field="firstName", code="REQUIRED", message="First name is required."))
        elif len(first_name) > 100:
            field_errors.append(ApiFieldError(field="firstName", code="MAX_LENGTH_EXCEEDED", message="First name must not exceed 100 characters."))
        elif not NO_CONTROL_CHARS.match(first_name):
            field_errors.append(ApiFieldError(field="firstName", code="INVALID_CHARACTERS", message="First name contains unsupported characters."))

        if not last_name:
            field_errors.append(ApiFieldError(field="lastName", code="REQUIRED", message="Last name is required."))
        elif len(last_name) > 100:
            field_errors.append(ApiFieldError(field="lastName", code="MAX_LENGTH_EXCEEDED", message="Last name must not exceed 100 characters."))
        elif not NO_CONTROL_CHARS.match(last_name):
            field_errors.append(ApiFieldError(field="lastName", code="INVALID_CHARACTERS", message="Last name contains unsupported characters."))

        # 2. Email validation
        bi_email = request.biEmail.strip().lower()
        if not bi_email:
            field_errors.append(ApiFieldError(field="biEmail", code="REQUIRED", message="BI email is required."))
        elif len(bi_email) > 320:
            field_errors.append(ApiFieldError(field="biEmail", code="MAX_LENGTH_EXCEEDED", message="Email must not exceed 320 characters."))
        elif not EMAIL_REGEX.match(bi_email):
            field_errors.append(ApiFieldError(field="biEmail", code="INVALID_EMAIL", message="Enter a valid BI email address."))

        # 3. Password validation
        password = request.password
        confirm_password = request.confirmPassword

        if not password:
            field_errors.append(ApiFieldError(field="password", code="REQUIRED", message="Password is required."))
        elif len(password) < 12:
            field_errors.append(ApiFieldError(field="password", code="MIN_LENGTH_NOT_MET", message="Password must contain at least 12 characters."))
        elif len(password) > 128:
            field_errors.append(ApiFieldError(field="password", code="MAX_LENGTH_EXCEEDED", message="Password must not exceed 128 characters."))
        elif bi_email and password.lower() == bi_email:
            field_errors.append(ApiFieldError(field="password", code="PASSWORD_EQUALS_EMAIL", message="Password must not be the same as your email address."))

        if not confirm_password:
            field_errors.append(ApiFieldError(field="confirmPassword", code="REQUIRED", message="Confirm your password."))
        elif password != confirm_password:
            field_errors.append(ApiFieldError(field="confirmPassword", code="PASSWORDS_DO_NOT_MATCH", message="Password and confirm password must match."))

        # 4. Secret Question validation
        secret_question_id = request.secretQuestionId.strip()
        if not secret_question_id:
            field_errors.append(ApiFieldError(field="secretQuestionId", code="REQUIRED", message="Select a valid secret question."))
        else:
            try:
                uuid.UUID(secret_question_id)
            except ValueError:
                field_errors.append(ApiFieldError(field="secretQuestionId", code="INVALID_UUID", message="Select a valid secret question."))

        # 5. Secret Answer validation
        secret_answer = request.secretAnswer.strip()
        if not secret_answer:
            field_errors.append(ApiFieldError(field="secretAnswer", code="REQUIRED", message="Secret answer is required."))
        elif len(secret_answer) < 2:
            field_errors.append(ApiFieldError(field="secretAnswer", code="MIN_LENGTH_NOT_MET", message="Secret answer must contain at least 2 characters."))
        elif len(secret_answer) > 255:
            field_errors.append(ApiFieldError(field="secretAnswer", code="MAX_LENGTH_EXCEEDED", message="Secret answer must not exceed 255 characters."))

        # If any basic field errors occurred, raise 422
        if field_errors:
            raise SignupError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="One or more fields are invalid.",
                field_errors=field_errors,
            )

        # 6. Verify Secret Question exists and is active
        question_rec = self.auth_store.get_secret_question_by_id(secret_question_id)
        if not question_rec or not question_rec.get("isActive"):
            raise SignupError(
                status_code=422,
                code="INVALID_SECRET_QUESTION",
                message="The selected secret question is no longer active. Please choose another question.",
                field_errors=[ApiFieldError(field="secretQuestionId", code="INACTIVE_QUESTION", message="Selected question is not active.")],
            )

        # 7. Check if Email already exists (case-insensitive)
        existing_user = self.auth_store.get_user_by_email(bi_email)
        if existing_user:
            self.auth_store.record_audit_event(
                event_type="IDENTITY",
                action="USER_SIGNUP",
                outcome="FAILURE",
                correlation_id=correlation_id,
                error_code="EMAIL_ALREADY_REGISTERED",
                details={"email": bi_email},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise SignupError(
                status_code=409,
                code="EMAIL_ALREADY_REGISTERED",
                message="An account with this BI email address already exists.",
                field_errors=[ApiFieldError(field="biEmail", code="DUPLICATE_EMAIL", message="An account with this email address already exists.")],
            )

        # 8. Load Default Role (REGULAR_USER)
        default_role = self.auth_store.get_default_role()
        if not default_role:
            logger.error("Default role REGULAR_USER not found or inactive in database.")
            raise SignupError(
                status_code=503,
                code="SIGNUP_CONFIGURATION_ERROR",
                message="Signup is temporarily unavailable due to a server configuration issue. Please try again later.",
            )

        role_id = default_role["roleId"]
        role_code = default_role["roleCode"]

        # 9. Hash credentials
        password_hash = self.password_service.hash_password(password)
        secret_answer_hash = self.password_service.hash_secret_answer(secret_answer)

        # 10. Atomic database transaction
        try:
            created_user = self.auth_store.create_user_with_security(
                first_name=first_name,
                last_name=last_name,
                bi_email=bi_email,
                role_id=role_id,
                password_hash=password_hash,
                secret_question_id=secret_question_id,
                secret_answer_hash=secret_answer_hash,
                correlation_id=correlation_id,
                ip_address=ip_address,
                user_agent=user_agent,
                status="ACTIVE",
            )
        except Exception as exc:
            logger.exception(f"Failed to create user record: {exc}")
            self.auth_store.record_audit_event(
                event_type="IDENTITY",
                action="USER_SIGNUP",
                outcome="FAILURE",
                correlation_id=correlation_id,
                error_code="DATABASE_ERROR",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise SignupError(
                status_code=500,
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected server error occurred while creating your account. Please try again.",
            )

        # 11. Generate JWT access token
        access_token, expires_in = self.token_service.create_access_token(
            user_id=created_user["userId"],
            bi_email=created_user["biEmail"],
            role=role_code,
        )

        return SignupSuccessResponse(
            success=True,
            message="User registered successfully.",
            data=SignupSuccessData(
                user=AuthenticatedUser(
                    userId=created_user["userId"],
                    firstName=created_user["firstName"],
                    lastName=created_user["lastName"],
                    biEmail=created_user["biEmail"],
                    role=role_code,
                    status=created_user["status"],
                    emailVerified=created_user["emailVerified"],
                ),
                authentication=AuthenticationResult(
                    accessToken=access_token,
                    tokenType="Bearer",
                    expiresIn=expires_in,
                ),
            ),
            meta=ApiMeta(correlationId=correlation_id),
        )
