"""Encrypted BAZE key persistence in a private Supabase table.

Only the Python server sees the Supabase secret and the encryption key. The
browser receives connection status and model IDs, never stored key material.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import truststore
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyStoreError(Exception):
    """Safe-to-display storage failure with no key material in its message."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # The server-only Supabase secret must never follow a redirect.
        raise KeyStoreError("키 저장소가 다른 주소로 이동을 요청했습니다.")


class SupabaseKeyStore:
    def __init__(self, url: str, secret: str, encryption_key: str):
        parsed = urlparse(url.rstrip("/"))
        if (parsed.scheme != "https" or not parsed.hostname or
                not parsed.hostname.endswith(".supabase.co") or
                parsed.path or parsed.query or parsed.fragment or parsed.port):
            raise KeyStoreError("SUPABASE_URL은 프로젝트의 https://...supabase.co 주소여야 합니다.")
        if not secret.startswith("sb_secret_"):
            raise KeyStoreError("SUPABASE_SECRET_KEY에 서버 전용 sb_secret_ 키를 설정하세요.")
        try:
            raw_key = base64.urlsafe_b64decode(encryption_key + "=" * (-len(encryption_key) % 4))
        except (ValueError, base64.binascii.Error) as exc:
            raise KeyStoreError("BAZE_LAB_KEY_ENCRYPTION_KEY는 Base64URL 형식이어야 합니다.") from exc
        if len(raw_key) != 32:
            raise KeyStoreError("BAZE_LAB_KEY_ENCRYPTION_KEY는 32바이트 난수여야 합니다.")
        self.endpoint = url.rstrip("/") + "/rest/v1/baze_lab_api_keys"
        self.secret = secret
        self.aes = AESGCM(raw_key)
        self.context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.opener = build_opener(HTTPSHandler(context=self.context), _NoRedirect())

    def _open(self, request):
        return self.opener.open(request, timeout=15)

    def _request(self, method: str, suffix: str = "", body: dict | None = None, prefer: str = ""):
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"apikey": self.secret, "Accept": "application/json", "User-Agent": "RE-AI-Lab/1.0"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        request = Request(self.endpoint + suffix, data=payload, headers=headers, method=method)
        try:
            with self._open(request) as response:
                raw = response.read(100_000)
        except HTTPError as exc:
            raise KeyStoreError(f"키 저장소 요청이 실패했습니다 (HTTP {exc.code}). 테이블과 권한을 확인하세요.") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise KeyStoreError("키 저장소에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from None
        try:
            return json.loads(raw) if raw else None
        except ValueError as exc:
            raise KeyStoreError("키 저장소 응답을 읽지 못했습니다.") from exc

    def load_all(self) -> dict[str, tuple[str, dict[str, list[str]]]]:
        rows = self._request("GET", "?select=slot,payload,models")
        if not isinstance(rows, list):
            raise KeyStoreError("키 저장소 응답 형식이 올바르지 않습니다.")
        loaded = {}
        for row in rows:
            slot = row.get("slot")
            if slot not in ("user", "friend", "member3", "member4"):
                continue
            try:
                data = base64.b64decode(row["payload"], validate=True)
                key = self.aes.decrypt(data[:12], data[12:], slot.encode()).decode("utf-8")
                models = row["models"]
                if (not key or not isinstance(models, dict) or
                        any(not isinstance(value, list) or any(not isinstance(item, str) for item in value)
                            for value in models.values())):
                    raise ValueError("invalid saved record")
            except (ValueError, KeyError, TypeError) as exc:
                raise KeyStoreError("저장된 키를 복원하지 못했습니다. 암호화 설정을 확인하세요.") from None
            except Exception as exc:
                raise KeyStoreError("저장된 키를 복원하지 못했습니다. 암호화 설정을 확인하세요.") from None
            loaded[slot] = (key, models)
        return loaded

    def save(self, slot: str, key: str, models: dict[str, list[str]]) -> None:
        nonce = os.urandom(12)
        payload = base64.b64encode(nonce + self.aes.encrypt(nonce, key.encode(), slot.encode())).decode("ascii")
        self._request("POST", "?on_conflict=slot", {"slot": slot, "payload": payload, "models": models},
                      "resolution=merge-duplicates,return=minimal")

    def delete(self, slot: str) -> None:
        self._request("DELETE", "?slot=eq." + slot)


def store_from_environment() -> SupabaseKeyStore | None:
    names = ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "BAZE_LAB_KEY_ENCRYPTION_KEY")
    values = [os.environ.get(name, "").strip() for name in names]
    if not any(values):
        return None
    if not all(values):
        raise KeyStoreError("SUPABASE_URL, SUPABASE_SECRET_KEY, BAZE_LAB_KEY_ENCRYPTION_KEY를 모두 설정하세요.")
    return SupabaseKeyStore(*values)
