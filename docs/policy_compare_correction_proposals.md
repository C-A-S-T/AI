# C.A.S.T. 정책 비교 정정 제안 — 단계 A

이 자료는 AI 분석 제안이다. 검토자 자기진술, 인증된 사람 승인, Phase 5
이벤트 또는 Java 반영 데이터가 아니다. 테스트는 아직 실행하지 않았다.

## 파일과 범위

- 제안: `metadata/policy_review_runs/seoul_youth_rent_2025_2026/20261120_correction_v1/correction_proposals.json`
- 읽기 전용 검증기: `src/policy_compare/review_correction_proposal.py`
- 테스트: `tests/test_policy_review_correction_proposal.py`
- 본 문서: `docs/policy_compare_correction_proposals.md`

기존 Source Manifest와 그 입력 20개, PDF, Parsed/Cleaned/REVIEWED,
Phase 3~5, 작업 B, v2 초기 Draft와 기존 모듈은 수정하지 않는다.
이 네 파일만 새로 작성한다. 테스트 스크립트도 변경하지 않는다.

P0 13개는 유지 2, 수정 6, 분해 2, 근거 부족 3으로 분류한다.
`RENT_CONVERSION_FORMULA`(정정 제안), `TIER_DISTRIBUTION`(보존 검증)은
별도 `related_items` 두 항목이며 P0 집계에 포함하지 않는다.

## 데이터와 판단의 구분

- `baseline_bindings`: Manifest, 작업 B, Phase 3·4 및 초기 Draft의 고정 해시.
- `baseline_snapshot`: 실제 Phase 4 displayItem 전체의 변경 없는 복사본.
- `recommendation`: 권장 유형·양 연도 표시값·설명·범위·대상 필드·미확정 질문.
  원본에 적용할 실행 가능한 patch는 아니다.
- `evidence`: 두 모집 공고의 문서 ID·연도·PDF 해시·페이지·원문 인용.
- `dependencies`: 실제 scope_id, 그룹, change_key, summary_role, 부모·자식,
  같은 변경 키를 사용하는 다른 항목. 원본 구조를 보존한다.
- `related_comparison_ids`: 의미상 연계 항목. 실제 82개 ID에 포함되어야 한다.
- `absence_analysis`: 이전 AI 분석의 2025 모집 공고 전체 텍스트 검토 범위.
  공고 밖 모든 문서에서의 부재 또는 사람의 ABSENCE_REVIEWED가 아니다.
- `assessment`: 분석 판정 상태, 심각도, 확인 상태, NOT_FINAL을 분리한다.
  이번 severity MEDIUM은 검토 우선도이며 확정 오류 등급이 아니다.
- `event_compatibility`: 자동 변환 false, 사람 검토·별도 실행 승인 필요.
- `trust`: AI 제안, 사람 자기진술 없음, 인증 승인 없음, 게이트 신뢰 변경 없음.

INSUFFICIENT_EVIDENCE인 세 항목의 INCONCLUSIVE는 유지한다.
ONE_PERSON_INCOME_THRESHOLDS만 UPDATED로 제안하되 보험료와 소득액의
직접 증감 비교를 하지 않는다. 기존 소득 판정·자격 항목의 설명을 보조한다.

SPLIT_REQUIRED 부모는 기존 두 분할 관계를 유지한다. 신규 비교 ID,
분할 자식, scope_id Enum 또는 change_key를 만들지 않는다.
환수 항목의 범위 정정은 scope_note에 기록하며 기존 APPLICANT_ALL을
실제 수정하지 않는다. 권장 scope_id의 구체적인 계약값은 후속 검토 대상이다.

모든 항목은 기존 대표 집계 구조를 보존하고 추가 건수를 만들지 않는다.
환산 산식은 MAINTAINED, 환산율 변경은 RENT_CONVERSION_RATE에서 집계한다.
TIER_DISTRIBUTION은 기존 15,000명/12,000명 분모 표현을 보존하며 대상 필드는 비어 있다.

## 출처 관측과 시각의 불확실성

`source_observations`는 앞선 대화 도구에서 공식 서버 바이트를 수신하고
로컬 PDF와 해시가 일치한 결과를 옮긴 독립 관측 기록이다.
현재 구현에서 원격 서버에 다시 접속하지 않는다.

`supplemental_sources`는 공식 게시물에 연결된 FAQ 두 개의 실제 측정 해시,
수신 크기, 인용 페이지·질문번호를 기록한다. 기존 Manifest 20개에는 넣지 않는다.

앞선 도구 결과에 정확한 확인 시각이 보존되어 있지 않으므로 두 종류 모두
`checked_at=null`, `time_status=UNKNOWN`으로 기록한다.
계획서 작성일이나 이번 파일 생성 시각을 측정 시각으로 대체하지 않는다.
새 관측을 수행하려면 별도 승인과 버전 관리가 필요하다.

2025 FAQ p.19 Q45와 2026 FAQ p.25 Q51은 월세 입력 예시를 설명한다.
이를 2026 실제 지급 산식으로 확정하지 않는다. FAQ 관측은 현재 검증기에서
다시 다운로드하거나 바이트 인증하지 않으며 기존 v2 이벤트의 문서 범위 밖이다.

로컬 입력 해시 검증이나 이 JSON의 검증 성공을 trusted_provenance_docs로
변환하지 않는다. 기존 게이트의 SOURCE_PROVENANCE_UNVERIFIED를 해제하지 않는다.

## 검증 API

