"""BAZE: GPT / Claude / Gemini / Grok 호출. Python 3.10+.

truststore가 설치되어 있으면 운영체제 인증서 검증을 사용합니다.
없으면 Python 기본 SSL 검증을 사용합니다. 인증서 검증은 항상 유지합니다.

사용법:
    python baze_models.py --list-models
    python baze_models.py gpt "안녕!"
    python baze_models.py claude --chat

BAZE_API_KEY 환경 변수 필요. 키가 없으면 터미널에서 숨김 입력을 받습니다.
이 파일은 모델 호출과 텍스트 대화를 제공하며 PC 명령을 실행하지 않습니다.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from getpass import getpass
import json
import os
import ssl
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


BASE_URL = "https://factchat.mindlogic-kr-api.com/v1/gateway"
# 연구실의 선택 모델. 계정별 제공 여부는 시작 전에 /models/로 확인합니다.
DEFAULT_MODELS = {
    "gpt": "gpt-6.1-sol",
    "claude": "claude-sonnet-5-5",
    "gemini": "gemini-3.8-flash",
    "grok": "grok-4.7",
}


class BazeError(RuntimeError):
    """인증, 통신, API 오류 또는 답변을 얻지 못한 경우."""


def _make_ssl_context() -> tuple[ssl.SSLContext, str]:
    """인증서 및 호스트 이름 검증을 유지하며 OS 인증서 저장소를 활용합니다."""
    try:
        import truststore
    except ImportError:
        context = ssl.create_default_context()
        backend = "python-ssl"
    else:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        backend = "system-truststore"
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context, backend


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 인증 헤더가 다른 주소로 자동 전달되는 것을 방지합니다.
        return None


@dataclass
class Reply:
    provider: str
    model: str
    text: str
    usage: dict[str, Any]
    raw: dict[str, Any]
    warning: str = ""


class BazeClient:
    def __init__(self, api_key: str | None = None, timeout: float = 120.0):
        self.api_key = (api_key or os.environ.get("BAZE_API_KEY", "")).strip()
        if not self.api_key:
            raise BazeError("BAZE_API_KEY를 설정하거나 BazeClient(api_key=...)로 키를 지정하세요.")
        if timeout <= 0:
            raise ValueError("timeout은 0보다 커야 합니다.")
        self.timeout = timeout
        context, self.ssl_backend = _make_ssl_context()
        self._opener = build_opener(_NoRedirect(), HTTPSHandler(context=context))

    def _redact(self, value: Any) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return text.replace(self.api_key, "[API_KEY]")[:2000]

    def _request(self, path: str, payload: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "BAZE-Python-Models/1.0",
        }
        if path.startswith("/claude/"):
            headers["anthropic-version"] = "2023-06-01"
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            BASE_URL + path, data=body, headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(16384).decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail)
                detail = detail.get("detail", detail.get("error", detail))
            except (ValueError, AttributeError):
                pass
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            hint = f" / Retry-After: {retry_after}초" if retry_after else ""
            raise BazeError(f"HTTP {exc.code}{hint}: {self._redact(detail)}") from None
        except (URLError, TimeoutError, OSError) as exc:
            cause = exc.reason if isinstance(exc, URLError) else exc
            if isinstance(cause, ssl.SSLCertVerificationError):
                if self.ssl_backend == "python-ssl":
                    hint = "같은 Python에 'python -m pip install truststore'를 실행한 후 다시 시작하세요."
                else:
                    hint = "Windows의 신뢰할 수 있는 인증서와 네트워크 인증서 설정을 확인해야 합니다."
                raise BazeError(f"SSL 인증서 검증 실패 ({self.ssl_backend}). {hint}") from None
            raise BazeError(f"연결 오류: {self._redact(str(exc))}") from None
        except (ValueError, UnicodeError):
            raise BazeError("API에서 JSON 형식의 응답을 받지 못했습니다.") from None
        if not isinstance(result, dict):
            raise BazeError("API 응답이 JSON 객체 형식이 아닙니다.")
        if result.get("error"):
            raise BazeError(self._redact(result["error"]))
        return result

    def list_models(self, provider: str | None = None) -> list[str]:
        """이 계정에서 보이는 LLM ID를 조회합니다. provider 생략 시 모든 LLM."""
        if provider is not None and provider not in DEFAULT_MODELS:
            raise ValueError(f"provider는 {', '.join(DEFAULT_MODELS)} 중 하나여야 합니다.")
        result = self._request("/models/?type=llm")
        if not isinstance(result.get("data"), list):
            raise BazeError("모델 목록 응답에 data 배열이 없습니다.")
        ids = sorted({item["id"] for item in result["data"] if isinstance(item, dict) and item.get("id")})
        return [name for name in ids if provider is None or name.startswith(provider + "-")]

    def credits(self) -> dict[str, Any]:
        """Read this API key's account balance in credits, without spending them."""
        result = self._request("/credits/")
        if result.get("object") != "credit_balance":
            raise BazeError("크레딧 잔액 응답 형식이 올바르지 않습니다.")
        for bucket in ("monthly_allocated", "purchased", "org_granted", "total"):
            value = result.get(bucket)
            if not isinstance(value, dict) or not isinstance(value.get("remaining"), (int, float)):
                raise BazeError("크레딧 잔액 응답에 필요한 값이 없습니다.")
        return result

    def usage(self, *, group_by: str = "day", scope: str = "key",
              from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
        """Read Gateway-only usage; browser chat usage is excluded by BAZE."""
        from urllib.parse import urlencode
        if group_by not in ("day", "model", "key") or scope not in ("key", "member"):
            raise ValueError("사용량 묶음 또는 조회 범위가 올바르지 않습니다.")
        params = {"by": group_by, "scope": scope}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        result = self._request("/usage/?" + urlencode(params))
        if result.get("object") != "usage_summary" or not isinstance(result.get("rows"), list):
            raise BazeError("사용량 응답 형식이 올바르지 않습니다.")
        return result

    def chat(self, provider: str, *, model: str | None = None,
             system: str = "한국어로 명확하게 답변하세요.", max_tokens: int = 16000) -> BazeChat:
        return BazeChat(self, provider, model=model, system=system, max_tokens=max_tokens)

    def ask(self, provider: str, prompt: str, **options) -> Reply:
        """대화 기록 없이 한 번 질문합니다. 연속 대화에는 chat()을 사용하세요."""
        return self.chat(provider, **options).ask(prompt)


class BazeChat:
    def __init__(self, client: BazeClient, provider: str, *, model: str | None = None,
                 system: str = "", max_tokens: int = 16000):
        if provider not in DEFAULT_MODELS:
            raise ValueError(f"provider는 {', '.join(DEFAULT_MODELS)} 중 하나여야 합니다.")
        if max_tokens <= 0:
            raise ValueError("max_tokens는 0보다 커야 합니다.")
        self.client, self.provider, self.system = client, provider, system
        self.model = model or os.environ.get(f"BAZE_{provider.upper()}_MODEL") or DEFAULT_MODELS[provider]
        self.max_tokens = max_tokens
        self.reset()

    def reset(self) -> None:
        self._history: list[dict] = []
        self._previous_response_id: str | None = None

    def ask(self, prompt: str) -> Reply:
        if not prompt.strip():
            raise ValueError("질문이 비어 있습니다.")
        provider = self.provider
        warning = ""
        if provider == "gpt":
            user = {"role": "user", "content": prompt}
            payload = {"model": self.model, "input": [user], "max_output_tokens": self.max_tokens}
            if self.system:
                payload["instructions"] = self.system
            if self._previous_response_id:
                payload["previous_response_id"] = self._previous_response_id
            raw = self.client._request("/responses/", payload)
            text = "\n".join(
                part["text"] for item in raw.get("output", []) if item.get("type") == "message"
                for part in item.get("content", []) if part.get("type") == "output_text"
            )
            if raw.get("status") not in ("completed", "incomplete"):
                raise BazeError(f"응답이 완료되지 않았습니다: {raw.get('status', '상태 없음')}")
            if not raw.get("id"):
                raise BazeError("Responses 응답에 대화 연결용 id가 없습니다.")
            if raw.get("status") == "incomplete":
                warning = "출력이 완성되지 않았습니다. 토큰 한도 또는 응답 제한을 확인하세요."
            usage = raw.get("usage") or {}
        elif provider == "claude":
            user = {"role": "user", "content": prompt}
            payload = {"model": self.model, "messages": self._history + [user], "max_tokens": self.max_tokens}
            if self.system:
                payload["system"] = self.system
            raw = self.client._request("/claude/v1/messages/", payload)
            text = "\n".join(part["text"] for part in raw.get("content", []) if part.get("type") == "text")
            assistant = {"role": "assistant", "content": deepcopy(raw.get("content", []))}
            usage = raw.get("usage") or {}
            if raw.get("stop_reason") == "max_tokens":
                warning = "출력 토큰 한도에 도달해 답변이 잘렸을 수 있습니다."
        elif provider == "gemini":
            user = {"role": "user", "parts": [{"text": prompt}]}
            payload = {
                "contents": self._history + [user],
                "generationConfig": {"maxOutputTokens": self.max_tokens},
            }
            if self.system:
                payload["systemInstruction"] = {"parts": [{"text": self.system}]}
            model = self.model.removeprefix("models/")
            raw = self.client._request(f"/gemini/v1beta/models/{quote(model, safe='')}:generateContent", payload)
            candidates = raw.get("candidates") or []
            candidate = candidates[0] if candidates else {}
            assistant = deepcopy(candidate.get("content", {}))
            # thoughtSignature를 포함한 원형 content 전체를 다음 턴에 보존합니다.
            assistant.setdefault("role", "model")
            text = "\n".join(part["text"] for part in assistant.get("parts", [])
                             if "text" in part and not part.get("thought"))
            usage = raw.get("usageMetadata") or {}
            finish = candidate.get("finishReason")
            if finish and finish != "STOP":
                warning = f"Gemini 종료 사유: {finish}. 답변이 일부만 반환됐을 수 있습니다."
        else:  # Grok: OpenAI-compatible Chat Completions
            user = {"role": "user", "content": prompt}
            messages = ([{"role": "system", "content": self.system}] if self.system else []) + self._history + [user]
            raw = self.client._request("/chat/completions/", {
                "model": self.model, "messages": messages, "max_tokens": self.max_tokens,
            })
            choices = raw.get("choices") or []
            choice = choices[0] if choices else {}
            text = choice.get("message", {}).get("content") or ""
            assistant = {"role": "assistant", "content": text}
            usage = raw.get("usage") or {}
            finish = choice.get("finish_reason")
            if finish and finish != "stop":
                warning = f"Grok 종료 사유: {finish}. 답변이 일부만 반환됐을 수 있습니다."

        if not isinstance(text, str) or not text.strip():
            details = {key: raw[key] for key in ("status", "stop_reason", "incomplete_details", "promptFeedback") if key in raw}
            if provider == "gemini":
                details["finishReason"] = candidate.get("finishReason")
            raise BazeError("텍스트 답변이 없습니다. 토큰 한도·모델 지원·필터 결과를 확인하세요. "
                            + self.client._redact(details))
        # HTTP/API/파싱 오류나 빈 응답은 대화 기록에 추가하지 않습니다.
        if provider == "gpt":
            self._previous_response_id = raw["id"]
        else:
            self._history.extend([user, assistant])
        return Reply(provider, raw.get("model") or raw.get("modelVersion") or self.model,
                     text, usage, raw, warning)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BAZE의 GPT / Claude / Gemini / Grok 호출")
    parser.add_argument("provider", nargs="?", choices=DEFAULT_MODELS, help="모델 계열")
    parser.add_argument("prompt", nargs="?", help="한 번 질문할 내용")
    parser.add_argument("--model", help="사용할 정확한 모델 ID")
    parser.add_argument("--list-models", action="store_true", help="계정에서 사용 가능한 LLM ID 조회")
    parser.add_argument("--chat", action="store_true", help="대화 모드: /reset, /exit 사용 가능")
    parser.add_argument("--system", default="한국어로 명확하게 답변하세요.")
    parser.add_argument("--max-tokens", type=int, default=16000, help="출력/추론 예산 상한 (기본 16000)")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP 타임아웃 초 (기본 120)")
    parser.add_argument("--json", action="store_true", help="텍스트 대신 API 원형 JSON 응답 출력")
    args = parser.parse_args(argv)
    if args.chat and (args.prompt is not None or args.list_models):
        parser.error("--chat은 prompt 또는 --list-models와 함께 사용할 수 없습니다.")
    if not args.list_models and (not args.provider or (args.prompt is None and not args.chat)):
        parser.error("provider와 질문을 지정하거나, --chat 또는 --list-models를 사용하세요.")
    try:
        key = os.environ.get("BAZE_API_KEY", "").strip()
        if not key and sys.stdin.isatty():
            key = getpass("BAZE API 키 (화면에 표시되지 않음): ").strip()
        client = BazeClient(key, timeout=args.timeout)
        if args.list_models:
            models = client.list_models(args.provider)
            print("\n".join(models) if models else "해당 계열의 모델이 목록에 없습니다.")
            return 0
        chat = client.chat(args.provider, model=args.model, system=args.system, max_tokens=args.max_tokens)

        def display(reply: Reply) -> None:
            print(json.dumps(reply.raw, ensure_ascii=False, indent=2) if args.json else reply.text)
            if reply.warning:
                print(f"안내: {reply.warning}", file=sys.stderr)

        if not args.chat:
            display(chat.ask(args.prompt))
            return 0
        print(f"{chat.provider} / {chat.model}\n/reset: 대화 초기화 · /exit: 종료")
        while True:
            prompt = input("\n나> ").strip()
            if prompt == "/exit":
                return 0
            if prompt == "/reset":
                chat.reset()
                print("대화를 초기화했습니다.")
            elif prompt:
                try:
                    display(chat.ask(prompt))
                except BazeError as exc:
                    print(f"오류: {exc}", file=sys.stderr)
    except (BazeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n종료했습니다.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

