# C.A.S.T. 정책 비교 재판정 후보 검토표 (읽기 전용)

> **문서 상태:** `REVIEW_PLANNING_ONLY_NOT_AN_EVENT` · **기준일:** 2026-11-20\
> **연계 파일:** `metadata/policy_review_runs/seoul_youth_rent_2025_2026/20261120_correction_v1/reassessment_candidates.json`\
> **원본 불변:** `correction_proposals.json`, Source Manifest, 모집공고 PDF, Phase 5 v2 코드, 이벤트·revision 및 Git 이력은 이 문서 작성으로 변경되지 않음.

## 1. 목적과 유의사항

- 원본 정정 제안 **15건(13 P0, 2 RELATED)**을 기존 비교 ID와 연결한 사람 검토용 표다. 검토 상태를 승인 또는 인증하지 않는다.
- **모든 항목의 `review_candidate_type`은 원본 AI 권장 유형과 동일**하다. 새 FAQ 근거는 `SIMILAR_SUPPORT_EXCLUSION`의 **별도 발견사항**일 뿐 정식 16번째 항목이 아니다.
- `v2_event_eligible=false`는 **현재 시점에 실제 검토·증거·승인 요건이 충족되지 않았음**을 뜻한다. 추후 적법한 증거가 확보되면 별도 검증·승인할 수 있다.
- 2025 FAQ Q9는 공개 사본의 본문을 확인했으나 공식 첨부파일과 바이트가 동일한지 확인하지 못했다. 공식 자료와 동등하게 취급하거나 원문 PDF 인용으로 위장하지 않는다.
- 아래 공고 PDF 페이지는 **검토 힌트**로, 확인된 사람의 페이지 검토 이벤트가 아니다.

## 2. 원본 연결 및 집계 불변조건

| 항목 | 기준값 |
|---|---|
| 원본 AI 제안 파일 SHA-256 | `93b87c9fcaa24a47c2f436156a570d8d68e105a97ecd24a49313dca9b8dcfbd8` |
| 원본 proposal_run_id | `seoul_youth_rent_2025_2026_20261120_correction_v1` |
| 정정 제안 건수 | **15 = P0 13 + RELATED 2** |
| 권장 유형 건수 | ADDED_CANDIDATE 7 / INCONCLUSIVE 3 / SPLIT_REQUIRED 2 / UPDATED 2 / MAINTAINED 1 |
| 기존 비교 항목 수 | 82 (기존 기준을 변경하지 않음) |
| 신규 정식 comparison_id 및 revision | 없음 |
| 승인·Java 전송 가능 여부 | `humanApproved=false`, `java_import_ready=false` |

## 3. A~D 15건 최종 검토 후보

