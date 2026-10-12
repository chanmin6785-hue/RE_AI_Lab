"""Durable research state and project files on the same private Supabase project.

The browser never receives the Supabase secret. Rows are inaccessible to anon
and authenticated clients; only the existing server-only secret can use them.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request

from key_store import KeyStoreError, SupabaseKeyStore


class ProjectStoreError(KeyStoreError):
    pass


class SupabaseProjectStore:
    def __init__(self, key_store: SupabaseKeyStore):
        self.key_store = key_store
        self.root = key_store.endpoint.rsplit("/", 1)[0]
        self.hashes: dict[str, str] = {}

    def _request(self, table: str, method: str, suffix: str = "", body=None, prefer: str = ""):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"apikey": self.key_store.secret, "Accept": "application/json",
                   "User-Agent": "RE-AI-Lab/2.0"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        request = Request(f"{self.root}/{table}{suffix}", data=data, headers=headers, method=method)
        try:
            with self.key_store._open(request) as response:
                raw = response.read(20_000_000)
        except HTTPError as exc:
            raise ProjectStoreError(f"연구 저장소 요청 실패 (HTTP {exc.code}). Supabase 연구 테이블을 확인하세요.") from None
        except (URLError, TimeoutError, OSError):
            raise ProjectStoreError("연구 저장소에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from None
        try:
            return json.loads(raw) if raw else None
        except ValueError as exc:
            raise ProjectStoreError("연구 저장소 응답을 읽지 못했습니다.") from exc

    def load(self, target: Path) -> dict | None:
        rows = self._request("baze_lab_research_state", "GET", "?id=eq.active&select=snapshot")
        if not rows:
            return None
        if not isinstance(rows, list) or not isinstance(rows[0].get("snapshot"), dict):
            raise ProjectStoreError("저장된 연구 상태가 올바르지 않습니다.")
        snapshot = rows[0]["snapshot"]
        project_name = snapshot.get("project_name", "")
        if not isinstance(project_name, str) or not project_name or Path(project_name).name != project_name:
            raise ProjectStoreError("저장된 연구 폴더 이름이 올바르지 않습니다.")
        project = target / project_name
        project.mkdir(parents=True, exist_ok=True)
        offset = 0
        self.hashes.clear()
        while True:
            rows = self._request("baze_lab_research_files", "GET",
                                 f"?project_id=eq.{quote(project_name, safe='')}&select=path,data,sha256&order=path.asc&limit=200&offset={offset}")
            if not isinstance(rows, list):
                raise ProjectStoreError("연구 파일 목록을 읽지 못했습니다.")
            for row in rows:
                relative = Path(row["path"])
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise ProjectStoreError("저장된 연구 파일 경로가 올바르지 않습니다.")
                content = base64.b64decode(row["data"], validate=True)
                digest = hashlib.sha256(content).hexdigest()
                if digest != row["sha256"]:
                    raise ProjectStoreError("연구 파일 무결성 검증에 실패했습니다.")
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                self.hashes[relative.as_posix()] = digest
            offset += len(rows)
            if len(rows) < 200:
                break
        return snapshot

    def save(self, project: Path, snapshot: dict) -> None:
        if not project.is_dir() or Path(project.name).name != project.name:
            raise ProjectStoreError("연구 폴더가 올바르지 않습니다.")
        if snapshot.get("project_name") != project.name:
            raise ProjectStoreError("연구 상태와 폴더가 일치하지 않습니다.")
        # Files first: a checkpoint never points beyond files that reached storage.
        for path in sorted(project.rglob("*")):
            if not path.is_file() or path.is_symlink() or path.name.endswith(".tmp"):
                continue
            relative = path.relative_to(project).as_posix()
            content = path.read_bytes()
            if len(content) > 5_000_000:
                raise ProjectStoreError(f"연구 파일 {relative}이 5MB 제한을 넘었습니다.")
            digest = hashlib.sha256(content).hexdigest()
            if digest == self.hashes.get(relative):
                continue
            self._request("baze_lab_research_files", "POST", "?on_conflict=project_id,path",
                          {"project_id": project.name, "path": relative,
                           "data": base64.b64encode(content).decode("ascii"), "sha256": digest},
                          "resolution=merge-duplicates,return=minimal")
            self.hashes[relative] = digest
        self._request("baze_lab_research_state", "POST", "?on_conflict=id",
                      {"id": "active", "snapshot": snapshot},
                      "resolution=merge-duplicates,return=minimal")

