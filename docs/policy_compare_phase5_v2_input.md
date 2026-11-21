# Phase 5 v2 — 오프라인 검토 입력 도구 (D 작업)

> 상태: 신규 구현 초안, **테스트 실행 전**. 기존 Phase 5 v2 158개 회귀 테스트와 신규 테스트를 통과하기 전에는 실제 검토 기록을 작성하지 않습니다.
>
> 이 도구는 **오프라인 자기진술 검토 기록**만 저장합니다. PDF 원문을 자동으로 확인하거나 검토자를 인증하지 않습니다. 공식 원격 PDF 바이트 신뢰 검증, `humanApproved=true`, Java import 승인/실행 기능은 없습니다.

## 입력과 보안 경계

- 기준: `source_manifest.json`(20개 입력), `page_analysis.json`, Phase 3·4 고정 SHA-256, `phase5_v2_review_draft.json`.
- 기존 Draft, PDF, Parsed, Cleaned, REVIEWED, Phase 3·4·5 자료는 수정하지 않습니다.
- `load_review_context()`가 기준 입력 20개와 실제 PDF의 로컬 원문 계보를 확인한 후 CLI 기능을 수행합니다.
- 변경 가능한 입력은 **검토자가 직접 작성한** `actions` 배열뿐입니다. 검토자 ID·시간·사유·근거를 프로그램이 자동으로 채우지 않습니다.
- 이벤트 ID, 직전 해시, 이벤트 SHA-256, 고정 입력 바인딩은 프로그램이 자동 부여합니다.
- 검토 결과는 `%LOCALAPPDATA%\CAST_AI\policy_compare_reviews\v2\revisions\review_rev_0001.json` 등의 **새 파일**로만 저장합니다. 이전 revision은 변경하지 않습니다.
- 게이트는 항상 차단 사유를 평가하며, 독립적으로 인증된 공식 원격 파일 검증 없이는 오프라인 CLI에서 최종 승인·게시를 허용할 수 없습니다.

## Windows PowerShell 5.1 실행

아래 `$common`은 **테스트 승인 이후** 사용합니다. 먼저 승인된 diff와 테스트를 완료하세요.

```powershell
Set-Location "C:\Development\AI\CAST_AI"
$python = ".\.venv\Scripts\python.exe"
$common = @(
    '-B', '-m', 'src.policy_compare.review_v2_input_cli',
    '--offline',
    '--project-root', 'C:\Development\AI\CAST_AI',
    '--local-appdata-root', $env:LOCALAPPDATA
)

# 진행률과 차단 사유 (읽기 전용)
& $python @common status

# 미검토 대기열 30개 (읽기 전용)
& $python @common queue --limit 30

# 2026년 PDF 12페이지 원본 추출 텍스트와 검토 상태 (읽기 전용)
& $python @common show --type PDF_PAGE --id 'DOC-543adbc0ebc09e5ce628:12'

# 1개 정책 비교 항목의 근거와 정정 현황 (읽기 전용)
& $python @common show --type COMPARISON --id ANNUAL_PROCESS_TIMELINE

# 검토 이력 (읽기 전용)
& $python @common history
```

`show`의 PDF 텍스트는 **원본 PDF의 시각 검토를 대신하지 않습니다.** 사람은 로컬 PDF 원문을 열어 해당 페이지의 표·각주·적용 조건을 직접 확인한 뒤 검토 기록을 작성해야 합니다.

### 템플릿 만들기

```powershell
$template = Join-Path $env:USERPROFILE 'Downloads\cast_review_page12_template.json'
& $python @common template --type PDF_PAGE `
    --id 'DOC-543adbc0ebc09e5ce628:12' `
    --action PAGE_CONFIRMED --output $template
```

- 새 UTF-8 템플릿 파일을 **덮어쓰지 않고** 생성합니다.
- 검토자·시각·사유는 빈 문자열로 남으며, 이 템플릿은 아무런 검토 완료 사실도 주장하지 않습니다.
- `checked_topics`와 `source_references`에는 원문에서 직접 확인한 항목과 정확한 인용만 입력합니다.
- `reviewed_at`에는 시간대가 있는 ISO 8601 시각을 명시합니다(예: `2026-11-19T18:30:00+09:00`).
- 확인하지 않은 문서를 `PAGE_CONFIRMED`로 기록하지 마세요.

### 저장 전 미리 검사

