# AI R&E Lab

GPT, Claude, Gemini, Grok 네 계열 모델이 BAZE API를 통해 한 채팅방에서 발언하는 **R&E 작업실**입니다. 네 사람이 각각 자신의 BAZE 키로 모델 하나씩 호출합니다. 네 모델은 역할과 AI 연구 주제를 토론해 정합니다. 네 사람 모두 채팅에 개입하고 자료를 추가하며, 활동 기록에서 실제로 보낸 프롬프트와 받은 답변을 확인할 수 있습니다.

## 실행 — PowerShell에서 한 줄씩

Python 3.10 이상이 필요합니다. Windows에서는 `python -m pip install -r requirements.txt`로 인증서 저장소 연동을 설치하세요.

```powershell
cd 'RE_AI_Lab'
```

```powershell
python .\app.py --share
```

브라우저가 자동으로 열리지 않으면 `http://127.0.0.1:8765`로 접속하세요. 종료할 때는 PowerShell에서 `Ctrl+C`를 누릅니다.

1. 네 사람이 각각 자기 화면의 **연구 설정** 탭에서 자신의 BAZE 키를 입력하고 **내 키 연결**을 누릅니다. 키와 각 계정의 모델 목록은 서로 분리됩니다.
   잘못 연결했다면 연구 시작 전에 **내 키 연결 해제**를 누르세요. 이 버튼은 현재 화면의 계정에 등록된 키만 서버 메모리에서 지웁니다.
2. 모델 네 개의 **담당 계정**을 한 사람당 하나씩 배정하고, 해당 계정에서 사용할 수 있는 모델 ID를 선택합니다. 목록에 없는 모델은 그 계정으로 호출할 수 없습니다.
3. 라운드 수를 정한 뒤 **연구 시작하기**를 누릅니다. 역할 협의 4번, 주제 선정 4번, 연구 토론에 라운드당 4번 호출합니다. 1라운드는 총 12번의 API 호출이며 비용은 담당 계정에 각각 발생합니다.
4. **메시지** 탭에서 답변을 보며 의견을 쓰거나 **공유 자료** 탭에서 UTF-8 자료를 올리세요. 현재 호출 중인 모델에는 반영되지 않고 **다음 모델 호출부터** 반영됩니다. **모델 발언마다 잠시 멈추기**를 체크했다면 매 발언 후 의견을 쓸 시간이 생깁니다.
5. **활동 기록** 탭에서 호출 계정·모델·시작/완료/실패 상태·실제 프롬프트·응답·반환된 사용량을 볼 수 있습니다. 제공업체가 공개하지 않는 내부 사고 과정은 볼 수 없습니다.
6. **일시정지**로 다음 모델 호출을 보류하고, **계속**으로 재개할 수 있습니다. **중지**는 현재 호출이 끝난 뒤 적용됩니다.
7. **공유 자료** 탭에서 **경로 복사**로 호스트 컴퓨터의 저장 위치를 확인하거나 **전체 ZIP 받기**로 자료와 결과를 내려받으세요. 저장된 초안과 데이터를 검토한 뒤 실제 실험·출처 검증을 계속 진행하세요.

## 프로젝트 폴더 구성

연구를 시작하면 `projects/YYYYMMDD_HHMMSS_******/` 아래에 생성됩니다.

| 위치 | 내용 |
| --- | --- |
| `manifest.json` | 선정 주제, 연구 질문, 모델 ID, 담당 계정, 역할, 상태 |
| `research/role_selection.md` | 네 모델이 협의한 역할 |
| `research/topic_selection.md` | 네 모델이 선정한 주제와 질문 |
| `data/raw/conversation.jsonl` | 모델·사용자·시스템의 전체 대화 기록 |
| `data/raw/prompts/` | 각 호출에 전달한 실제 프롬프트 |
| `data/raw/responses/` | BAZE API 응답 JSON (키가 응답에 섞인 경우 마스킹) |
| `data/processed/turn_metrics.csv` | 호출 시간, 모델, 사용량, 경고 |
| `data/processed/activity.jsonl` | 각 호출의 대기·완료·실패 이벤트 |
| `datasets/` | 사용자가 올린 데이터셋 |
| `references/sources.csv` | 사용자가 입력한 출처·수집 메모 |
| `results/discussion_draft.md` | 토론을 모은 보고서 **초안** |

