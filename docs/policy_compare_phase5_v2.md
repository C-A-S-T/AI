# C.A.S.T. Phase 5 v2 — 오프라인 원문·판정 검토 계약

> 상태: **설계·구현 초안 / 미승인**. 본 문서는 정책 내용을 승인하지 않으며 사람 검토 이력을 대리 생성하지 않습니다.

## 1. 입력 기준선과 경계

- Source Manifest: `a916e643d17b56b24ebf21e3fa0c3ba27b0cab65fa889bfc2752efb15e2ef9f9`
- Task B `page_analysis.json`: `faa5970b4aa9bbf41cfdee0aad916a3dd806b61fd43ed7f94a3390bdfbb5d34e`
- Phase 3: `65713d53c0b77906c6bb96998df1a1cdf5cce4185310df6bf81f05be2090b906`
- Phase 4: `250363ecfec5934df1cb621034609b7a796a37e2add530506dbbe332dd8a61a3`

모든 입력은 읽기 전용이고, Phase 5 v1 파일은 그대로 둡니다. 새 계약은 기존 **82개** 비교 항목, **22개** 미해결 검토 작업(추가 후보 13·불확실 7·분할 필요 2), **57개** 검토 그룹, **19개** 기존 대표 키, **분할 부모 2개**, **별도 후보 1개**를 고정 식별자로 취급합니다. 기존 19개는 신규 검토 결과의 확정 변경 건수가 아닙니다.

PDF 검토 범위는 2025년 **10페이지**, 2026년 **13페이지**, 총 **23페이지**입니다. 이 중 Source Manifest가 지정하는 집중 검토 범위는 총 **10페이지**(2025 p.1·4·8·10 / 2026 p.5·8·9·10·12·13)입니다. Task B의 원문 구조화 손실 **8개 발견 사항**을 별도 해결해야 합니다.

## 2. 구현된 파일 및 책임

| 파일 | 기능 |
|---|---|
| `review_v2_contract.py` | 원본 해시와 v2 스키마·검토 범위 검증, 초기 Draft 재구성 |
| `review_v2_source.py` | PDF 페이지 및 Task B 발견 사항의 사람 검토 **자기진술** 검증 |
| `review_v2_decision.py` | 해시 연결 이벤트, 비교 항목 정정/반려/수용, 부재 검토, 별도 후보 이력 |
| `review_v2_gate.py` | 미검토·출처 불명·분할 오류·정정 미해결 등의 차단 이유 생성 |
| `review_v2_cli.py` | Source Manifest의 20개 실제 원본 검증 후 오프라인 보고서 독점 생성 |

초기 Draft는 `metadata/policy_review_runs/.../20261117_v1/phase5_v2_review_draft.json`이며, 실제 이벤트를 기록하기 전이므로 `events=[]`를 유지합니다. 변경 이력을 작성하려면 이 파일을 덮어쓰지 않고 별도 신규 개정 파일을 사용합니다.

## 3. 이벤트 필수 구조

```json
{
  "schema_version": 2,
  "event_id": "EV-000001",
  "event_type": "PDF_PAGE",
  "subject": {"type": "PDF_PAGE", "id": "DOC-211f45df17b98569c5f1:4"},
  "action": "PAGE_CONFIRMED",
  "reviewer_id": "OFFLINE_REVIEWER_SELF_ASSERTED",
  "reviewed_at": "2026-11-18T12:00:00+09:00",
  "reason": "실제 검토 이후에만 검토자가 작성한 구체적 설명",
  "source_references": [],
  "payload": {
    "pdf_sha256": "6288e029484140bff4e7a3a5de64691d8230f07b04bae47d7dbcb25300cd0df4",
    "checked_topics": ["표 행·열, 적용 대상과 예외"],
    "discrepancies": []
  },
  "source_bindings": {
    "source_manifest_sha256": "a916e643d17b56b24ebf21e3fa0c3ba27b0cab65fa889bfc2752efb15e2ef9f9",
    "page_analysis_sha256": "faa5970b4aa9bbf41cfdee0aad916a3dd806b61fd43ed7f94a3390bdfbb5d34e",
    "phase3_result_sha256": "65713d53c0b77906c6bb96998df1a1cdf5cce4185310df6bf81f05be2090b906",
    "phase4_result_sha256": "250363ecfec5934df1cb621034609b7a796a37e2add530506dbbe332dd8a61a3"
  },
  "previous_event_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "event_hash": "VALID_SHA256_OF_ALL_OTHER_EVENT_FIELDS"
}
```

