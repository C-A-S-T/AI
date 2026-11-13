
import json
from pathlib import Path

from src.retrieval.chunking import chunk_document


FIXTURE = Path(__file__).parent / "fixtures" / "sample_policy.json"


def load_document():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_chunk_count_and_page_numbers():
    chunks = chunk_document(load_document(), max_chars=500)

    assert len(chunks) == 4
    assert [chunk["page_number"] for chunk in chunks] == [1, 2, 3, 4]


def test_chunk_ids_are_unique():
    chunks = chunk_document(load_document(), max_chars=50)

    chunk_ids = [chunk["chunk_id"] for chunk in chunks]

    assert len(chunk_ids) == len(set(chunk_ids))


def test_long_sentences_are_preserved():
    chunks = chunk_document(load_document(), max_chars=50)

    contents = [chunk["content"] for chunk in chunks]

    assert any("무주택 청년입니다." in content for content in contents)
    assert any("2026년 3월 31일까지" in content for content in contents)


def test_document_id_is_preserved():
    chunks = chunk_document(load_document())

    assert all(
        chunk["document_id"] == "DOC-TEST-001"
        for chunk in chunks
    )


def test_invalid_max_chars():
    try:
        chunk_document(load_document(), max_chars=0)
    except ValueError:
        pass
    else:
        raise AssertionError("max_chars=0 must raise ValueError")