| 그룹 | comparison_id | 기존 AI 권장 유형 = 이번 검토 후보 | 근거 수준 | 현재 권장 처리 |
|---|---|---|---|---|
| A | `RENT_BELOW_CAP_PAYMENT` | `INCONCLUSIVE` | `UNRESOLVED` | `NEEDS_MORE_EVIDENCE` |
| A | `RENT_CONVERSION_FORMULA` | `MAINTAINED` | `DIRECT_PDF_SUPPORT` | `REVIEW_MAINTAINED` |
| B | `ONE_PERSON_INCOME_THRESHOLDS` | `UPDATED` | `DIRECT_PDF_SUPPORT` | `REVIEW_UPDATED_WITH_CORRECTION` |
| B | `NEW_SPECIAL_APPLICATION_GROUPS` | `ADDED_CANDIDATE` | `PDF_DIFFERENCE_ABSENCE_UNATTESTED` | `REVIEW_ADDED_AFTER_ABSENCE` |
| B | `TIER_DISTRIBUTION` | `UPDATED` | `DIRECT_PDF_SUPPORT` | `REVIEW_UPDATED` |
| C | `PREVIOUS_BENEFICIARY_RESTRICTION` | `INCONCLUSIVE` | `UNRESOLVED` | `NEEDS_MORE_EVIDENCE` |
| C | `SIMILAR_SUPPORT_EXCLUSION` | `INCONCLUSIVE` | `UNRESOLVED` | `NEEDS_MORE_EVIDENCE` |
| C | `GOV_SUPPORT_REFUND_ON_OVERLAP` | `ADDED_CANDIDATE` | `PDF_DIFFERENCE_ABSENCE_UNATTESTED` | `REVIEW_ADDED_AFTER_ABSENCE` |
| C | `SIMILAR_SUPPORT_SAME_MONTH_STOP` | `ADDED_CANDIDATE` | `PDF_DIFFERENCE_ABSENCE_UNATTESTED` | `REVIEW_ADDED_AFTER_ABSENCE` |
| C | `SUSPENSION_EFFECT` | `SPLIT_REQUIRED` | `SPLIT_DEPENDENCIES_PENDING` | `REVIEW_ONLY_SPLIT_AFTER_CHILDREN` |
| C | `SUSPENSION_NO_RESUME` | `ADDED_CANDIDATE` | `PDF_DIFFERENCE_ABSENCE_UNATTESTED` | `REVIEW_ADDED_AFTER_ABSENCE` |
| D | `DOC_LEASE_ALTERNATIVES` | `SPLIT_REQUIRED` | `SPLIT_DEPENDENCIES_PENDING` | `REVIEW_ONLY_SPLIT_AFTER_CHILDREN` |
| D | `DOC_ADMIN_CONSENT` | `ADDED_CANDIDATE` | `PDF_DIFFERENCE_ABSENCE_UNATTESTED` | `REVIEW_ADDED_AFTER_ABSENCE` |
| D | `ADMIN_CONSENT_ALTERNATIVES` | `ADDED_CANDIDATE` | `PDF_DIFFERENCE_ABSENCE_UNATTESTED` | `REVIEW_ADDED_AFTER_ABSENCE` |
| D | `OBJECTION_DOCUMENT_LIMITATION` | `ADDED_CANDIDATE` | `PDF_DIFFERENCE_ABSENCE_UNATTESTED` | `REVIEW_ADDED_AFTER_ABSENCE` |

## 4. 항목별 근거 페이지·검토 질문

### A · `RENT_BELOW_CAP_PAYMENT` — 20만 원 미만 월세 지원금

**초기 비교 유형:** `INCONCLUSIVE` · **AI 권장 유형:** `INCONCLUSIVE` · **원본 처분:** `INSUFFICIENT_EVIDENCE`\
**모집공고 확인 페이지:** 2025 p.1 / 2026 p.2\
**발견 내용:** 기본 월세 지원 원칙은 양 연도 공통이나, 108,000원 계약자의 실제 지급액과 입력 절사 적용 관계는 자료만으로 확정 불가.

**확인할 사항**
- [ ] 2025년 공고의 108,000원 예시와 2025 지급 공지의 차이 정리
- [ ] 2026년 FAQ Q51 입력 예시와 지급 공지를 구분
- [ ] 지원금 실제 절사 적용을 추가 자료로 확인할 수 없으면 보류

**다음 행동:** `NEEDS_MORE_EVIDENCE`; 이벤트 작성은 별도 승인 후 진행.

### A · `RENT_CONVERSION_FORMULA` — 보증금 환산 계산식

**초기 비교 유형:** `MAINTAINED` · **AI 권장 유형:** `MAINTAINED` · **원본 처분:** `REVISE_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.3 / 2026 p.4\
**발견 내용:** 보증금×환산율÷12개월 산식 형태는 공통. 환산율 5.0%→4.5%, 월세 초과시 합산 한도 93만→90만원 변경은 별도 변경 항목으로 취급.

**확인할 사항**
- [ ] 산식 구조 유지와 환산율 변경을 구분
- [ ] 계산식만 MAINTAINED; 한도와 비율을 유지로 해석하지 않기

**다음 행동:** `REVIEW_MAINTAINED`; 이벤트 작성은 별도 승인 후 진행.

### B · `ONE_PERSON_INCOME_THRESHOLDS` — 1인 가구 소득 판정

**초기 비교 유형:** `INCONCLUSIVE` · **AI 권장 유형:** `UPDATED` · **원본 처분:** `REVISE_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.3, p.4 / 2026 p.5\
**발견 내용:** 2025년 건강보험료 기반 판정과 2026년 소득금액증명원 기반 판정, 중위소득 48% 초과~150% 이하의 범위 차이를 구분.

