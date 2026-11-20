# C.A.S.T. Phase 4 — 정책 비교 결과 표시·검토 계층

> 구현 초안. **수정(diff) 승인 전까지 테스트하지 마세요.** 원본 PDF를 직접 확인하지 않았으며 모든 정책 판정은 `PENDING_REVIEW`입니다. Java 또는 DB 반영을 허용하지 않습니다.

## 1. 목표와 범위

사용자에게 전달된 **Phase 3 실제 실행 결과** (`SEMANTIC_ADJUDICATION_REVIEW_REQUIRED.json`, SHA-256 `65713d53c0b77906c6bb96998df1a1cdf5cce4185310df6bf81f05be2090b906`)를 변경하지 않고 읽어, 별도 화면 표시용 결과를 생성합니다.

- 기존 75개 비교 ID 및 최종 82개 검토 항목, 변경 유형·역할·변경 키를 그대로 유지
- `MAINTAINED`인데 한쪽 표시값이 비어 있는 **8개만**, 등록된 정제 공고의 한 문장/연속 인용을 표시용으로 사용
- 기존 REVIEWED의 필드나 Phase 3 JSON에 값을 주입하지 않음
- `ADDED_CANDIDATE` 13개의 이전 연도 `null`은 보존 (2025년에 없었다고 단정하지 않음)
- 복합 부모 `DOC_LEASE_ALTERNATIVES`, `SUSPENSION_EFFECT`를 기존 자식과 연결해 표시. 부모를 독립적인 변경 건수로 세지 않음
- Phase 3의 미해결 22개, 19개 대표 키, 57개 그룹을 그대로 보존
- 월세 이체증 임대인 성명·계좌번호 전체 표기 요건은 **추가 검토 후보**로만 보관. 신규 비교 항목에 포함하지 않음

## 2. 신규 파일 (5개만 추가)

| 경로 | 설명 |
|---|---|
| `src/policy_compare/review_projection.py` | 검증 및 표시용 데이터 투영(읽기 전용) |
| `src/policy_compare/review_projection_cli.py` | 오프라인 명시 실행 진입점 |
| `metadata/policy_semantic_reviews/seoul_youth_rent_2025_2026_phase4_review_notes.json` | 표시값 8개 allowlist, 미해결 22개, PDF 검토 우선순위, 복합 관계, 추가 후보 |
| `tests/test_policy_review_projection.py` | 임시 파일만 이용하는 단위 테스트 초안 (**아직 실행하지 않음**) |
| `docs/policy_compare_phase4.md` | 이 문서 |

기존 `cli.py`, `semantic_adjudication.py`, `supplemental_evidence.py`, REVIEWED 파일, Cleaned 파일, Phase 2·3 JSON은 **수정하지 않습니다**.

## 3. 입력과 출력

CLI 입력은 (1) Phase 3 실제 결과, (2) LF 형태의 Supplemental Evidence JSON, (3~4) 양쪽 Cleaned JSON, (5) Phase 4 리뷰 메타데이터입니다.

실행 인터페이스 **예시** (Phase 4 수정 diff 승인 및 테스트 실행 승인 후에만 실행):

```powershell
Set-Location "C:\Development\AI\CAST_AI"

$reviewRoot = Join-Path $env:LOCALAPPDATA "CAST_AI\policy_compare_reviews"
$previous = "data\cleaned\DOC-211f45df17b98569c5f1.json"
$current = "data\cleaned\DOC-543adbc0ebc09e5ce628.json"
$phase3 = Join-Path $reviewRoot "2026\seoul_youth_rent_2025_2026_SEMANTIC_ADJUDICATION_REVIEW_REQUIRED.json"
$evidence = "metadata\policy_semantic_reviews\seoul_youth_rent_2025_2026_supplemental_evidence.json"
$notes = "metadata\policy_semantic_reviews\seoul_youth_rent_2025_2026_phase4_review_notes.json"
$output = Join-Path $reviewRoot "2026\seoul_youth_rent_2025_2026_PRESENTATION_REVIEW_REQUIRED.json"

# 위 Cleaned 경로는 Phase 3 실제 테스트 스크립트에서 사용했던 경로입니다.
# REVIEWED JSON 또는 DRAFT JSON을 Cleaned 입력으로 지정하면 해시 검사가 실패합니다.

& ".\.venv\Scripts\python.exe" -B -m src.policy_compare.review_projection_cli `
    --phase3-result $phase3 `
    --supplemental-evidence $evidence `
    --previous-cleaned $previous `
    --current-cleaned $current `
    --review-notes $notes `
    --output $output `
    --offline
