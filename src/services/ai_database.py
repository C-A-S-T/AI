import os

import psycopg


def get_ai_db_connection():
    database_url = os.getenv("CAST_AI_DATABASE_URL")

    if not database_url:
        raise RuntimeError("CAST_AI_DATABASE_URL is not configured")

    return psycopg.connect(
        database_url,
        options="-c search_path=ai",
        connect_timeout=5,
    )