**확인할 사항**
- [ ] 판정 기준 단위(보험료/월 소득) 혼동 금지
- [ ] 피부양자와 적용 가구원 수 조건 확인
- [ ] 기존 INCONCLUSIVE에서 UPDATED로 전환 시 채택된 정정 필요

**다음 행동:** `REVIEW_UPDATED_WITH_CORRECTION`; 이벤트 작성은 별도 승인 후 진행.

### B · `NEW_SPECIAL_APPLICATION_GROUPS` — 특별 신청유형

**초기 비교 유형:** `ADDED_CANDIDATE` · **AI 권장 유형:** `ADDED_CANDIDATE` · **원본 처분:** `REVISE_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.2, p.5 / 2026 p.1, p.2, p.3\
**발견 내용:** 2026년 별도 특별 신청유형·정원(전세사기피해자, 한부모가족, 청년 신혼부부, 청년안심주택 민간임대)을 확인. 민간임대 거주 자체의 최초 지원을 주장하지 않음.

**확인할 사항**
- [ ] 2025년 10페이지에서 동등한 별도 유형·정원 부재 확인
- [ ] 기존 HOUSEHOLD_ELIGIBILITY와 중복 집계 방지
- [ ] 특별유형별 자격·정원 조건 보존

**다음 행동:** `REVIEW_ADDED_AFTER_ABSENCE`; 이벤트 작성은 별도 승인 후 진행.

### B · `TIER_DISTRIBUTION` — 선정 구간 비율

**초기 비교 유형:** `UPDATED` · **AI 권장 유형:** `UPDATED` · **원본 처분:** `RETAIN_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.7, p.8 / 2026 p.2, p.9\
**발견 내용:** 선정구간 비율 45/30/15/10%→35/30/20/15%; 2026년 적용 분모는 1인 가구 정원 12,000명.

**확인할 사항**
- [ ] 2025년 전체 15,000명과 2026년 1인 가구 12,000명 분모 차이 유지
- [ ] 실제 최종 선정 인원과 공고 정원 구분

**다음 행동:** `REVIEW_UPDATED`; 이벤트 작성은 별도 승인 후 진행.

### C · `PREVIOUS_BENEFICIARY_RESTRICTION` — 기수혜·자치구 선정 제한

**초기 비교 유형:** `INCONCLUSIVE` · **AI 권장 유형:** `INCONCLUSIVE` · **원본 처분:** `INSUFFICIENT_EVIDENCE`\
**모집공고 확인 페이지:** 2025 p.1, p.5 / 2026 p.1, p.6\
**발견 내용:** 서울시 기수혜 제한과 국토부 사업 종료 예외는 양 연도 공통. 자치구 사업 선정자(2025)와 수혜 중인 자(2026)의 실제 적용 범위는 불명확.

**확인할 사항**
- [ ] 자치구 선정 후 미지급·포기·종료자의 2025년 처리 규칙 미확인 표기
- [ ] 서울시 생애 1회 기수혜 제한과 자치구 제한 구분
- [ ] 추가 명확한 근거 없으면 INCONCLUSIVE 유지

**다음 행동:** `NEEDS_MORE_EVIDENCE`; 이벤트 작성은 별도 승인 후 진행.

### C · `SIMILAR_SUPPORT_EXCLUSION` — 유사사업 동시 수혜 제한

**초기 비교 유형:** `INCONCLUSIVE` · **AI 권장 유형:** `INCONCLUSIVE` · **원본 처분:** `INSUFFICIENT_EVIDENCE`\
**모집공고 확인 페이지:** 2025 p.5 / 2026 p.6\
**발견 내용:** 신청 시점 유사사업 동시 수혜 제한 및 종료 예외는 양 연도에 존재. 2025 FAQ Q9와 2026 FAQ Q14는 중복 신청 허용 안내가 상이하지만 이는 별도 범위의 발견 사항.

**확인할 사항**
- [ ] 동시 신청과 동시 수혜의 정책 의미 분리
- [ ] 2025 FAQ Q9 공개 사본의 공식 원본 바이트 동일성 미검증 보존
- [ ] FAQ 발견 사항을 기존 PDF의 source_references로 가장하지 않기
- [ ] 자치구 선정자·수혜 중 표현 차이의 실무 범위 미확정 표기