사용자가 올린 파일은 각 모델에 최대 10,000자씩 전달됩니다. 여러 파일을 합친 프롬프트 자료는 최대 30,000자입니다. 긴 자료는 일부만 전달될 수 있지만 원본 파일은 그대로 저장됩니다. 출처 URL은 기록하지만 자동으로 읽거나 검증하지 않습니다. 이 프로그램은 모델의 연구 **계획·토론·기록**을 자동화하며, 실제 실험이나 학술적 검증이 끝났다고 표시하지 않습니다.

## 보안 및 오류

로컬 서버는 이 컴퓨터의 `127.0.0.1`에만 열립니다. 네 API 키는 각각 서버 메모리에만 보관되고 프로젝트 파일이나 화면 상태 응답에는 기록되지 않습니다. 다만 대화, 업로드한 데이터와 프롬프트는 각 모델을 맡은 BAZE 계정과 제공업체로 전송됩니다. 민감한 자료는 올리지 마세요. 모델 답변이 실패하면 자동 재시도하지 않으므로 사용량 중복 청구를 피할 수 있습니다. 새 연구를 시작하기 전 오류 내용과 저장된 기록을 확인하세요.

이 PC의 SSL 인증서 오류를 해결한 `baze_models.py`를 그대로 포함합니다. 다른 Python 환경에서 같은 오류가 난다면 해당 Python에 `python -m pip install truststore`를 설치한 후 다시 시작하세요. 인증서 검증은 끄지 않습니다.

`[WinError 10061]` 연결 거부가 나타나면 키 오류로 단정하지 마세요. 실행 환경의 네트워크 차단 프록시 때문에 BAZE 서버에 도달하지 못할 수 있습니다. 외부 네트워크가 허용된 일반 PowerShell에서 앱을 실행하거나, 실행 환경의 네트워크 권한을 허용한 뒤 앱을 다시 시작하세요. 키 인증 오류는 서버에 도달한 뒤 `HTTP 401`처럼 별도로 표시됩니다.

키 입력 없이 앱 화면과 서버를 켤 수 있지만, 실제 네 모델 호출에는 네 사람의 BAZE API 키와 각 계정의 모델 권한·잔액이 필요합니다.

## 로컬에서 네 사람 접속

네 사람 모두 같은 화면과 권한을 사용합니다. 암호로 접속하면 자신의 BAZE 키를 연결하고, 모델을 선택하고 연구를 시작·일시정지·재개·중지할 수 있으며 메시지·자료·출처를 추가할 수 있습니다. 대화에는 각자의 발언이 구분되어 기록됩니다. 상대의 BAZE 키 자체는 화면에 표시되지 않습니다.

첫 번째 PowerShell:

```powershell
cd 'RE_AI_Lab'
```

```powershell
python .\app.py --share
```

내 화면은 `http://127.0.0.1:8765`입니다. 친구, 참여자 3, 참여자 4의 화면은 각각 `http://127.0.0.1:8766`, `http://127.0.0.1:8767`, `http://127.0.0.1:8768`에 열립니다. 각 화면의 `viewer` 로그인 암호가 PowerShell 창에 표시됩니다. 암호는 실행할 때마다 새로 생성됩니다.

다른 장소에서 접속하려면 각 참여자 포트마다 별도 터널이 필요합니다. 예를 들어 친구 화면은 두 번째 PowerShell에서 같은 폴더로 이동한 뒤:

```powershell
.\tools\cloudflared.exe tunnel --url http://127.0.0.1:8766
```

