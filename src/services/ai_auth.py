import os
import secrets

from fastapi import Header, HTTPException


def verify_ai_service_token(
    x_ai_service_token: str | None = Header(default=None),
) -> None:
    expected_token = os.getenv("CAST_AI_API_TOKEN")

    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="AI service token is not configured",
        )

    if not x_ai_service_token or not secrets.compare_digest(
        x_ai_service_token,
        expected_token,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid AI service token",
        )