**다음 행동:** `NEEDS_MORE_EVIDENCE`; 이벤트 작성은 별도 승인 후 진행.

**별도 FAQ 발견:** 2025 Q9는 다른 월세지원 사업의 중복 신청을 불가하다고 안내하며, 2026 Q14는 신청기간 중복 시 신청은 가능하나 동시 수혜는 불가하다고 안내한다. 이 차이는 **중복 신청 안내**라는 별도 주제의 `UPDATED` 검토 후보이며, 기존 **중복 수혜 제한 비교 항목의 최종 판정이 아니다.**

- 2025 사본: https://www.goodil.or.kr/index.php?act=procFileOutput&file_key=69d75a06jzng7j32jzq-xeqMy1rl5gmrqqMEXim27b3pJ9bX&file_srl=14523&module=file
- 2025 공식 첨부 목록: https://housing.seoul.go.kr/site/main/board/notice/12478
- 2026 공식 FAQ Q14: https://housing.seoul.go.kr/site/main/board/faq_mr/12652

**출처 검증 상태:** 2025 사본 내용 관측·공식 원본 동등성 미확인 / 2026 공식 웹페이지 본문 관측. **정식 v2 이벤트 인용에 직접 사용 불가.**

### C · `GOV_SUPPORT_REFUND_ON_OVERLAP` — 국토부 중복 선정 시 환수

**초기 비교 유형:** `ADDED_CANDIDATE` · **AI 권장 유형:** `ADDED_CANDIDATE` · **원본 처분:** `REVISE_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.9 / 2026 p.6\
**발견 내용:** 2026년 서울시 선정·지급 후 당해 국토부 최종 선정에 따른 기지급액 전액 환수 문구를 특정하여 비교; 2025년 일반 부정 신청 환수와 구별.

**확인할 사항**
- [ ] 2025년 전체 공고에서 동등한 순서·범위의 환수 규칙 검토
- [ ] 동일 연도·선정→지급→국토부 최종 선정 순서 유지
- [ ] 일반 환수 규칙 자체를 신규라고 주장하지 않기

**다음 행동:** `REVIEW_ADDED_AFTER_ABSENCE`; 이벤트 작성은 별도 승인 후 진행.

### C · `SIMILAR_SUPPORT_SAME_MONTH_STOP` — 중복 수혜 당월 지급 중지

**초기 비교 유형:** `ADDED_CANDIDATE` · **AI 권장 유형:** `ADDED_CANDIDATE` · **원본 처분:** `RETAIN_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.9 / 2026 p.11\
**발견 내용:** 2026년 유사사업 동시 수혜 발생 월 지급 중지 예외를 2025년 일반 익월 중지와 구별.

**확인할 사항**
- [ ] 2025년 전체 공고의 당월 중지 동등 예외 검토
- [ ] 2026년 일반 익월 중지와 유사사업 당월 중지 차이 표시
- [ ] SUSPENSION_EFFECT 자식 연계 확인

**다음 행동:** `REVIEW_ADDED_AFTER_ABSENCE`; 이벤트 작성은 별도 승인 후 진행.

### C · `SUSPENSION_EFFECT` — 지급 중지 효과 부모

**초기 비교 유형:** `SPLIT_REQUIRED` · **AI 권장 유형:** `SPLIT_REQUIRED` · **원본 처분:** `SPLIT_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.9 / 2026 p.11\
**발견 내용:** 지원 중지 규칙을 두 자식(동시 수혜 당월 중지·재개 불가)으로 구분하고 부모는 실질 변경 건수에 포함하지 않음.

**확인할 사항**
- [ ] 자식 두 항목 각각 REVIEW_ACCEPTED 필요
- [ ] 부모용 SPLIT_RESOLUTION 정정 채택 필요
- [ ] 부모 REVIEW_ONLY_SPLIT 및 중복 집계 금지

**다음 행동:** `REVIEW_ONLY_SPLIT_AFTER_CHILDREN`; 이벤트 작성은 별도 승인 후 진행.

### C · `SUSPENSION_NO_RESUME` — 중지 후 재개 불가

**초기 비교 유형:** `ADDED_CANDIDATE` · **AI 권장 유형:** `ADDED_CANDIDATE` · **원본 처분:** `RETAIN_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.5, p.9 / 2026 p.11\
**발견 내용:** 2026년 지급 중지 후 재개·재신청 불가 및 잔여금 소멸을 별도 조항으로 다룸. 2025년 운영상 동일 효과 여부는 미확정.