출력에 표시되는 `https://....trycloudflare.com` 주소와 **사용자 이름 `viewer`**, 첫 번째 창의 **친구 암호**를 친구에게 알려 주세요. 참여자 3과 4는 각각 8767, 8768 포트로 같은 명령을 별도 PowerShell에서 실행합니다. 공유 주소는 임시 주소라 터널을 다시 켜면 바뀝니다. 종료할 때는 각 창에서 `Ctrl+C`를 누릅니다. URL이나 암호를 공개 게시물에 올리지 마세요.

`tools/cloudflared.exe`는 저장소에 포함하지 않습니다. 공유하려면 [Cloudflare 공식 다운로드](https://developers.cloudflare.com/tunnel/downloads/)에서 직접 설치한 뒤 위 명령의 실행 파일 경로를 조정하세요. 임시 URL 방식은 [Cloudflare Quick Tunnels 안내](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)를 따릅니다.

GitHub에 코드를 올릴 수는 있지만, [GitHub Pages는 Python 서버를 실행하지 않습니다](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site). 이 앱의 실시간 모델 호출·대화 저장 기능을 유지하려면 별도 서버가 필요합니다. 저장소에 올릴 때는 `.gitignore`가 제외하는 `projects/`의 연구 기록·데이터셋과 `tools/`의 실행 파일을 포함하지 마세요.

## PC를 꺼도 접속하는 클라우드 배포

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/chanmin6785-hue/RE_AI_Lab)

`Dockerfile`은 HTTPS 프록시 뒤에서 네 사람이 각각 로그인하는 서버를 실행합니다. Render에서는 `BAZE_LAB_PUBLIC_HOST`를 설정할 필요가 없습니다. 아래 네 환경 변수에 **서로 다른 20자 이상의 로그인 암호**를 설정하세요. 암호를 코드나 GitHub 저장소에 적지 마세요. 네 계정은 연구 설정·대화·자료·시작/중지에 같은 권한을 가집니다. BAZE 키는 각자 로그인한 화면에서 연결합니다.

| Render 환경 변수 | 로그인 사용자 이름 |
| --- | --- |
| `BAZE_LAB_OWNER_PASSWORD` | `owner` |
| `BAZE_LAB_FRIEND_PASSWORD` | `friend` |
| `BAZE_LAB_MEMBER3_PASSWORD` | `member3` |
| `BAZE_LAB_MEMBER4_PASSWORD` | `member4` |

이미 만든 Render Blueprint에 새 암호 변수 두 개를 추가했다면, `sync: false` 변수는 다시 묻지 않으므로 서비스의 **Environment**에서 직접 입력하고 **Save and deploy**를 선택해야 합니다.

연구 파일을 재배포·재시작 뒤에도 보존하려면 호스트의 **영구 저장 디스크**를 붙이고 `BAZE_LAB_PROJECTS_DIR`을 해당 디스크의 `projects` 폴더로 지정해야 합니다. 예를 들어 디스크가 `/data`에 붙었다면 `/data/projects`입니다. 디스크 없이 실행하면 호스트가 재시작할 때 자료가 사라질 수 있습니다. 앱은 BAZE 키를 메모리에만 보관하므로 서버가 재시작하면 네 사람이 키를 다시 연결해야 합니다. 진행 중이던 모델 호출도 재시작 시 이어지지 않습니다.

Render에서 GitHub 저장소의 **New → Blueprint**를 선택해 이 저장소의 `render.yaml`을 연결하면 무료 Web Service를 만들 수 있습니다. Render가 자동 제공하는 `RENDER_EXTERNAL_HOSTNAME`을 사용하므로 `BAZE_LAB_PUBLIC_HOST`를 따로 지정할 필요는 없습니다. 배포 화면에서 네 로그인 암호를 각각 입력하세요. 상태 확인 경로는 `/healthz`입니다. 무료 인스턴스는 유휴 시 중지되고 로컬 파일이 재시작·재배포 후 유지되지 않습니다. 연구가 끝나면 반드시 **전체 ZIP 받기**로 기록을 내려받으세요. 서버가 다시 켜지면 네 사람이 BAZE 키를 다시 연결해야 합니다. GitHub 저장소를 공개하더라도 API 키·로그인 암호·연구 자료는 저장소에 올리지 마세요.


