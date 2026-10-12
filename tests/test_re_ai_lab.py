import base64
import copy
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from uuid import uuid4
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Lab, ViewerHandler, CloudHandler, ACCOUNT_LABELS, CLOUD_USERS
from key_store import KeyStoreError
from baze_models import Reply


class FakeControl:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail_on_call = 0


class FakeClient:
    def __init__(self, key, timeout, control):
        self.api_key = key
        self.control = control

    def list_models(self):
        provider = {"OWNER": "gpt", "FRIEND": "claude", "MEMBER3": "gemini", "MEMBER4": "grok"}[self.api_key.split("_", 1)[0]]
        return [f"{provider}-test", f"{provider}-next"]

    def ask(self, provider, prompt, model, max_tokens):
        calls = self.control.calls
        calls.append((self.api_key, provider, prompt, model))
        if len(calls) == 1:
            self.control.entered.set()
            self.control.release.wait(4)
        if len(calls) == self.control.fail_on_call:
            raise ValueError(f"Provider rejected {self.api_key}")
        if "현재 단계: role_selection" in prompt:
            if "ROLE_GPT:" in prompt:
                text = "\n".join(f"ROLE_{p.upper()}: {p}가 정한 연구 역할" for p in ("gpt", "claude", "gemini", "grok"))
            else:
                text = f"MY_ROLE: {provider}의 연구 역할 제안\n역할 중복을 검토합니다."
        elif "현재 단계: topic_selection" in prompt and "RESEARCH_TOPIC:" in prompt:
            text = "RESEARCH_TOPIC: 모델 협업 평가\nRESEARCH_QUESTION: 협업은 품질을 높이는가?"
        else:
            text = f"{provider}의 {len(calls)}번째 토론"
        return Reply(provider, model, text, {"input_tokens": 10},
                     {"id": f"fake-{len(calls)}", "model": model, "upstream_echo": self.api_key})


