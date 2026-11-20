# C.A.S.T. 정책 비교 Stage C — 읽기 전용 정정 제안 연결

> **상태:** Stage C 기존 구현은 2026-11-20에 통합 회귀 테스트 **142/142 PASS** 및 보호 파일 97개 SHA-256 불변을 확인했다. **이번 상태 진단 개선 배치의 신규·변경 테스트는 아직 실행하지 않았다.** 이 모듈은 원본 정책 정정·승인이나 검토자 인증이 아닌 **검토 준비 진단** 기능이다.

## 1. 범위 및 고정 조건

- 정책: 2025·2026 서울시 청년월세지원.
- AI 정정 제안: `metadata/policy_review_runs/seoul_youth_rent_2025_2026/20261120_correction_v1/correction_proposals.json`.
- 대상 15건: **P0 13건**(유지 제안 2, 수정 제안 6, 분해 제안 2, 근거 부족 3) 및 **연계 2건**.
- Phase 4: 비교 항목 82개, 그룹 57개, 기존 검토 작업 22개, 추가 후보 1개.
- 초기 상태: 검토 revision 0개·이벤트 0개이며 PDF 23페이지, 비교 82개, 작업 B 발견 8개는 별도 사람 확인 대상이다.
- 입력: 기존 `review_correction_proposal.load_proposal()`와 `review_v2_input.load_review_context()`를 재사용한다. 전자는 Manifest의 등록 입력 20개와 원본 PDF 인용을 로컬에서 검증하고, 후자는 최신 오프라인 review revision의 바인딩과 게이트를 검증한다.
- 원본 PDF, Parsed, Cleaned, REVIEWED, Phase 3/4/5, 초기 Draft, JSON 제안 파일은 **절대 수정하지 않는다**.

## 2. 이번 신규 파일

| 파일 | 역할 |
|---|---|
| `src/policy_compare/review_v2_proposal_bridge.py` | 로컬 승인 전 분석 자료 15건과 최신 검토 상태를 결합하는 읽기 전용 모듈·CLI |
| `tests/test_policy_review_v2_proposal_bridge.py` | 연결·무결성·차단 조건·실제 로더 무변경 확인용 unittest (작성만, 미실행) |
| `docs/policy_compare_stage_c.md` | 범위·안전한 실행 절차·신뢰 경계 기록 |

이 외 기존 Python 모듈, 메타데이터 또는 revision에 대한 변경은 계획하지 않는다.

## 3. 출력 항목과 검토 의미

- **기준 정보:** `comparison_id`, `bucket`, Phase 4의 `label`, `baseline_change_type`, 현재 검토 상태.
- **AI 제안:** `disposition`, `recommended_change_type`, 기존 원문에 대한 설명·범위·미해결 질문.
- **근거:** 2025·2026 문서 ID·원본 PDF SHA-256·페이지·인용, 해당 페이지의 현재 *자기진술* 검토 상태.
- **연결:** 원래 `change_group_id`, `change_key`, `summary_role`, 부모/자식, 같은 변경 키 항목 및 기타 관련 항목.
- **현재 결정:** 최신 revision의 `current_review_status`, `current_final_change_type`, 연결된 정정 이력.
- **진단:** `requirements`는 **현재 남아 있는** 검토 요구사항이며, `original_review_flags`는 **AI 제안 당시** 필요했던 분할·근거 보완·부재 검토의 이력을 보존한다. 최종 판정이나 자동 처리 지시가 아니다.
- `--summary`는 현재 요구사항별 `requirement_counts`와 과거 AI 우려사항별 `original_review_flag_counts`를 별도로 제공한다.

| 진단 코드 | 의미 |
|---|---|
| `SOURCE_REVIEW_REQUIRED` | 인용 PDF 페이지가 현재 확인된 상태로 기록되지 않음 |
| `ADDITIONAL_EVIDENCE_REQUIRED` | 제안서가 근거 부족으로 분류했고, 최신 v2 검토에서도 아직 `REVIEW_ACCEPTED`가 아닌 항목 |
| `SPLIT_REVIEW_REQUIRED` | 분해 부모 또는 기존 자식들의 수용 판정이 미완료 |
| `ABSENCE_REVIEW_REQUIRED` | 최종 `ADDED`·`REMOVED` 판단을 위해 필요한 부재 검토가 없거나 아직 검토가 미완료. 단, **채택된 정정에 따라 `NO_CHANGE`로 수용된 항목에는 요구하지 않음** |
| `PENDING_HUMAN_REVIEW` | 해당 비교 항목이 `REVIEW_ACCEPTED`가 아님. `REVIEW_REJECTED`도 미완료 |
| `NEW_ITEM_NOT_IMPLEMENTED` | 추가 후보의 신규 비교 항목 생성이 미구현 상태이며 별도 후보 진단에 표시됨 |

**진단과 원본 AI 이력의 차이:** `INCONCLUSIVE`였던 항목이 이후 유효한 정정 및 `COMPARISON_ACCEPTED`로 해결되면 `ADDITIONAL_EVIDENCE_REQUIRED`는 현재 요구사항에서 빠진다. 단 `original_review_flags`에서는 삭제하지 않는다. 한쪽 연도 신규 후보도 실제 검토를 거쳐 최종 `NO_CHANGE`로 수용되면 부재 검토가 요구되지 않는다. 기존 Phase 5 v2 이벤트 재생은 양 연도 근거와 채택된 `CHANGE_TYPE_CORRECTION`을 이미 검증한다. 이 연결 모듈은 이러한 사실을 **검토 없이 스스로 만들어 내거나 승인하지 않는다**. 원본 인용 페이지 미확인·게이트 차단은 별도로 유지한다.