위 예시는 **계약 형식**을 설명하기 위한 것으로 `event_hash`는 계산되지 않았고 유효한 검토 기록도 아닙니다. 실제 이벤트를 합성해 사람 검토로 제출하면 안 됩니다. `event_hash`는 `review_decision.event_hash()`의 JSON 정규화 해시로 계산해야 하며, 앞선 이벤트의 해시를 연결합니다. 원본 파일 이외에 헤드 해시를 독립 보관하거나 서명하지 않는 이상, 이 방식만으로 작성자 신원을 인증하거나 전체 이력 교체를 방지할 수 없습니다.

모든 이벤트는 `event_id`가 고유해야 하며, `reviewed_at`은 시간대 포함 ISO 8601이어야 합니다. 정확한 페이지·문서·인용이 기존 PDF/Parsed 텍스트에 존재해야 하고, 실제 검토자가 해당 페이지를 확인하기 전에는 `PAGE_CONFIRMED`를 기록해서는 안 됩니다.

### 3.1 PDF 페이지

- `PAGE_CONFIRMED`: `payload={pdf_sha256, checked_topics, discrepancies:[]}`. 집중 검토 페이지는 비어 있지 않은 `checked_topics`가 필수입니다.
- `PAGE_DISCREPANCY`: `discrepancies`에 원문·구조 또는 근거의 문제를 설명합니다.
- `PAGE_REOPENED`: `payload={}`. 기존 이벤트 삭제 없이 해당 페이지의 현재 상태를 미검토로 되돌립니다.

### 3.2 Task B 발견 사항

- `FINDING_RESOLVED`: `resolution`은 `CONFIRMED_ISSUE`, `PRESERVED_BY_OTHER_EVIDENCE`, `OUT_OF_SCOPE` 중 하나입니다.
- `CONFIRMED_ISSUE`는 `correction_ids`가 1개 이상 필요하며, 연결된 정정이 최종 비교 판단에 반영되어야 합니다.
- `FINDING_REOPENED`: `payload={}`. 원문 PDF 페이지의 검토 자체와 발견 사항의 해결을 혼동하지 않습니다.
- `affected_comparison_ids`는 Task B의 원래 배열과 정확히 같아야 합니다.

### 3.3 정책 비교 82개

- `CORRECTION_PROPOSED`: `correction_id`, `correction_type`, `proposed_change_type`, `previous_value`, `current_value`, `scope_note` 필수.
- `CORRECTION_ACCEPTED`: 동일 ID의 앞선 제안이 있어야 하며, 이를 **자기진술 채택** 상태로 기록합니다.
- `ABSENCE_REVIEWED`: 기존 연도에 대응 규정이 없는지 판단할 때 해당 문서 **전체 페이지**를 검토한 기록과 동등어 검토 키워드를 요구합니다. 문자열 검색만으로 부재를 자동 확정하지 않습니다.
- `COMPARISON_ACCEPTED`: `final_change_type`, `correction_id`(없으면 `null`), `absence_reviewed_document_id`(해당하지 않으면 `null`). 실제 양측 값이 있는 경우 관련 PDF 페이지의 자기진술 검토와 원문 인용이 필요합니다.
- `COMPARISON_REJECTED`: `rejection_reason_code`(`NOT_A_POLICY_CHANGE`/`DUPLICATE`/`INSUFFICIENT_SUPPORT`/`OUT_OF_SCOPE`). 반려 항목은 대표 변경 집계에서 제외합니다.
- `COMPARISON_REOPENED`, `COMPARISON_NEEDS_MORE_EVIDENCE`: 비최종 상태로 전환합니다.

변경 유형은 `MAINTAINED`, `UPDATED`, `ADDED`, `REMOVED`, `ANNUAL_SCHEDULE`, `WORDING_ONLY`, `REVIEW_ONLY_SPLIT`, `NO_CHANGE`를 허용합니다. `INCONCLUSIVE`는 정정 없이 최종 채택할 수 없고, `SPLIT_REQUIRED` 부모는 `REVIEW_ONLY_SPLIT`로만 처리하며 자식 항목의 검토를 확인합니다. 자동으로 82개 항목을 재작성하거나 새 비교 항목을 추가하지 않습니다.

