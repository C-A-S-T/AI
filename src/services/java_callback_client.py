"""Send AI research results to the Java backend."""

import os

import httpx


def send_java_callback(task_id: int, payload: dict) -> dict:
    """Send a result callback and return the Java receipt."""

    base_url = os.getenv(
        "CAST_BACKEND_BASE_URL",
        "http://127.0.0.1:8080",
    ).rstrip("/")

    token = os.getenv("CAST_AI_CALLBACK_TOKEN")

    if not token:
        raise RuntimeError(
            "CAST_AI_CALLBACK_TOKEN is not configured"
        )

    if task_id <= 0:
        raise ValueError("task_id must be positive")

    url = (
        f"{base_url}/internal/ai/"
        f"research-tasks/{task_id}/result"
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            url,
            json=payload,
            headers={
                "X-AI-Service-Token": token,
                "Content-Type": "application/json",
            },
        )

        response.raise_for_status()

        return response.json()