**확인할 사항**
- [ ] 2025년 전체 공고에서 동등한 재개 불가 규칙 부재 확인
- [ ] 공고 밖 기존 운영 규칙의 존재 가능성 명시
- [ ] SUSPENSION_EFFECT 자식 연계 확인

**다음 행동:** `REVIEW_ADDED_AFTER_ABSENCE`; 이벤트 작성은 별도 승인 후 진행.

### D · `DOC_LEASE_ALTERNATIVES` — 대체 증빙 서류 부모

**초기 비교 유형:** `SPLIT_REQUIRED` · **AI 권장 유형:** `SPLIT_REQUIRED` · **원본 처분:** `SPLIT_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.6, p.7 / 2026 p.7, p.8\
**발견 내용:** 주택·고시원 기존 대체자료 조합과 전대차 계약서 요구 변화·기숙사 확인서 명시를 분리한다.

**확인할 사항**
- [ ] SUBLET_DOC_REQUIRED_ITEMS 개별 검토
- [ ] DORMITORY_CONFIRMATION 개별 검토
- [ ] SPLIT_RESOLUTION 채택 및 부모 REVIEW_ONLY_SPLIT
- [ ] 공고 외 보완서류 요구 불가능으로 확대해석 금지

**다음 행동:** `REVIEW_ONLY_SPLIT_AFTER_CHILDREN`; 이벤트 작성은 별도 승인 후 진행.

### D · `DOC_ADMIN_CONSENT` — 행정정보 공동이용 동의서

**초기 비교 유형:** `ADDED_CANDIDATE` · **AI 권장 유형:** `ADDED_CANDIDATE` · **원본 처분:** `REVISE_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.6 / 2026 p.7, p.8\
**발견 내용:** 2026년 행정정보 공동이용 사전동의서의 별도 필수서류 명시를 일반 개인정보 동의와 구분하며 비동의 대체 경로를 보존.

**확인할 사항**
- [ ] 2025년 10페이지에서 동일 별도 동의서 제출 요구 부재 확인
- [ ] 2025년 별지·온라인 절차까지 부재 확정하지 않기
- [ ] ADMIN_CONSENT_ALTERNATIVES와 중복 변경 집계 금지

**다음 행동:** `REVIEW_ADDED_AFTER_ABSENCE`; 이벤트 작성은 별도 승인 후 진행.

### D · `ADMIN_CONSENT_ALTERNATIVES` — 비동의 대체서류

