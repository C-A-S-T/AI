# 보유 문서 기반 정책 비교 — 1차 Python 구현

이 단계는 **정책 비교 후보 생성 및 검토용 JSON 출력**만 제공한다. 신규 문서 수집, 자동 정책 감지, Java API 호출, DB 업데이트, 리서치/Claim 재검증은 수행하지 않는다. 실제 정책 자료는 Git 저장소에 포함되어 있지 않다.

## 입력 준비

1. 기존 `pipeline.py`가 만든 `metadata/documents.json`, `data/cleaned/DOC-...json`을 사용한다. 원본 `data/raw`는 수정하지 않는다.
2. 비교할 문서에는 `metadata/sources.json`의 `program_name`, `organization`, `document_role`, 필요 시 `published_at`을 신중히 확인한다. 같은 연도 폴더나 비슷한 제목만으로는 동일 정책으로 취급하지 않는다.
3. 다음 명령으로 **후보 제안만** 생성한다. 이 명령은 LLM을 사용하지 않는다.

```powershell
python -m src.policy_compare.cli propose --documents metadata/documents.json --output reports/policy_compare_candidates.json
```

4. 제안된 후보에서 진짜 같은 사업의 다른 연도/정정 버전인지 원문을 확인한다. `metadata/policy_compare_pairs.example.json`을 참고하여 **별도의** `metadata/policy_compare_pairs.json`을 만들고, 실제 `DOC-...` 값만 넣는다. 예시 파일에는 임의 문서 ID를 제공하지 않는다.

```json
{
  "schema_version": 1,
  "pairs": [
    {
      "approved": true,
      "policy_key": "verified-policy-key",
      "policy_title": "실제 문서에서 검토한 동일 정책명",
      "category": "GOV_SUPPORT",
      "previous_document_key": "DOC-<실제 이전 문서 ID>",
      "current_document_key": "DOC-<실제 이후 문서 ID>",
      "previous_extraction_reviewed": false,
      "current_extraction_reviewed": false
    }
  ]
}
```

`DOC-<...>`는 형식 안내이므로 실제 값으로 교체해야 한다. `approved`는 **문서 관계의 수동 확인**을 뜻하며, AI가 출력할 개별 변경 결과의 확인과는 별개다. 추출 경고가 존재한다면 관련 페이지/표를 직접 확인한 뒤에만 `*_extraction_reviewed`를 `true`로 설정한다. `OCR_REVIEW`는 수동 플래그로도 통과할 수 없고, OCR/재추출이 먼저 필요하다. 또한 HWPX에서 원본 표인 `source_tables`가 페이지에 매핑되지 않은 채 남아 있거나 해당 필드가 없으면, 수동 검토 플래그가 참이어도 `HWPX_SOURCE_TABLE_REVIEW_REQUIRED`로 중단한다. 이 단계에서는 원본 표를 임의의 PDF 페이지에 연결하지 않는다.

## 유료 LLM 비교 (별도 테스트·실제 호출 승인 이후에만 실행)

이 명령은 사용자의 명시적인 실행 승인과 `OPENAI_API_KEY`, OpenAI Python SDK가 필요하다.
SDK는 별도의 `requirements-policy-compare.txt`에 선언되어 있으며, 의존성 설치도 별도 승인 후 실행한다.
기존 RAG용 의존성 파일은 변경하지 않았다. 설치가 승인되면 정책 비교 실행에 사용하는 Python 환경에서
`python -m pip install -r requirements-policy-compare.txt`로 설치한다. VS Code에서는 프로젝트의 `.venv`를 선택하고, `python`이 해당 가상환경을 가리키는지 확인한다. 기존 서비스와 같은 환경에 설치하는 경우 SDK 버전 충돌이 없는지 확인해야 한다.

승인된 비교 쌍은 **최대 3쌍(절대 상한)**이다. 동일한 문서가 여러 쌍에 등장하더라도 **한 실행에서 고유 문서당 LLM 추출은 한 번**만 수행하고, 추출 필드를 메모리에서 재사용한다. 같은 문서에 대한 추출 검토 플래그가 서로 다른 경우 실행을 중단한다. 모든 고유 문서의 추출 상태·원본 표·45,000자 입력 제한을 **첫 유료 호출 전에** 검사하며, 부적합 문서가 하나라도 있으면 호출하지 않는다. 다만 사전 검사를 모두 통과한 이후 LLM 응답이 실패하면 이미 보낸 요청의 비용은 발생할 수 있다.

GPT-4.1 mini의 SDK 자동 재시도는 `0회`, 요청 타임아웃은 `120초`, 출력 상한은 `12,000` 토큰이다. 완료되지 않은 응답은 거부한다. 45,000자를 넘는 문서는 **조용히 자르지 않고 실패**한다. 이는 문서 분할 비교가 아직 없는 1차 MVP의 한계다.

```powershell
python -m src.policy_compare.cli compare --documents metadata/documents.json --pairs metadata/policy_compare_pairs.json --cleaned-dir data/cleaned --output reports/policy_compare_review.json --max-pairs 3 --allow-llm
```

각 문서에서 정책 항목을 추출하고, 이전·이후 양쪽에서 같은 `field_key`와 `scope`가 식별되며 값이 다른 항목만 `UPDATED` 후보로 출력한다. **명시적인 신설/폐지 근거 없이 한쪽에만 나온 항목은 `INCONCLUSIVE`**로 분류한다. 표는 원문과 같은 페이지의 단일 셀 텍스트로만 인용을 검증한다.

이 프로그램은 인용문이 해당 페이지/표 셀에 존재하는지 확인하고, AI가 출력한 값에 **아라비아 숫자가 포함된 경우** 숫자·범위·단위의 표면적 일치도 검사한다. 쉼표 및 공백 차이는 허용하지만, `20만 원`과 `200,000원`처럼 단위 환산이 필요한 표현은 자동으로 동일하다고 인정하지 않는다. 인용은 실제 페이지 텍스트 또는 단일 표 셀에 포함되어야 한다.
검증 실패 시 비교 실행은 오류로 중단되며 확인되지 않은 일부 결과만 따로 출판하지 않는다. 숫자가 없는 의미적 조건, 복잡한 표 관계, 여러 숫자 중 어느 기준을 가리키는지, 법적 효력 및 실제 변경 여부는 **자동으로 검증할 수 없다**. 따라서 모든 비교 결과는 `REVIEW_REQUIRED`, `java_import_ready=false`이며 자동 저장하지 않는다. 의미가 같아도 표현만 다른 값은 변경 후보가 될 수 있으므로 최종 판정은 사람의 검토가 필요하다.

기존 결과 파일은 덮어쓰지 않는다. 새 결과 파일명으로 실행해야 한다. 기존 문서 원본, 전처리 캐시, DB는 절대 수정하지 않는다.

## 다음 개발 단계

- 확인된 항목별 비교 결과를 위한 Java 수신 DTO·내부 인증 API 및 Flyway V13 설계
- Python 파일의 문자열 문서 키 `DOC-...`를 AI DB의 숫자 `ai.document.document_id`에 정확하게 대응시킨 후에만 Java 전송. 현재 CLI JSON은 **Java import 계약이 아니다**
- 통합 검증이 끝나기 전까지 정식 정책 변경으로 노출하지 않기
