# C.A.S.T. Phase 5 — 오프라인 정책 비교 검토·승인 조건 검사

## 1. 범위와 신뢰 경계

- 기존 Phase 3/4 코드, REVIEWED/Cleaned, 결과 JSON, DB를 **수정하지 않음**.
- 고정된 Phase 4 `PRESENTATION_REVIEW_REQUIRED.json`을 읽기 전용으로 참조하고 SHA-256으로 묶음.
- PDF의 바이트 해시를 확인하지만, **코드가 시각 검토를 자동 수행한 것으로 주장하지 않음**.
- 사람이 기록한 페이지 검토는 `reviewer_id`로 작성된 **자기진술(self-attestation)**. 인증·전자서명·원본 부재의 증명은 아님.
- 승인 이력의 해시 체인은 이벤트 내부 변경을 탐지하기 위한 보조수단이며, 별도의 신뢰할 수 있는 헤드 해시 보관 없이 로그 전체 재작성 공격을 막지 못함.
- 이번 버전의 결과는 **항상** `status=REVIEW_REQUIRED`, `humanApproved=false`, `java_import_ready=false`를 유지. Java/DB/게시 연동 없음.

## 2. 추가 파일

- `src/policy_compare/pdf_source_review.py`: PDF 바이트 무결성, HTTPS 출처, 페이지별 수동 확인 기록 검사
- `src/policy_compare/review_decision.py`: 82개 항목에 대한 상태·판정 이벤트와 연결 해시 검사
- `src/policy_compare/review_approval_gate.py`: 82개 검토·22개 미해결·19개 대표 키·5개 PDF 페이지 검토 상태 검사
- `src/policy_compare/review_approval_cli.py`: 순수 오프라인 검토 보고서 출력
- `metadata/policy_semantic_reviews/seoul_youth_rent_2025_2026_phase5_review_draft.json`: 모든 검토 미완료 초안
- `tests/test_policy_pdf_source_review.py`, `tests/test_policy_review_decision.py`, `tests/test_policy_review_approval_gate.py`: 신규 테스트 코드 (테스트 실행 승인 전 미실행)

## 3. PDF 검토 기록

PDF 바이트를 준비한 경우 원본 PDF 두 파일의 SHA-256을 `pdf_sources[].pdf_sha256`에 입력하고, 검토자가 확인한 공식 `https://...` 공고 배포 URL을 `source_url`에 기록한다. **변조된 PDF**는 바이트 해시 불일치로 거부된다.

`page_reviews[]` 기록 예시 (실제 육안 검토 완료 **후에만** 입력):

```json
{
  "page": 8,
  "status": "PDF_VISUALLY_CONFIRMED",
  "reviewer_id": "local:reviewer-1",
  "reviewed_at": "2026-11-17T13:00:00+09:00",
  "note": "구간별 선정 인원과 원문 표의 행·열을 육안 대조",
  "comparison_ids": ["TIER_DISTRIBUTION"]
}
```

원문과 상충하면 `status=SOURCE_DISCREPANCY`로 표시한다. 이 상태는 승인을 차단한다. 현재 초안에는 **원본 PDF·승인자·검토 시각이 없으므로 빈값**으로 남긴다.

`pdf_source_review.py`는 `%PDF-`/`%%EOF`와 실제 파일의 SHA-256만 확인한다. HTTPS 형식만 검증하며 실제 공식 기관의 도메인인지 자동 확인하지 않는다. 표·문단의 시각적 정확도나 원본 문서의 실제 페이지 수는 자동 검증하지 않는다. 해당 사항은 수동 검토 후 별도 인증이 필요하다.

## 4. 항목별 검토 기록

Phase 4 표시 항목은 82개이며, 기존 `proposed_change_type`은 불변이다. 별도 `review_events`에만 추가로 기록한다. 가능한 `status`는 `IN_REVIEW`, `NEEDS_CORRECTION`, `EVIDENCE_INSUFFICIENT`, `APPROVED`, `REJECTED`다. 이벤트가 없으면 모두 `PENDING_REVIEW`다.