```

**중요:** 이 명령은 로컬 복사 후 Diff 승인과 별도 테스트 승인까지 완료된 다음에만 실행합니다.

출력 구조:

```text
schema_version: 1
artifact_type: POLICY_PRESENTATION_REVIEW_DRAFT
status: REVIEW_REQUIRED
java_import_ready: false
source_bindings:
  phase3_result_sha256
  supplemental_evidence_sha256
  cleaned_documents: [document_id, cleaned_sha256, ...]
comparisons[0]:
  comparisonMode: PRESENTATION_REVIEW
  reviewStatus: REVIEW_REQUIRED
  humanApproved: false
  displayItems: 82
    previous: {value, source_type, reviewed_fields, supplemental_quotes, source_cleaned_sha256, ...}
    current:  {value, source_type, reviewed_fields, supplemental_quotes, source_cleaned_sha256, ...}
  reviewGroups: 57
  summaryChangeKeys: 19
  compoundRelations: 2
  reviewTasks: 22
  pdfReviewTargets: 5
  additionalReviewCandidates: 1 (review-only; 82개에 추가되지 않음)
```

## 4. 표시값 보완 규칙

- 기존 `*_display_value`가 문자열이면 이를 그대로 사용 (`source_type=REVIEWED`)
- **고정된 8개 allowlist**에 속하고 `MAINTAINED`, 한쪽 값 `null`, 해당 연도 단일 Supplemental Evidence가 있는 경우: **정제 JSON에서 인용문을 정확히 확인하고 원문 그대로 출력** (`source_type=SUPPLEMENTAL_EVIDENCE`)
- 그 외의 `null`: `value=null`, `source_type=UNAVAILABLE`, `missing_reason` 명시
- 추가 근거가 여러 개일 때는 문자열을 임의로 결합하지 않고 `supplemental_quotes`에 개별 보관
- 기존 `reviewStatus`·`proposed_change_type`은 절대 수정하지 않음

## 5. 무결성 및 검토 상태

- Phase 3 JSON의 **바이트 SHA-256**을 실제 실행 파일 해시와 대조 (`65713d53...`)
- Supplemental Evidence JSON의 **바이트 SHA-256** 검사 (`7e10ff77b725c01e30a66bfa07447bbeec46e30aa9ca29937621b942982863ef`)
- registry에 저장된 2025·2026 Cleaned JSON의 SHA-256 검사 (`fe7dc7afb0c64886683e0eee96f6557c473edd367ceece5f93b8a5f41ba692b2`, `46972707cc2c7be0f414a8bbe3e30629ccaa31fc7868e34dda40c3c0a0f73be9`)
- 보충 근거 35개와 PDF 검토 추가 후보의 정제 공고 페이지/인용문 확인
- `pdf_visual_reviewed`는 모든 표시 결과에서 `false`; `CLEANED_TEXT_VERIFIED`가 PDF 육안 검토 완료를 의미하지 않음
- 모든 항목은 `PENDING_REVIEW`; 변경·신설 후보를 **실제 확정 정책 변화로 게시하지 않음**
- CLI는 네트워크, OpenAI API, Java 및 DB 접근 기능을 포함하지 않음
- 출력 경로가 이미 존재하면 **실패 후 중단**, 다른 입력 파일을 덮어쓰는 경로면 중단

## 6. 다음 승인 절차

1. **현재:** 새 5개 파일 작성, ZIP 및 정적 diff 제시 (테스트 실행 금지)
2. 로컬 저장소에 새 파일 5개만 복사, Git 상태·내용 해시 확인
3. 수정 diff 승인
4. 신규 단위 테스트와 기존 회귀 테스트 및 실제 오프라인 결과 생성 계획 승인
5. 승인 후에만 실제 테스트 실행; 실패 시 원본을 바꾸지 않고 로그 분석

## 7. PDF 확인을 특히 권장하는 항목

2025년 공고 p.1 월세 절사 예시, p.8 구간별 선정 비율 표, 2026년 공고 p.5 소득 표, p.9 구간별 비율 표, p.8 동의서 비동의 예외·이체증 전체 표기 규정을 우선 검토합니다.
