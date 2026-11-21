"""Authenticated read-only policy comparison retrieval."""

from fastapi import APIRouter, Depends, HTTPException

from src.services.ai_auth import verify_ai_service_token
from src.services.policy_compare import load_policy_comparison


router = APIRouter(
    prefix="/v1/policy-comparisons",
    tags=["policy-comparisons"],
    dependencies=[Depends(verify_ai_service_token)],
)


@router.get("/{policy_key}")
@router.get("/{policy_key}/preview", include_in_schema=False)
def get_policy_comparison(policy_key: str) -> dict:
    try:
        return load_policy_comparison(policy_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown policy") from None
    except (OSError, ValueError, UnicodeError) as exc:
        # No internal paths or source content are returned on failure.
        raise HTTPException(
            status_code=503,
            detail="Policy comparison is unavailable",
        ) from exc