`APPROVED` 기록에는 양쪽 근거가 있는 경우 각각 확인한 PDF 페이지와 `final_change_type`이 필요하다. 신설/폐지 후보는 해당 연도 PDF 전체에서 대응 규정의 부재를 확인했다는 별도 `absence_review` 진술이 필요하며, 이 주장을 코드가 자동 입증하지는 못한다.

```json
{
  "event_id": "EV-0001",
  "comparison_id": "RENT_CONVERSION_RATE",
  "status": "APPROVED",
  "final_change_type": "UPDATED",
  "reviewer_id": "local:reviewer-1",
  "reviewed_at": "2026-11-17T13:00:00+09:00",
  "decision_reason": "2025년과 2026년 공고의 환산율과 적용 기준일을 확인함",
  "previous_event_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "verified_pdf_pages": {"previous": [3], "current": [4]},
  "event_hash": "<서명 없는 이벤트 정규화 JSON의 SHA-256>"
}
```

`event_hash`는 `src.policy_compare.review_decision.event_hash({키:값 ...})`로 계산하되 `event_hash` 필드 자체를 계산에서 제외한다. 첫 이벤트의 이전 해시는 64자리 `0`, 다음 이벤트는 직전 `event_hash`를 참조한다. 이벤트 내용 수정 시 해시는 달라진다. **기록된 검토자 ID는 인증된 사용자 정보가 아니다.** 실제 승인 이벤트 입력은 별도 검토 단계에서 승인 후 진행한다.

## 5. 오프라인 CLI (검토용; 승인 후 실행)

```powershell
& ".\.venv\Scripts\python.exe" -B -m src.policy_compare.review_approval_cli `
  --phase4-result "$env:LOCALAPPDATA\CAST_AI\policy_compare_reviews\2026\seoul_youth_rent_2025_2026_PRESENTATION_REVIEW_REQUIRED.json" `
  --review-draft ".\metadata\policy_semantic_reviews\seoul_youth_rent_2025_2026_phase5_review_draft.json" `
  --output "$env:LOCALAPPDATA\CAST_AI\policy_compare_reviews\2026\seoul_youth_rent_2025_2026_POLICY_APPROVAL_GATE_REPORT.json" `
  --offline
```

PDF가 준비되고 SHA/공식 출처가 검토 초안에 기록된 후에만 `--previous-pdf`와 `--current-pdf`를 추가한다. PDF 없이 실행하면 게이트는 `PDF_NOT_AVAILABLE` 및 미승인 항목들을 차단 사유로 보고하지만 **명령 자체는 성공적으로 보고서를 생성**한다. 차단된 게이트 상태는 구현 실패가 아니다.

- 출력 파일이 이미 있으면 덮어쓰지 않는다.
- 입력 파일이 출력 대상과 겹치면 거부한다.
- 파일 입력 전후 SHA-256을 비교한다.
- API, HTTP 요청, Java/DB 접근이 없다.
- PDF 파일/공고 초안/Phase 4 결과를 수정하지 않는다.

## 6. 승인 범위

`eligible_for_authenticated_publication_review=true`가 되더라도, 이는 **인증된 최종 승인 단계의 검토 대상**으로 넘어갈 준비가 됐다는 의미일 뿐이다. Phase 5는 `humanApproved=true` 또는 `java_import_ready=true`를 내보내지 않는다. 인증된 검토자 권한, 실제 게재 승인, Java 데이터 계약은 별도 단계로 남긴다.

## 7. 다음 단계

1. 신규 파일 9개 로컬 적용 및 Diff 승인
2. 3개 신규 테스트 파일 + Phase 3/4 기존 59개 회귀 테스트 계획 별도 승인
3. 원본 PDF 2개 확보 후 해시·출처 연결 및 수동 시각 검토 승인
4. 미해결 22개와 대표 변경 후보 19개에 대한 실제 검토 시작