**초기 비교 유형:** `ADDED_CANDIDATE` · **AI 권장 유형:** `ADDED_CANDIDATE` · **원본 처분:** `REVISE_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.6 / 2026 p.8\
**발견 내용:** 2026년 사전동의 비동의 시 건강보험 자격확인서·최근 소득금액증명원·주민등록등초본 별도 제출 경로를 보존.

**확인할 사항**
- [ ] 비동의를 신청 자체 불가능으로 오해하지 않기
- [ ] 서류별 시점과 발급 기준 유지
- [ ] DOC_ADMIN_CONSENT의 SUPPORTING으로 중복 집계 금지

**다음 행동:** `REVIEW_ADDED_AFTER_ABSENCE`; 이벤트 작성은 별도 승인 후 진행.

### D · `OBJECTION_DOCUMENT_LIMITATION` — 필수서류 미제출 보완 제한

**초기 비교 유형:** `ADDED_CANDIDATE` · **AI 권장 유형:** `ADDED_CANDIDATE` · **원본 처분:** `REVISE_PROPOSAL`\
**모집공고 확인 페이지:** 2025 p.8 / 2026 p.7, p.10\
**발견 내용:** 2026년 필수 4종 미제출로 서류심사 탈락한 경우에 한정하여 이의신청 추가자료 보완 불가를 설명.

**확인할 사항**
- [ ] 미제출과 경미한 오류·소득 소명을 구별
- [ ] 2025년 전체 공고에 동등한 제한 문구 존재 여부 확인
- [ ] 일반 이의신청 전면 금지로 확대하지 않기

**다음 행동:** `REVIEW_ADDED_AFTER_ABSENCE`; 이벤트 작성은 별도 승인 후 진행.

## 5. FAQ 근거 처리 원칙

1. `reassessment_candidates.json.evidence_catalog`에 공식/비공식 사본의 **출처 유형과 검증 상태를 함께 보관**한다.
2. 원본 Phase 4 비교 유형, `comparison_id`, 82개 집계 및 15개 제안의 `recommendation`을 변경하지 않는다.
3. 공개 FAQ의 문구 차이는 `SIMILAR_SUPPORT_EXCLUSION.separate_faq_finding`에 별도로 보관한다. 이것은 16번째 정식 비교 항목이 아니다.
4. 기존 v2 `source_references`는 고정된 2025·2026년 모집공고 PDF로 검증한다. FAQ URL 또는 외부 사본을 PDF 문서 ID·페이지로 위장해서 입력하면 안 된다.
5. 향후 FAQ를 독립적인 공식 증거로 수용하려면 원본 취득·SHA-256, 문서 ID/페이지/인용 검증, Source Manifest 및 입력 계약·게이트 영향 분석과 별도 승인 절차가 필요하다. **이번 범위에는 미포함**이다.

## 6. 기존 Phase 5 v2에 따른 가능 행동 (모두 미실행)

| 원본 유형 및 검토 상황 | 가능한 다음 절차 | 주의 |
|---|---|---|
| `INCONCLUSIVE` / 증거 부족 | `COMPARISON_NEEDS_MORE_EVIDENCE` | 최종 승인·게이트 통과로 간주하지 않음 |
| `INCONCLUSIVE` / 유형 정정 | `CORRECTION_PROPOSED` → `CORRECTION_ACCEPTED` → `COMPARISON_ACCEPTED` | 양 연도 PDF 증거와 사람 검토 필요 |
| `ADDED_CANDIDATE` / 실제 신규 | 2025년 전 페이지 사람 검토 → `ABSENCE_REVIEWED` → `COMPARISON_ACCEPTED(ADDED)` | 공고 밖 제도 부재 주장은 금지 |
| `ADDED_CANDIDATE` / 동등 규정 있음 | `CHANGE_TYPE_CORRECTION` 채택 → `COMPARISON_ACCEPTED(NO_CHANGE)` | 양 연도 인용 필요, 부재 검토를 주장하지 않음 |
| `SPLIT_REQUIRED` | 각 자식 검토 → `SPLIT_RESOLUTION` 채택 → `COMPARISON_ACCEPTED(REVIEW_ONLY_SPLIT)` | 부모 중복 집계 금지 |
| `UPDATED`, `MAINTAINED` / 기존 값 정확 | 페이지 검토 후 해당 최종 유형 수용 가능 | 기존 값에 잘못된 부분은 별도 정정 |

## 7. 이벤트·revision 생성 전 검토 체크리스트

- [ ] 실제 2025년 PDF 10쪽과 2026년 PDF 13쪽에서 관련 페이지·표·각주 확인
- [ ] `ADDED_CANDIDATE` 7건에 대해서는 전년도 전체 문서의 동등 규정 부재를 **사람이 직접** 확인
- [ ] `SUSPENSION_EFFECT`, `DOC_LEASE_ALTERNATIVES`의 자식 검토 및 부모 분할 계약 확인
- [ ] `change_key`, `summary_role`, 중복 집계 영향 검토
- [ ] 2025 FAQ Q9 원본 바이트 동일성 미확인 사실을 검토 기록에 보존
- [ ] 본문 FAQ 변경 발견은 기존 2025/2026 모집공고 PDF 인용으로 치환하지 않음
- [ ] `humanApproved=false`, `java_import_ready=false`, `authenticated_approval=NOT_GRANTED` 유지
- [ ] 사용자로부터 파일 수정/이벤트 실행/테스트 각각 별도 승인 획득

## 8. 이번 배치의 범위

**신규 생성만 예정:** `reassessment_candidates.json`, 이 문서. 기존 JSON·PDF·Source Manifest·Phase 5 v2 코드 및 revision 파일에는 기록하지 않음. 본 문서와 신규 JSON은 검토 보조 자료이며 자동 병합·전송 대상이 아니다.