추가 후보가 `PROPOSE_NEW_ITEM`에 따라 `NEW_ITEM_PENDING`이면 별도 `additional_candidates`에 표시하고 기존 게이트의 `ADDITIONAL_NEW_ITEM_NOT_IMPLEMENTED` 차단을 유지한다. 신규 Phase 4 비교 항목이나 `comparison_id`는 생성하지 않는다.

`ADDED_CANDIDATE`는 최종 `ADDED`가 아니고, `RETAIN_PROPOSAL`은 최종 `MAINTAINED`가 아니다. 근거 부족 항목의 `INCONCLUSIVE`는 유지한다. `RENT_CONVERSION_FORMULA`와 `TIER_DISTRIBUTION`은 연계 검토 항목이지 신규 변경 건수로 집계하지 않는다. 각 항목의 기존 `summary_role` 및 `change_key`를 보존하며 새로운 변경 집계는 수행하지 않는다.

## 4. Windows PowerShell 5.1 조회 예시

**테스트와 Diff 검토 승인 이후** 프로젝트 `.venv`에서 실행한다.

```powershell
Set-Location "C:\Development\AI\CAST_AI"
$python = ".\.venv\Scripts\python.exe"
$common = @(
    '-B', '-m', 'src.policy_compare.review_v2_proposal_bridge',
    '--offline',
    '--project-root', 'C:\Development\AI\CAST_AI',
    '--local-appdata-root', $env:LOCALAPPDATA
)

# 15건 검토 준비 요약. 콘솔 출력만 수행한다.
& $python @common --summary

# 15건 전체의 인용·연계·미해결 질문을 출력한다.
& $python @common --all

# 개별 비교 항목 1건의 상세 검토 정보.
& $python @common --id 'ONE_PERSON_INCOME_THRESHOLDS'
```

위 명령은 `status`, `summary`, `items` 등의 **진단 JSON만 stdout으로 출력**한다. `--all`은 실제 인용문을 포함할 수 있으므로 로그를 외부에 공유하기 전 개인정보나 비공개 내용을 확인한다.

**실행하지 않는 명령:** `apply`, `template`, `test`, Git 변경/푸시. 이 모듈은 해당 기능을 제공하지 않는다.

## 5. 안전·신뢰 경계

1. `load_proposal()`가 로컬에 등록된 20개 입력·원본 PDF 바이트·인용 위치를 검증하더라도 공식 원격 서버의 **독립 인증은 아니다**.
2. `load_review_context()`는 검토자 ID나 이벤트 해시를 **실제 사람의 인증 승인**으로 만들지 않는다.
3. 사람이 시각적으로 원본 PDF의 표·각주·적용 대상·시점을 확인한 후에만 별도 승인을 거쳐 `review_v2_input_cli`에 검토 내용을 입력한다.
4. `ABSENCE_REVIEWED`는 2025년 공고 전체와 동등 규정에 대한 실제 검토가 필요하다. AI의 `absence_analysis`만으로 작성하지 않는다.
5. `humanApproved=false`, `java_import_ready=false`를 유지한다. 게이트 `SOURCE_PROVENANCE_UNVERIFIED`를 로컬 관측으로 해제하지 않는다.
6. 제안 내용이 채택되더라도 `CORRECTION_ACCEPTED` 후 적법한 `COMPARISON_ACCEPTED`를 별도로 기록해야 한다.
7. 검토 revision은 사용자와 별도의 실행 승인 이후에만 기존 `review_v2_input_cli apply`로 새 파일에 저장한다. Stage C bridge는 이벤트, revision, PDF, DB, Git 변경 기능을 갖지 않는다.
8. 별도 출처 확인을 하지 않은 FAQ 기록은 참고 정보일 뿐 인증된 v2 PDF 근거가 아니다.

## 6. 검증 이력 및 이번 개선 배치 계획

- **기존 승인본 검증:** 2026-11-20 Stage C 신규 20개·Stage B 44개·기존 v2 60개·Stage A 18개, 총 **142/142 PASS**. 보호 대상 97개 파일의 검사 전후 SHA-256과 Git 상태, revision 상태가 동일했다.
- **이번 배치:** 기존 연결 모듈, 해당 테스트, 본 문서 **세 파일만** 수정. 원본 정책·PDF·기존 이벤트 판정/게이트 모듈은 수정하지 않는다.
- **새 회귀 검증 시나리오:** 최종 수용된 한쪽 연도 후보의 `NO_CHANGE`, 재검토 상태로 되돌아간 후보, 실제 `ADDED` 부재 검토, 근거 부족 항목의 수용/기각, 원본 우려사항과 현재 요구사항 집계 분리.
- **미실행:** 위 변경에 대한 신규 테스트·회귀 테스트는 **실행하지 않았다**. 기존 142건의 PASS는 변경 이후 테스트 성공을 의미하지 않는다.
- **후속 승인 절차:** 세 파일의 전체 Diff와 SHA-256 비교 후 별도 승인을 받아 신규 테스트 및 관련 기존 회귀 테스트를 묶어 실행. 전후 파일 해시, Git 상태, LocalAppData revision 목록 비교.
- **실제 사람 검토:** 정책 15건의 원문 확인, 검토자 판단, 승인된 action 파일의 dry-run, 개별 실행 승인 후 revision 생성. 이번 기능 개선만으로 검토 완료 처리하지 않는다.

Stage C bridge는 *검토를 위한 읽기 전용 연결층*이며 정책 의미의 사실성, 출처 독립 인증, 검토자 신원, 최종 게시 또는 Java DB 반영 가능성을 보증하지 않는다.
