"""Authenticated read-only preview of an existing policy comparison."""

from fastapi import APIRouter, Depends, HTTPException

from src.services.ai_auth import verify_ai_service_token
from src.services.policy_compare_preview import load_policy_compare_preview


router = APIRouter(
    prefix="/v1/policy-comparisons",
    tags=["policy-comparisons"],
    dependencies=[Depends(verify_ai_service_token)],
)


@router.get("/{policy_key}/preview")
def get_policy_compare_preview(policy_key: str) -> dict:
    try:
        return load_policy_compare_preview(policy_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown policy") from None
    except (OSError, ValueError, UnicodeError) as exc:
        # No internal paths or source content are returned on failure.
        raise HTTPException(
            status_code=503,
            detail="Policy comparison preview is unavailable",
        ) from exc