class LabTest(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parent
        self.temp = self.test_root / ("re_test_" + uuid4().hex)
        self.temp.mkdir()
        self.control = FakeControl()
        self.lab = Lab(lambda key, timeout: FakeClient(key, timeout, self.control), self.temp)
        self.models = {provider: f"{provider}-test" for provider in ("gpt", "claude", "gemini", "grok")}
        self.assignments = {"gpt": "user", "claude": "friend", "gemini": "member3", "grok": "member4"}
        self.lab.connect("OWNER_SECRET_TEST_KEY", actor="user")
        self.lab.connect("FRIEND_SECRET_TEST_KEY", actor="friend")
        self.lab.connect("MEMBER3_SECRET_TEST_KEY", actor="member3")
        self.lab.connect("MEMBER4_SECRET_TEST_KEY", actor="member4")

    def tearDown(self):
        self.control.release.set()
        if self.lab.worker:
            self.lab.worker.join(5)
        self.assertEqual(self.temp.resolve().parent, self.test_root.resolve())
        shutil.rmtree(self.temp)

    def wait_done(self):
        self.lab.worker.join(5)
        self.assertFalse(self.lab.worker.is_alive())

    def test_roles_four_keys_topic_activity_and_persistence(self):
        self.lab.start(1, self.models, self.assignments)
        self.assertTrue(self.control.entered.wait(2))
        self.lab.intervene("초등학생도 따라 할 수 있는 평가 방법을 포함하세요.")
        self.lab.upload("../sample.csv", base64.b64encode("case,value\na,2\n".encode()).decode())
        self.lab.add_source("예시", "https://example.org/paper", "사용자 제공")
        waiting = self.lab.turn_detail(1)
        self.assertEqual(waiting["status"], "waiting")
        self.assertIn("현재 단계: role_selection", waiting["prompt"])
        self.control.release.set()
        self.wait_done()
        state = self.lab.public_state()
        self.assertEqual(state["status"], "completed", state["error"])
        self.assertEqual(state["topic"], "모델 협업 평가")
        self.assertEqual(len(self.control.calls), 12)
        self.assertEqual(len(state["roles"]), 4)
        self.assertEqual(len(state["activities"]), 12)
        self.assertEqual([item["status"] for item in state["activities"]], ["completed"] * 12)
        self.assertEqual({key for key, _, _, _ in self.control.calls},
                         {"OWNER_SECRET_TEST_KEY", "FRIEND_SECRET_TEST_KEY", "MEMBER3_SECRET_TEST_KEY", "MEMBER4_SECRET_TEST_KEY"})
        self.assertTrue(all(self.assignments[provider] == {"OWNER": "user", "FRIEND": "friend",
                                                             "MEMBER3": "member3", "MEMBER4": "member4"}[key.split("_", 1)[0]]
                            for key, provider, _, _ in self.control.calls))
        self.assertIn("초등학생도", self.control.calls[1][2])
        self.assertIn("case,value", self.control.calls[1][2])
        self.assertIn("example.org/paper", self.control.calls[1][2])
        self.assertEqual(state["datasets"], ["sample.csv"])
        self.assertTrue((self.lab.project / "research" / "role_selection.md").exists())
        self.assertTrue((self.lab.project / "results" / "discussion_draft.md").exists())
        self.assertIn("1415", (self.lab.project / "results" / "discussion_draft.md").read_text(encoding="utf-8"))
        self.assertEqual(len(list((self.lab.project / "data/raw/responses").glob("*.json"))), 12)
        self.assertEqual(self.lab.turn_detail(1)["status"], "completed")
        self.assertTrue(self.lab.turn_detail(1)["response"])
        self.assertIn("fake-1", self.lab.turn_detail(1)["raw_response"])
        self.assertIn("[API_KEY]", self.lab.turn_detail(1)["raw_response"])
        texts = "\n".join(p.read_text(encoding="utf-8-sig") for p in self.lab.project.rglob("*")
                          if p.is_file() and p.suffix in (".md", ".txt", ".json", ".jsonl", ".csv"))
        self.assertNotIn("OWNER_SECRET_TEST_KEY", texts)
        for key in ("FRIEND_SECRET_TEST_KEY", "MEMBER3_SECRET_TEST_KEY", "MEMBER4_SECRET_TEST_KEY"):
            self.assertNotIn(key, texts)
        self.assertNotIn("OWNER_SECRET_TEST_KEY", json.dumps(state))
        for key in ("FRIEND_SECRET_TEST_KEY", "MEMBER3_SECRET_TEST_KEY", "MEMBER4_SECRET_TEST_KEY"):
            self.assertNotIn(key, json.dumps(state))

    def test_exact_one_model_per_person_is_required(self):
        invalid = dict(self.assignments, gemini="user")
        with self.assertRaisesRegex(ValueError, "정확히 한 모델"):
            self.lab.start(1, self.models, invalid)
        invalid = dict(self.assignments, gpt="friend", claude="user")
        with self.assertRaisesRegex(ValueError, "담당 계정"):
            self.lab.start(1, self.models, invalid)
        self.assertIsNone(self.lab.project)

    def test_saved_keys_restore_after_recreating_lab(self):
        class MemoryStore:
            rows = {}
            def load_all(self):
                return dict(self.rows)
            def save(self, slot, key, models):
                self.rows[slot] = (key, models)
            def delete(self, slot):
                self.rows.pop(slot, None)

        store = MemoryStore()
        new_lab = Lab(lambda key, timeout: FakeClient(key, timeout, self.control), self.temp, store)
        for actor, key in (("user", "OWNER_SECRET_TEST_KEY"), ("friend", "FRIEND_SECRET_TEST_KEY"),
                           ("member3", "MEMBER3_SECRET_TEST_KEY"), ("member4", "MEMBER4_SECRET_TEST_KEY")):
            new_lab.connect(key, actor=actor)
        self.assertEqual(new_lab.public_state()["key_storage"], "persistent")
        restored = Lab(lambda key, timeout: FakeClient(key, timeout, self.control), self.temp, store)
        self.assertTrue(restored.public_state()["connected"])
        self.assertEqual(restored.clients["friend"].api_key, "FRIEND_SECRET_TEST_KEY")
        restored.disconnect("friend")
        self.assertNotIn("friend", store.rows)
        self.assertFalse(Lab(lambda key, timeout: FakeClient(key, timeout, self.control), self.temp, store)
                         .public_state()["connected"])

    def test_storage_failure_keeps_previous_key(self):
        class FailingStore:
            def load_all(self): return {}
            def save(self, slot, key, models): raise KeyStoreError("storage unavailable")
            def delete(self, slot): raise KeyStoreError("storage unavailable")

        lab = Lab(lambda key, timeout: FakeClient(key, timeout, self.control), self.temp, FailingStore())
        with self.assertRaises(KeyStoreError):
            lab.connect("FRIEND_SECRET_TEST_KEY", actor="friend")
        self.assertFalse(lab.public_state()["accounts"]["friend"]["connected"])

    def test_failed_call_is_visible_without_exposing_either_key(self):
        self.control.fail_on_call = 1
        self.lab.start(1, self.models, self.assignments)
        self.assertTrue(self.control.entered.wait(2))
        self.control.release.set()
        self.wait_done()
        state = self.lab.public_state()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["activities"][0]["status"], "failed")
        self.assertIn("[API_KEY]", state["error"])
        self.assertNotIn("OWNER_SECRET_TEST_KEY", json.dumps(state))
        self.assertNotIn("FRIEND_SECRET_TEST_KEY", json.dumps(state))
        self.assertNotIn("MEMBER3_SECRET_TEST_KEY", json.dumps(state))
        self.assertNotIn("MEMBER4_SECRET_TEST_KEY", json.dumps(state))
        detail = self.lab.turn_detail(1)
        self.assertEqual(detail["status"], "failed")
        self.assertNotIn("SECRET_TEST_KEY", json.dumps(detail))

    def test_pause_then_resume_at_turn_boundary(self):
        self.lab.start(1, self.models, self.assignments)
        self.assertTrue(self.control.entered.wait(2))
        self.lab.pause()
        self.control.release.set()
        time.sleep(.12)
        self.assertEqual(len(self.control.calls), 1)
        self.assertEqual(self.lab.public_state()["status"], "paused")
        self.lab.resume()
        self.wait_done()
        self.assertEqual(self.lab.public_state()["status"], "completed", self.lab.public_state()["error"])

    def test_model_swap_preserves_earlier_model_and_changes_later_turns(self):
        self.lab.start(1, self.models, self.assignments, step_mode=True)
        self.assertTrue(self.control.entered.wait(2))
        with self.assertRaisesRegex(ValueError, "일시정지"):
            self.lab.swap_model("gemini", "gemini-next", actor="friend")
        self.lab.pause()
        with self.assertRaisesRegex(ValueError, "응답"):
            self.lab.swap_model("gemini", "gemini-next", actor="friend")
        self.control.release.set()
        deadline = time.monotonic() + 3
        while any(item["status"] == "waiting" for item in self.lab.public_state()["activities"]) and time.monotonic() < deadline:
            time.sleep(.01)
        while not any(item["provider"] == "gemini" and item["status"] == "completed"
                      for item in self.lab.public_state()["activities"]):
            self.lab.resume()
            deadline = time.monotonic() + 3
            while self.lab.public_state()["status"] == "running" and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertLess(time.monotonic(), deadline)
        change = self.lab.swap_model("gemini", "gemini-next", actor="friend", reason="새 버전 비교")
        self.assertEqual(change["from"], "gemini-test")
        self.assertEqual(change["after_turn"], len(self.control.calls))
        with self.assertRaisesRegex(ValueError, "정확한 모델 ID"):
            self.lab.swap_model("gemini", "gemini-unknown", actor="friend")
        while self.lab.public_state()["status"] == "paused":
            self.lab.resume()
            deadline = time.monotonic() + 3
            while self.lab.public_state()["status"] == "running" and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertLess(time.monotonic(), deadline)
        self.wait_done()
        gemini = [item for item in self.lab.activities if item["provider"] == "gemini"]
        self.assertEqual(gemini[0]["model"], "gemini-test")
        self.assertTrue(all(item["model"] == "gemini-next" for item in gemini[1:]))
        self.assertEqual(self.lab.public_state()["model_changes"], [change])
        self.assertIn("gemini-next", (self.lab.project / "manifest.json").read_text(encoding="utf-8"))

    def test_project_checkpoint_restores_paused_research_without_repeating_completed_call(self):
        class MemoryProjectStore:
            def __init__(self):
                self.snapshot = None
                self.files = {}
            def save(self, project, snapshot):
                self.snapshot = copy.deepcopy(snapshot)
                self.files = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            def load(self, target):
                if self.snapshot is None:
                    return None
                project = target / self.snapshot["project_name"]
                for relative, data in self.files.items():
                    path = project / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                return copy.deepcopy(self.snapshot)
        store = MemoryProjectStore()
        self.lab.project_store = store
        self.lab.start(1, self.models, self.assignments, step_mode=True)
        self.assertTrue(self.control.entered.wait(2))
        self.control.release.set()
        deadline = time.monotonic() + 3
        while self.lab.public_state()["status"] != "paused" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(self.control.calls), 1)
        self.lab.intervene("데이터 출처 확인", actor="member4")
        self.lab.upload("evidence.csv", base64.b64encode(b"x,y\n1,2\n").decode())
        self.lab.project_store = None
        self.lab.stop()
        self.lab.worker.join(5)
        restored = Lab(lambda key, timeout: FakeClient(key, timeout, self.control), self.temp, project_store=store)
        for actor, client in self.lab.clients.items():
            restored.clients[actor] = client
        restored.assignments = dict(self.assignments)
        self.assertEqual(restored.public_state()["status"], "paused")
        self.assertEqual(restored.public_state()["datasets"], ["evidence.csv"])
        self.assertTrue(any("데이터 출처" in msg["content"] for msg in restored.messages))
        restored.swap_model("gemini", "gemini-next", actor="user")
        restored.step_mode = False
        restored.resume()
        restored.worker.join(5)
        self.assertEqual(restored.status, "completed", restored.error)
        self.assertEqual(len(self.control.calls), 12)
        self.assertEqual(len([a for a in restored.activities if a["status"] == "completed"]), 12)

    def test_failed_model_swap_does_not_claim_new_model(self):
        class FailingProjectStore:
            def save(self, project, snapshot):
                raise KeyStoreError("연구 저장소 오류")
        self.lab.start(1, self.models, self.assignments, step_mode=True)
        self.assertTrue(self.control.entered.wait(2))
        self.control.release.set()
        deadline = time.monotonic() + 3
        while self.lab.public_state()["status"] != "paused" and time.monotonic() < deadline:
            time.sleep(.01)
        self.lab.project_store = FailingProjectStore()
        before = (self.lab.project / "data/raw/conversation.jsonl").read_bytes()
        with self.assertRaises(KeyStoreError):
            self.lab.swap_model("gemini", "gemini-next", actor="user")
        self.assertEqual(self.lab.models["gemini"], "gemini-test")
        self.assertEqual(self.lab.model_changes, [])
        self.assertEqual((self.lab.project / "data/raw/conversation.jsonl").read_bytes(), before)
        self.lab.project_store = None
        self.lab.stop()

    def test_stop_at_turn_boundary(self):
        self.lab.start(1, self.models, self.assignments)
        self.assertTrue(self.control.entered.wait(2))
        self.lab.stop()
        self.control.release.set()
        self.wait_done()
        self.assertEqual(len(self.control.calls), 1)
        self.assertEqual(self.lab.public_state()["status"], "stopped")

    def test_step_mode_waits_for_people_between_models(self):
        self.lab.start(1, self.models, self.assignments, step_mode=True)
        self.assertTrue(self.control.entered.wait(2))
        self.control.release.set()
        deadline = time.monotonic() + 2
        while self.lab.public_state()["status"] != "paused" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.lab.public_state()["status"], "paused")
        self.assertEqual(len(self.control.calls), 1)
        self.lab.intervene("다음 모델은 대조군도 제시하세요.", actor="friend")
        self.lab.resume()
        deadline = time.monotonic() + 2
        while len(self.control.calls) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(self.control.calls), 2)
        self.assertIn("대조군도", self.control.calls[1][2])
        self.lab.stop()
        self.wait_done()

    def test_frontend_references_existing_controls(self):
        web = Path(__file__).resolve().parents[1] / "web"
        html = (web / "index.html").read_text(encoding="utf-8")
        script = (web / "app.js").read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([^"]+)"', html))
        refs = set(re.findall(r'\$\("([^"]+)"\)', script))
        self.assertFalse(refs - ids, f"Missing HTML controls: {refs - ids}")
        self.assertEqual(ACCOUNT_LABELS, {"user": "1415", "friend": "1314", "member3": "1410", "member4": "1411"})
        self.assertEqual(CLOUD_USERS, ACCOUNT_LABELS)
        for label in ACCOUNT_LABELS.values():
            self.assertIn(label, html)
            self.assertIn(label, script)
        for slot in ACCOUNT_LABELS:
            self.assertIn('id="apiKey-' + slot + '"', html)
        for old_label in ("연구자", "친구", "참여자 3", "참여자 4"):
            self.assertNotIn(old_label, html + script)

    def test_friend_connects_own_key_and_has_full_shared_controls(self):
        ViewerHandler.lab = self.lab
        ViewerHandler.password = "test-pass"
        server = ThreadingHTTPServer(("127.0.0.1", 0), ViewerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{server.server_port}"
        auth = "Basic " + base64.b64encode(b"viewer:test-pass").decode()

        def send(path, data, origin=None, host=None):
            headers = {"Authorization": auth, "Content-Type": "application/json", "Origin": origin or root}
            if host:
                headers["Host"] = host
            request = Request(root + path, data=json.dumps(data).encode(), method="POST", headers=headers)
            with urlopen(request) as response:
                return json.load(response)

        try:
            with self.assertRaises(HTTPError) as unauth:
                urlopen(root + "/api/state")
            self.assertEqual(unauth.exception.code, 401)
            connected = send("/api/connect", {"key": "FRIEND_REPLACED_KEY"})
            self.assertEqual(connected["actor"], "friend")
            self.assertEqual(self.lab.clients["user"].api_key, "OWNER_SECRET_TEST_KEY")
            self.assertEqual(self.lab.clients["friend"].api_key, "FRIEND_REPLACED_KEY")
            disconnected = send("/api/disconnect", {})
            self.assertTrue(disconnected["accounts"]["user"]["connected"])
            self.assertFalse(disconnected["accounts"]["friend"]["connected"])
            self.assertNotIn("friend", self.lab.clients)
            send("/api/connect", {"key": "FRIEND_REPLACED_KEY"})
            with urlopen(Request(root + "/api/state", headers={"Authorization": auth})) as response:
                state = json.load(response)
            self.assertEqual(state["self_actor"], "friend")
            self.assertTrue(state["connected"])
            self.assertNotIn("OWNER_SECRET_TEST_KEY", json.dumps(state))
            self.assertNotIn("FRIEND_REPLACED_KEY", json.dumps(state))
            with urlopen(Request(root + "/", headers={"Authorization": auth})) as response:
                self.assertIn("공동 연구 채팅", response.read().decode())
            with self.assertRaises(HTTPError) as denied:
                send("/api/start", {"rounds":1,"models":self.models,"assignments":self.assignments}, "https://wrong.example")
            self.assertEqual(denied.exception.code, 403)
            started = send("/api/start", {"rounds":1,"models":self.models,"assignments":self.assignments})
            self.assertEqual(started["status"], "running")
            self.assertTrue(self.control.entered.wait(2))
            with self.assertRaises(HTTPError) as disconnect_while_running:
                send("/api/disconnect", {})
            self.assertEqual(disconnect_while_running.exception.code, 400)
            sent = send("/api/intervene", {"content":"친구의 연구 의견"})
            self.assertEqual(sent["actor"], "friend")
            remote_sent = send("/api/intervene", {"content":"원격 링크 의견"},
                               origin="https://lab.example.test", host="lab.example.test")
            self.assertEqual(remote_sent["actor"], "friend")
            send("/api/upload", {"filename":"friend.csv","content":base64.b64encode(b"a,b\n1,2\n").decode()})
            send("/api/source", {"title":"friend source","url":"https://example.org/friend","note":"test"})
            with urlopen(Request(root + "/api/turn/1", headers={"Authorization":auth})) as response:
                detail = json.load(response)
            self.assertEqual(detail["account"], self.assignments[detail["provider"]])
            self.assertIn("현재 단계: role_selection", detail["prompt"])
            with urlopen(Request(root + "/api/archive", headers={"Authorization":auth})) as response:
                with ZipFile(BytesIO(response.read())) as archive:
                    self.assertIn("datasets/friend.csv", archive.namelist())
                    self.assertIn("data/raw/conversation.jsonl", archive.namelist())
            self.assertEqual(send("/api/pause", {})["status"], "paused")
            self.assertEqual(send("/api/resume", {})["status"], "running")
            self.assertEqual(send("/api/stop", {})["status"], "stopping")
            self.control.release.set()
            self.wait_done()
        finally:
            self.control.release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_cloud_roles_auth_host_and_origin(self):
        CloudHandler.lab = self.lab
        CloudHandler.public_host = "lab.example.test"
        CloudHandler.passwords = {
            "user": "owner-password-at-least-20-characters",
            "friend": "friend-password-at-least-20-characters",
            "member3": "member3-password-at-least-20-characters",
            "member4": "member4-password-at-least-20-characters",
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), CloudHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{server.server_port}"

        def headers(name, password, origin=None, host="lab.example.test"):
            auth = "Basic " + base64.b64encode(f"{name}:{password}".encode()).decode()
            result = {"Host": host, "Authorization": auth}
            if origin is not None:
                result["Origin"] = origin
            return result

        try:
            with urlopen(Request(root + "/healthz", headers={"Host": "lab.example.test"})) as response:
                self.assertTrue(json.load(response)["ok"])
            with self.assertRaises(HTTPError) as unauth:
                urlopen(Request(root + "/api/state", headers={"Host": "lab.example.test"}))
            self.assertEqual(unauth.exception.code, 401)
            with self.assertRaises(HTTPError) as old_name:
                urlopen(Request(root + "/api/state", headers=headers("owner", CloudHandler.passwords["user"])))
            self.assertEqual(old_name.exception.code, 401)
            for actor, password in CloudHandler.passwords.items():
                name = CLOUD_USERS[actor]
                with urlopen(Request(root + "/api/state", headers=headers(name, password))) as response:
                    state = json.load(response)
                self.assertEqual(state["self_actor"], actor)
                self.assertNotIn("OWNER_SECRET_TEST_KEY", json.dumps(state))
                self.assertNotIn("FRIEND_SECRET_TEST_KEY", json.dumps(state))
                self.assertNotIn("MEMBER3_SECRET_TEST_KEY", json.dumps(state))
                self.assertNotIn("MEMBER4_SECRET_TEST_KEY", json.dumps(state))
            with self.assertRaises(HTTPError) as wrong_host:
                urlopen(Request(root + "/api/state", headers=headers("1415", CloudHandler.passwords["user"], host="evil.test")))
            self.assertEqual(wrong_host.exception.code, 403)
            with self.assertRaises(HTTPError) as wrong_origin:
                request = Request(root + "/api/disconnect", data=b"{}", method="POST",
                                  headers={**headers("1314", CloudHandler.passwords["friend"], "https://evil.test"),
                                           "Content-Type": "application/json"})
                urlopen(request)
            self.assertEqual(wrong_origin.exception.code, 403)
            request = Request(root + "/api/disconnect", data=b"{}", method="POST",
                              headers={**headers("1314", CloudHandler.passwords["friend"], "https://lab.example.test"),
                                       "Content-Type": "application/json"})
            with urlopen(request) as response:
                state = json.load(response)
            self.assertTrue(state["accounts"]["user"]["connected"])
            self.assertFalse(state["accounts"]["friend"]["connected"])
            self.assertTrue(state["accounts"]["member3"]["connected"])
            self.assertTrue(state["accounts"]["member4"]["connected"])
            for actor in ("member3", "member4"):
                name = CLOUD_USERS[actor]
                request = Request(root + "/api/connect", data=json.dumps({"key": actor.upper() + "_REPLACED_KEY"}).encode(), method="POST",
                                  headers={**headers(name, CloudHandler.passwords[actor], "https://lab.example.test"),
                                           "Content-Type": "application/json"})
                with urlopen(request) as response:
                    connected = json.load(response)
                self.assertEqual(connected["actor"], actor)
                self.assertEqual(self.lab.clients[actor].api_key, actor.upper() + "_REPLACED_KEY")
            request = Request(root + "/api/connect",
                              data=json.dumps({"slot":"user", "key":"OWNER_REPLACED_KEY"}).encode(), method="POST",
                              headers={**headers("1314", CloudHandler.passwords["friend"], "https://lab.example.test"),
                                       "Content-Type": "application/json"})
            with urlopen(request) as response:
                self.assertEqual(json.load(response)["actor"], "user")
            self.assertEqual(self.lab.clients["user"].api_key, "OWNER_REPLACED_KEY")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_cloud_login_page_session_and_logout(self):
        CloudHandler.lab = self.lab
        CloudHandler.public_host = "lab.example.test"
        CloudHandler.passwords = {actor: f"{label}-long-test-password-123456789" for actor, label in CLOUD_USERS.items()}
        CloudHandler.session_key = hashlib.sha256("\x00".join(CloudHandler.passwords[actor] for actor in ("user", "friend", "member3", "member4")).encode()).digest()
        server = ThreadingHTTPServer(("127.0.0.1", 0), CloudHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, path, body=None, cookie=None, origin="https://lab.example.test", host="lab.example.test", extra=None):
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"Host": host}
            if origin is not None and method == "POST":
                headers["Origin"] = origin
            if cookie:
                headers["Cookie"] = cookie
            if body is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers.update(extra or {})
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
            connection.close()
            return result

        try:
            status, headers, _ = request("GET", "/")
            self.assertEqual((status, headers.get("Location")), (303, "/login"))
            status, login_headers, page = request("GET", "/login")
            self.assertEqual(status, 200)
            for label in CLOUD_USERS.values():
                self.assertIn(label.encode(), page)
            self.assertNotIn(b"password-123456789", page)
            csrf = re.search(rb'name="csrf" value="([^"]+)"', page).group(1).decode()
            login_cookie = login_headers["Set-Cookie"].split(";", 1)[0]
            self.assertIn("Secure; HttpOnly; SameSite=Strict", login_headers["Set-Cookie"])
            self.assertIn(b'<script src="/login.js" defer>', page)
            self.assertEqual(request("GET", "/login.js")[0], 200)
            self.assertEqual(request("GET", "/api/state")[0], 401)
            self.assertEqual(request("POST", "/login", urlencode({"account":"1415", "password":"wrong", "csrf":csrf}), cookie=login_cookie)[0], 303)
            self.assertEqual(request("POST", "/login", urlencode({"account":"1415", "password":CloudHandler.passwords["user"], "csrf":csrf}), origin="https://evil.test")[0], 403)
            self.assertEqual(request("POST", "/login", urlencode({"account":"1415", "password":CloudHandler.passwords["user"], "csrf":"tampered"}), cookie=login_cookie, origin=None)[0], 403)
            header = {"X-RE-Lab-CSRF": csrf, "Sec-Fetch-Site": "same-origin"}
            self.assertEqual(request("POST", "/login", urlencode({"account":"1415", "password":CloudHandler.passwords["user"], "csrf":csrf}), origin="null", extra=header)[0], 303)
            self.assertEqual(request("POST", "/login", urlencode({"account":"1415", "password":CloudHandler.passwords["user"], "csrf":csrf}), origin="null")[0], 403)
            self.assertEqual(request("POST", "/login", urlencode({"account":"1415", "password":CloudHandler.passwords["user"], "csrf":csrf}), origin="https://evil.test", extra=header)[0], 403)
            for actor, label in CLOUD_USERS.items():
                body = urlencode({"account":label, "password":CloudHandler.passwords[actor], "csrf":csrf})
                status, headers, _ = request("POST", "/login", body, cookie=login_cookie, origin="null")
                self.assertEqual((status, headers.get("Location")), (303, "/"))
                cookie = headers["Set-Cookie"].split(";", 1)[0]
                self.assertIn("Secure; HttpOnly; SameSite=Lax", headers["Set-Cookie"])
                status, _, state = request("GET", "/api/state", cookie=cookie)
                self.assertEqual(status, 200)
                state = json.loads(state)
                self.assertEqual(state["self_actor"], actor)
                self.assertTrue(state["cloud"])
                self.assertTrue(state["csrf_token"])
                self.assertEqual(request("GET", "/", cookie=cookie)[0], 200)
                if actor == "user":
                    status, _, result = request("POST", "/api/connect", '{"slot":"user","key":"OWNER_COOKIE_TEST_KEY"}', cookie=cookie,
                                                origin="null", extra={"X-RE-Lab-CSRF":state["csrf_token"], "Content-Type":"application/json"})
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(result)["actor"], "user")
                    status, _, result = request("POST", "/api/disconnect", '{"slot":"friend"}', cookie=cookie,
                                                origin=None, extra={"X-RE-Lab-CSRF":state["csrf_token"], "Content-Type":"application/json"})
                    self.assertEqual(status, 200)
                    self.assertFalse(json.loads(result)["accounts"]["friend"]["connected"])
                tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")
                self.assertEqual(request("GET", "/api/state", cookie=tampered)[0], 401)
                self.assertEqual(request("POST", "/logout", cookie=cookie, origin=None, extra={"X-RE-Lab-CSRF":"wrong"})[0], 403)
                status, headers, _ = request("POST", "/logout", cookie=cookie, origin=None, extra={"X-RE-Lab-CSRF":state["csrf_token"]})
                self.assertEqual((status, headers.get("Location")), (303, "/login"))
                self.assertIn("Max-Age=0", headers["Set-Cookie"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()

