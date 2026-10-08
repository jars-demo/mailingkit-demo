"""MailingKit inside a FastAPI application.

Run from the repository root:

    uv run --with fastapi --with uvicorn --with "pydantic[email]" \
        uvicorn app:app --app-dir examples/fastapi --reload

Then:

    curl -X POST localhost:8000/signup -H "content-type: application/json" \
         -d '{"name": "Ada", "email": "ada@example.com"}'

Emails are printed in the server terminal until you set MAILINGKIT_PROVIDER.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr

from mailingkit import MailingKit, MailingKitError, Template, ValidationError

BASE_URL = "http://localhost:8000"


@dataclass
class WelcomeEmail:
    name: str
    login_url: str


@dataclass
class PasswordResetEmail:
    email: str
    reset_url: str
    expires_minutes: int


WELCOME = Template("welcome", WelcomeEmail)
PASSWORD_RESET = Template("password-reset", PasswordResetEmail)

# One client for the whole application, configured from MAILINGKIT_* variables.
mail = MailingKit.from_env(
    templates=Path(__file__).parent / "templates",
    default_sender="Acme <no-reply@example.com>",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await mail.aclose()


app = FastAPI(title="MailingKit + FastAPI", lifespan=lifespan)


class SignupRequest(BaseModel):
    name: str
    email: EmailStr


class PasswordResetRequest(BaseModel):
    email: EmailStr


@app.post("/signup")
async def signup(body: SignupRequest) -> dict[str, str]:
    # ... create the user in your own database here ...
    try:
        result = await mail.send_template(
            WELCOME,
            WelcomeEmail(name=body.name, login_url=f"{BASE_URL}/login"),
            to=str(body.email),
            idempotency_key=f"welcome:{body.email}",
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MailingKitError as exc:
        # The account exists either way; log it and let the user ask for a resend.
        raise HTTPException(status_code=502, detail="Could not send the welcome email") from exc
    return {"status": "created", "email_id": result.id}


@app.post("/password-reset")
async def password_reset(body: PasswordResetRequest) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    # ... store a hash of the token against the user here ...
    await mail.send_template(
        PASSWORD_RESET,
        PasswordResetEmail(
            email=str(body.email),
            reset_url=f"{BASE_URL}/reset?token={token}",
            expires_minutes=30,
        ),
        to=str(body.email),
    )
    # Same answer whether or not the account exists, so the endpoint cannot be used to
    # discover which addresses are registered.
    return {"status": "If that account exists, a reset link is on its way."}