작성한 템플릿 파일에는 `expected_draft_sha256`이 포함돼 있습니다. 이 해시가 현재 Draft/최신 revision과 다르면 `apply`는 거부합니다.

```powershell
& $python @common apply --actions-file $template --dry-run
```

**주의:** 템플릿을 생성한 상태 그대로 실행하면 검토자·시각·사유가 비어 있으므로 실패해야 정상입니다. 이는 의도된 보호 기능입니다.

### 새 revision에 저장

```powershell
& $python @common apply --actions-file $template
& $python @common status
```

한 번에 여러 이벤트를 기록하려면 동일한 요청 JSON의 `actions` 배열에 여러 개를 명시합니다. **하나라도 유효하지 않으면 어떤 이벤트도 저장하지 않습니다.** `--dry-run`은 파일을 저장하지 않습니다.

### 기록할 수 있는 이벤트

| 종류 | action | 주요 규칙 |
|---|---|---|
| PDF_PAGE | PAGE_CONFIRMED, PAGE_DISCREPANCY, PAGE_REOPENED | 원본 PDF SHA-256 확인, 집중 페이지는 `checked_topics` 필수 |
| FINDING | FINDING_RESOLVED, FINDING_REOPENED | 발견 페이지 확인, 해당 인용, 연결된 비교 ID 유지 |
| COMPARISON | COMPARISON_ACCEPTED, COMPARISON_REJECTED, COMPARISON_REOPENED, COMPARISON_NEEDS_MORE_EVIDENCE | 적용 조건과 근거 인용 검증 |
| COMPARISON | ABSENCE_REVIEWED | 문서 전체 페이지 확인 및 동등 규정 검색 근거 필요 |
| COMPARISON | CORRECTION_PROPOSED, CORRECTION_ACCEPTED, CORRECTION_REJECTED | 정정 ID 고유성, 근거와 검토 결정, 미처리 제안 차단 |
| ADDITIONAL_CANDIDATE | CANDIDATE_RESOLVED, CANDIDATE_REOPENED | 1개 후보의 결론 및 출처 인용 |

각 `action`은 `event_type`, `subject_id`, `action`, `reviewer_id`, `reviewed_at`, `reason`, `source_references`, `payload`를 포함합니다. 추가 필드나 사람이 임의 작성한 `event_hash`, `humanApproved`를 포함하면 거부합니다.

### 정정 미처리 및 페이지 재검토

- `CORRECTION_PROPOSED`를 만들고 채택·반려하지 않으면 게이트는 `CORRECTION_PENDING`을 유지합니다.
- `CORRECTION_ACCEPTED` 뒤에는 해당 제안을 적용한 비교 항목 결정을 별도로 기록해야 합니다.
- `CORRECTION_REJECTED`는 필수 `rejection_reason`을 요구합니다.
- 페이지가 `PAGE_REOPENED`되면 해당 PDF 근거, Phase 4 연결 페이지, 작업 B 발견 사항으로 연결된 판단을 미검토 상태로 돌립니다. 나중에 해당 페이지를 다시 확인하더라도 이전 판단은 자동 복원되지 않습니다.
- `PAGE_DISCREPANCY` 또한 원문과의 불일치가 확인된 상태이므로 후속 승인 준비가 차단됩니다.

### Revision 경쟁 상태와 복구

- 최초 저장은 `review_rev_0001.json`, 그다음 `review_rev_0002.json` 순서입니다.
- 최신 revision보다 이전 Draft를 입력하면 변경은 거부됩니다.
- 동시 저장 시 같은 이름의 파일을 기존 내용에 덮어쓰지 않도록 **독점적인 새 파일 생성**을 사용합니다.
- 저장 직전 원본 SHA-256과 최신 revision을 다시 확인합니다.
- 중간 저장 오류에서 기존 revision과 기준 자료는 보존됩니다.
- 승인 없이 `git clean`, `git reset`, 원본 JSON 수정 또는 revision 삭제를 하지 않습니다.

## 개발 완료 기준과 제한

- 신규 두 테스트 파일과 기존 158개 회귀 테스트 통과가 필요합니다(현재 미실행).
- 정적 구문 확인은 실행 테스트를 대신하지 않습니다.
- 이 도구는 검토 입력 편의성만 개선하며, 공식 첨부파일 원격 동일성 검증·검토자 인증·Java API 연동·최종 게시 승인은 향후 별도 작업입니다.