`load_proposal(path, *, project_root, local_appdata_root)`는 다음 순서로 읽는다.

1. 고정 Source Manifest 해시 확인.
2. 등록 입력 20개의 바이트 크기·해시, Phase 3·4 고정 해시 확인.
3. 작업 B 및 v2 초기 Draft의 고정 해시 확인.
4. 원본 PDF 두 개의 해시·10/13페이지를 확인하고 메모리에서 텍스트 추출.
5. 제안 구조, P0/연계 ID, 전체 원본 스냅샷, 범위·관계, 유형·상태,
   양 연도 근거 페이지·인용, 집계 수, 출처 관측 및 신뢰 경계 검증.

정규화는 공백만 합친다. 표의 의미나 인용의 충분성, 권장 문장의 정책적
정확성까지 자동 판정하지 않는다. 유효한 ID라는 사실도 의미상 중복 관계의
정확성을 증명하지 않는다. 해당 판단은 사람 검토가 필요하다.

`validate_proposal(proposal, *, phase4, pdf_text)`는 메모리 객체만 확인하는
순수 함수다. 호출자가 제공한 객체의 바이트 신뢰는 보장하지 않으므로 실제
입력에는 `load_proposal`을 사용한다. 두 API 모두 입력을 변경하지 않는다.
중복 JSON 키·비표준 NaN 등은 기존 엄격 JSON 디코더로 거부한다.

결과는 VALID_AI_PROPOSAL_NOT_APPROVAL이며 humanApproved,
java_import_ready, gate_trust_updated는 항상 false이다.
이벤트·revision·보고서 파일 생성, 네트워크, 게이트 실행 기능은 없다.

개인 이름·계좌번호·주민번호 값은 기록하지 않고 제출 요건만 설명한다.
금지 필드와 주민번호 형식 검사는 보조 방어다. 자유문장 속 이름·계좌번호를
완벽히 검출하는 개인정보 탐지기는 아니므로 사람의 내용 검토를 유지한다.

## 테스트 계획 — 별도 승인 후 실행

18개 테스트 메서드와 독립 deepcopy subTest로 다음을 검증한다.

- 정상 13+2 구조, P0 2/6/2/3, 입력 무변경, 승인 false.
- 누락·중복·미등록·P0/연계 혼합, 원본 스냅샷·관계·범위 변조.
- 잘못된 문서·페이지·해시·인용, 중복 인용, 한 연도 근거 누락.
- INCONCLUSIVE/신규 후보 자동 확정, 이벤트·승인·부재 자기진술 위조.
- 역사적 관측 해시·미확인 시각 변경, 소득 지표·산식·선정 분모·중복 집계.
- 단계 B 필수 후속 항목과 자동 이벤트 변환 금지.
- 82개 항목·57개 그룹의 누락·중복·미등록 연결 및 개수 오류.
- 모의 입력 바이트 변조 거부 및 실제 로컬 입력 로더의 읽기 전용 동작.

테스트 fixture는 저장소 제안 JSON 및 현재 고정 Phase 4/Parsed 파일을 읽는다.
로컬 검토 자료가 필요하며 합성 데이터로 원격 신뢰를 꾸미지 않는다.
순수 함수 테스트는 각 사례마다 복사본을 사용한다. 실제 로더 테스트만
원본 PDF 텍스트 추출을 수행한다. 모의 변조는 메모리에서만 수행한다.

PowerShell 5.1 실행 예시(아직 실행 승인 없음):

```powershell
Set-Location 'C:\Development\AI\CAST_AI'
$env:CAST_AI_TEST_LOCALAPPDATA = 'C:\Users\Jihyun\AppData\Local'
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_policy_review_correction_proposal.py -v
```

Diff 승인 후 신규 테스트, 실제 제안 로더 검증, 기존 181개 회귀 테스트를
별도 승인 범위에 따라 진행한다. 기존 개수는 재실행 결과로 확인한다.
기존 v2 테스트 수를 변경하지 않으며 새 테스트를 기존 181개에 포함했다고
보고하지 않는다. 실패 시 승인 없이 추가 수정하지 않는다.

전후에는 등록 입력 20개, 실행 폴더 JSON, 저장소 추적·미추적 파일,
외부 검토 결과, Git HEAD/index/config/status 및 기존 diff를 비교한다.
허용되는 변경은 승인된 신규 네 파일뿐이다.

## 단계 B — 이번에는 미구현, 반드시 후속 수정

1. COMPARISON_REJECTED만으로 게이트·진행률·대기열·분할 자식을 완료로
   취급하지 않는다. 기각 이력과 근거 있는 최종 결론을 구분해야 한다.
2. 신규 후보의 근거 있는 비변경·중복 결론을 기록할 경로를 함께 설계한다.
   단순히 기각을 막아 영구 미완료로 만들지 않는다.
3. 실질 변경, 연도별 일정, 표현 변경 집계를 분리한다.
4. 기존 23페이지·해시·출처 신뢰·사람 인증 조건을 약화시키지 않는다.

단계 A에서는 기존 v2 모듈을 수정하지 않는다. 이후 코드 변경은 별도 승인,
Diff 확인, 테스트 승인 절차를 따른다. 사람의 PAGE_CONFIRMED,
ABSENCE_REVIEWED, COMPARISON_ACCEPTED 등은 사람이 실제 확인한 입력과
별도 실행 승인 없이는 생성하지 않는다. revision 생성, 최종 승인,
Java DB 반영, Git commit/push는 이번 범위 밖이다.
