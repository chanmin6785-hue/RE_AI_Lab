# BAZE 조사 기록 (2026-10-12)

범위: 로그인된 BAZE 채팅 모델 선택창과 API Gateway 개발자 화면을 직접 열고, BAZE 공식 개발자 문서와 대조했다. API 키 값은 읽거나 복사하지 않았고, 인증된 API 호출은 실행하지 않았다. 화면에 보이는 정보는 계정·시점에 따라 달라질 수 있다.

## 연구실에 영향을 주는 사실

- BAZE 공지(2026-10-02)는 **남은 월간 크레딧이 5,000 미만**이면 한국 시간 자정에 **월간 크레딧 5,000을 추가**한다고 설명한다. 기준은 토큰 수가 아니고, `<= 5,000`도 아니다. 추가된 월간 크레딧은 다음 달로 이월되지 않으며 정책은 변경될 수 있다. 연구실은 잔액을 추정하거나 이 공지가 모든 계정에 영구 적용된다고 가정해서는 안 된다.
- 개발자 화면의 API Gateway Base URL은 `https://factchat.mindlogic-kr-api.com/v1/gateway`이다. 다른 배포처로 같은 키를 보내면 401이 발생한다고 명시한다.
- 현재 화면은 API 호출 가능 모델 **47개**를 표시한다. Super Agent와 무제한 모델(SAIT 등)은 채팅 앱 전용으로 Gateway API에서 사용할 수 없다. 각 키의 실제 모델 접근 권한은 `GET /models/?type=llm`으로 개별 확인해야 한다.
- 채팅 화면의 모델 카드 비용 예: GPT-6.1 Sol 20, Claude Sonnet 5.5 20, Gemini 3.8 Flash 8, Grok 4.7 20 **크레딧/1만 토큰**. 이는 채팅 UI의 표시값이다. Gateway는 제공사 USD 가격, 당일 환율, 계정별 크레딧 환산율, 캐시·도구 사용량을 반영하므로 이 숫자를 API 호출 비용에 대입해서는 안 된다.
- `GET /credits/`는 API 키에 연결된 계정의 `monthly_allocated`, `purchased`, `org_granted`, `total` 각각의 잔액을 반환한다. `GET /usage/`는 날짜·모델·키별 Gateway 사용량을 반환하지만 BAZE 웹앱 채팅 사용량은 제외한다. 비스트리밍 LLM 응답에는 계정 설정에 따라 `billing.deducted_credit`가 실리고, 잔액은 별도 `/credits/` 요청으로 조회해야 한다.
- `POST /estimate/`는 이미지·비디오·음악만 견적을 제공한다. 네 텍스트 모델의 사전 견적 수단으로 사용하면 안 된다.
- Gateway에는 제공사 서버가 실행하는 웹 검색과 코드 실행 도구가 있다. Claude Messages와 OpenAI Responses에서 웹 검색·코드 실행을 요청할 수 있고, Gemini 네이티브 경로는 검색을 지원한다. 이는 연구실 서버에서 생성된 코드를 실행시키지 않고 검증 계산을 맡길 수 있는 경로다. 다만 지원 여부는 모델별로 다르며 검색은 횟수당, 코드 실행은 컨테이너 시간당 토큰과 별도로 과금된다. 문서상 Claude 코드 실행은 최소 5분, OpenAI 코드 인터프리터는 최소 15분 기준으로 계산된다. 도구 실행 결과와 비용도 원형 응답·사용량에 남겨야 한다.
- Gateway 일반 속도 제한은 회원당 60초에 120건이다. 429는 `Retry-After`를 참고해 기다리고, 402는 크레딧 소진으로 처리한다. 제한은 키마다 따로 부여되는 것이 아니다.

## 네 계열의 현재 표기 모델 ID 예시

| 계열 | 최근 모델 예시 | 설명 |
|---|---|---|
| GPT | `gpt-6.1-sol` | 채팅 카드: 1.05M 세션, 20 크레딧/1만 토큰. |
| Claude | `claude-sonnet-5-5` | 채팅 카드: 1M 세션, 20 크레딧/1만 토큰. |
| Gemini | `gemini-3.8-flash` | 채팅 카드: 1M 세션, 8 크레딧/1만 토큰. |
| Grok | `grok-4.7` | 채팅 카드: 500K 세션, 20 크레딧/1만 토큰. |