### 3.4 추가 후보 1개

`CANDIDATE_RESOLVED`의 `resolution`은 `PROPOSE_NEW_ITEM`, `MERGE_EXISTING`, `REJECT`이고, `MERGE_EXISTING`일 때만 기존 `target_comparison_id`를 적습니다. `PROPOSE_NEW_ITEM`은 새로운 비교 항목 **추가 제안일 뿐** 새 83번째 항목을 생성하지 않습니다. `CANDIDATE_REOPENED`는 다시 미검토로 돌립니다.

## 4. 게이트 계약

초기 Draft에는 검토 이벤트가 하나도 없으므로 정상 게이트 결과는 `REVIEW_REQUIRED`이며, PDF 23페이지 미검토, 발견 사항 8개 미해결, 비교 항목 82개 미검토, 별도 후보 미처리, 공식 원격 PDF 바이트 미검증을 **차단 사유**로 출력합니다.

통과 자격에 필요한 조건은 PDF 23페이지 자기진술 검토, Task B 발견 사항 해결, 82개 항목 채택 또는 반려, 22개 미해결 검토 작업 처리, 분할 부모 2개와 자식 검토, 추가 후보 처리, 원격 공식 출처의 독립 검증입니다.

**중요:** 현재 CLI는 네트워크나 인증 시스템을 호출하지 않으며 `trusted_provenance_docs`를 전달하지 않습니다. 그러므로 자체 입력의 `REMOTE_MATCH_SELF_ATTESTED`만으로 출처 조건을 통과할 수 **없고**, 실제 오프라인 보고서의 `eligible_for_authenticated_publication_review`는 출처 검증이 연결되기 전까지 `false`여야 합니다. 합성 단위 테스트는 신뢰된 외부 검증기 입력을 **주입**해 전이 로직만 시험할 수 있지만, 그 자체가 공식 파일 검증이 되지는 않습니다.

게이트 출력의 `humanApproved=false`, `java_import_ready=false`, `java_db_import=NOT_EXECUTED`는 모든 경우에 고정됩니다. 정책 승인/Java 반영/DB 기록은 이 단계의 범위 밖입니다.

## 5. CLI (후속 실행 승인 필요)

```powershell
Set-Location 'C:\Development\AI\CAST_AI'
$python = '.\.venv\Scripts\python.exe'
$draft = 'metadata\policy_review_runs\seoul_youth_rent_2025_2026\20261117_v1\phase5_v2_review_draft.json'
$output = Join-Path $env:LOCALAPPDATA 'CAST_AI\policy_compare_reviews\v2\seoul_youth_rent_2025_2026_V2_REPORT.json'
& $python -B -m src.policy_compare.review_v2_cli `
    --offline --project-root (Get-Location).Path `
    --local-appdata-root $env:LOCALAPPDATA `
    --review-draft $draft --output $output
```

실행 전 **반드시 사용자 승인을 별도로 받아야 합니다**. 출력이 이미 있으면 덮어쓰기를 거부합니다. 결과 파일은 프로젝트 외부 Local AppData 지정 하위 폴더에 **독점 신규 생성**합니다. 실행에 앞서 Source Manifest의 20개 파일과 실제 PDF·Task B 계보·Phase 3·4 해시를 확인합니다. 인터넷 요청이나 유료 AI API 호출은 하지 않습니다.

## 6. 테스트/구현 절차

이번 패키지는 신규 파일 13개만 포함합니다. 작성 직후에는 Python AST/JSON 구문 및 해시·Diff를 **정적으로만** 확인합니다. `unittest`나 실제 CLI는 **별도 테스트 승인 후** 실행합니다.

1. 신규 5개 테스트 모듈 및 기존 121개 회귀 테스트 실행.
2. 실제 v2 초기 Draft에 대한 차단 결과 확인.
3. 합성 이벤트의 상태 전이·해시 변조·근거 위조 검출 확인.
4. 원본 PDF 2개 및 전체 입력 20개 무결성 비교.
5. 테스트 전후 Git 작업 트리 및 파일 SHA-256 비교.

위 검사가 성공해도 PDF 사람 검토·원격 공식 파일 바이트 검증·최종 정책 승인은 별도로 남습니다.
