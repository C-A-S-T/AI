
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from dotenv import dotenv_values

DOC_KEY = "DOC-543adbc0ebc09e5ce628"
BASE = Path(__file__).resolve().parent

# 1. 반드시 별도의 테스트 환경변수 파일에서 읽는다.
env_path = BASE / ".env.integration"

if not env_path.is_file():
    raise RuntimeError(".env.integration 파일이 없습니다.")

database_url = dotenv_values(env_path).get("CAST_AI_DATABASE_URL")

if not database_url:
    raise RuntimeError("테스트 DB 주소가 없습니다.")

# 2. 접속 전 DB 이름, 호스트, 포트를 검사한다.
parsed_url = urlparse(database_url)

if (
    parsed_url.hostname not in ("127.0.0.1", "localhost")
    or parsed_url.port != 15433
    or parsed_url.path != "/cast_integration_test"
):
    raise RuntimeError("허용되지 않은 DB 주소입니다.")

# 3. 테스트 문서 및 임베딩 파일을 읽는다.
parsed_file = BASE / "data" / "parsed" / f"{DOC_KEY}.json"
embedding_file = BASE / "data" / "embeddings" / f"{DOC_KEY}.json"

document = json.loads(parsed_file.read_text(encoding="utf-8"))
chunks = json.loads(embedding_file.read_text(encoding="utf-8"))

document_hash = document["file_hash_sha256"]

# 4. 테스트 데이터의 형식을 검증한다.
if not re.fullmatch(r"[0-9a-f]{64}", document_hash):
    raise RuntimeError("문서 해시 형식이 올바르지 않습니다.")

if len(chunks) != 31:
    raise RuntimeError("청크 개수가 31개가 아닙니다.")

for index, chunk in enumerate(chunks, start=1):
    if chunk["document_id"] != DOC_KEY:
        raise RuntimeError(f"청크 {index}: 문서 ID 불일치")

    if chunk["chunk_id"] != f"{DOC_KEY}-CHUNK-{index:04d}":
        raise RuntimeError(f"청크 {index}: 청크 ID 불일치")

    if (
        not isinstance(chunk["page_number"], int)
        or isinstance(chunk["page_number"], bool)
        or chunk["page_number"] <= 0
    ):
        raise RuntimeError(f"청크 {index}: 페이지 번호 오류")

    if not isinstance(chunk["content"], str) or not chunk["content"].strip():
        raise RuntimeError(f"청크 {index}: 내용이 비어 있습니다.")

# 5. 테스트 DB에 연결한다.
with psycopg.connect(database_url, connect_timeout=5) as conn:
    with conn.cursor() as cur:

        # 실제 연결된 DB를 다시 검증한다.
        cur.execute(
            "SELECT current_database(), inet_server_port()"
        )

        db_name, port = cur.fetchone()

        if db_name != "cast_integration_test" or port != 5432:
            raise RuntimeError("테스트 DB 연결 검증 실패")

        # 6. 동일한 문서가 이미 존재하는지 확인한다.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM ai.document
            WHERE content_hash = %s
            """,
            (document_hash,),
        )

        existing_count = cur.fetchone()[0]

        if existing_count > 0:
            raise RuntimeError(
                "테스트 문서가 이미 DB에 존재합니다. "
                "중복 적재를 방지하기 위해 실행을 중단합니다."
            )

        # 7. 문서 정보를 저장한다.
        cur.execute(
            """
            INSERT INTO ai.document (doc_title, content_hash)
            VALUES (%s, %s)
            RETURNING document_id
            """,
            (DOC_KEY, document_hash),
        )

        document_id = cur.fetchone()[0]

        # 8. 문서 청크 31개를 저장한다.
        for index, chunk in enumerate(chunks, start=1):
            cur.execute(
                """
                INSERT INTO ai.document_chunk
                    (
                        document_id,
                        chunk_index,
                        chunk_content,
                        page_start,
                        page_end
                    )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    document_id,
                    index,
                    chunk["content"],
                    chunk["page_number"],
                    chunk["page_number"],
                ),
            )

print(f"완료: 문서 1개, 청크 {len(chunks)}개 적재")