이 표는 선택 후보일 뿐이다. 실제 연구 시작 전 각 키의 `/models/?type=llm` 결과와 `/credits/` 잔액을 다시 확인해야 한다. 개발자 화면의 `47개`는 그 화면에 표시된 API 모델 수이며, 각 참여자 계정의 실제 사용 가능 수와 같다고 단정할 수 없다.

## 연구 도중 Gemini 교체 원칙

초기 선택은 GPT-6.1 Sol, Claude Sonnet 5.5, Gemini 3.8 Flash, Grok 4.7이다. Gemini 4 Argon이 나중에 BAZE Gateway의 담당 계정 `/models/?type=llm` 목록에 실제로 나타나면, 진행 중 호출이 끝난 체크포인트에서 Gemini만 교체한다. 원래 대화·자료·계획서는 유지하고, 교체 일시·정확한 모델 ID·호출 번호·이유를 변경 이력에 남긴다. 모델을 연구 대상이나 평가자로 쓰는 실험에서는 교체 전후 결과를 같은 조건의 결과로 합치지 않는다. 고정된 테스트셋의 일부를 두 모델에 모두 실행해 연결 비교를 하고 보고서에 모델 버전별 결과를 따로 표기한다. 당시 모델에 접근할 수 없으면 과거 결과를 재생성할 수 없을 수 있으므로 원형 응답과 모델 ID를 보존한다.

## R&E 운영 기준

전북과학고의 공개 2024학년도 운영 자료에는 학생 주도 주제 선정, 연구계획서 발표, 중간 결과 발표, 최종보고서 발표, 교사 중간 지도와 연구일지 기록, 3월부터 12월까지의 장기 탐구가 포함되어 있다. 2026학년도 공식 일정이나 양식이라고 단정하지 않고 연구실의 단계 설계 참고 자료로 쓴다. AI가 만든 연구 계획과 발표 자료는 사람의 검토를 거쳐야 하며, 실험 결과는 실행·관측 기록과 재현 가능한 자료가 없으면 결과로 기재하지 않는다.

## 설계에 반영할 점

1. 고정 라운드 대신 역할 협의 → 주제·가설 → 계획서와 계획발표 승인 → 실험 설계·실제 실행·연구일지 → 중간발표 승인 → 추가 실험 → 최종보고서·최종발표 승인으로 진행한다. AI가 다음 단계를 제안해도 검증 및 승인 대기 상태를 기록한다.
2. 호출마다 담당 키의 `/credits/`를 확인한다. 월간 잔액과 전체 잔액을 구분하고, 출력 길이와 과거 사용량으로 보수적인 호출 예산을 잡는다. 호출 뒤 `billing.deducted_credit`와 `/usage/`를 기록한다. 402·429·네트워크 오류는 실패로 기록하고 재시도 시간을 보존한다.
3. 자정 보충은 공지에 따른 가능성일 뿐이다. 다음 날 실제 `/credits/` 값이 증가했는지 확인한 뒤 연구를 재개한다. 한 계정의 잔액 부족을 다른 사람의 키로 조용히 우회하지 않는다.
4. 무료 Render 웹서비스는 유휴 시 잠들며 로컬 파일이 사라질 수 있다. 수개월 연구에는 Supabase에 상태·자료를 저장하고, 깨우기용 예약 작업과 재시작 복원이 필요하다.

## 출처

- BAZE 로그인 후 채팅 모델 선택창, API Gateway 개발자 화면 및 2026-10-02 공지 (2026-10-12 직접 확인)
- [Gateway 개요](https://docs.factchat.kr/docs/app/api-gateway/getting-started/overview)
- [모델 조회](https://docs.factchat.kr/docs/app/api-gateway/getting-started/models)
- [크레딧 잔액](https://docs.factchat.kr/docs/app/api-gateway/reference/credits)
- [사용량 요약](https://docs.factchat.kr/docs/app/api-gateway/reference/usage)
- [요금과 차감](https://docs.factchat.kr/docs/app/api-gateway/reference/pricing)
- [생성 견적 범위](https://docs.factchat.kr/docs/app/api-gateway/reference/estimate)
- [서버 도구: 웹 검색과 코드 실행](https://docs.factchat.kr/docs/app/api-gateway/reference/server-tools)
- [오류와 호출 제한](https://docs.factchat.kr/docs/app/api-gateway/reference/errors)
- [전북과학고 2024학년도 과제연구 운영 자료](https://school.jbedu.kr/ejbs/MABADADAFAC/)
- [Render 무료 웹서비스 제약](https://render.com/docs/free)
