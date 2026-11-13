
import os

import psycopg
from dotenv import load_dotenv


# 프로젝트의 .env 파일에서 환경변수 불러오기
load_dotenv()


def get_ai_db_connection():
    """Connect to the C.A.S.T. PostgreSQL AI database."""

    database_url = os.getenv("CAST_AI_DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "CAST_AI_DATABASE_URL is not configured"
        )

    return psycopg.connect(
        database_url,
        options="-c search_path=ai",
        connect_timeout=5,
    )
