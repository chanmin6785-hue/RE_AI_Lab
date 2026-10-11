import base64
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
from uuid import uuid4
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Lab, ViewerHandler, CloudHandler
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
        return [f"{provider}-test"]

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
            for actor, name, password in (("user", "owner", CloudHandler.passwords["user"]),
                                          ("friend", "friend", CloudHandler.passwords["friend"]),
                                          ("member3", "member3", CloudHandler.passwords["member3"]),
                                          ("member4", "member4", CloudHandler.passwords["member4"])):
                with urlopen(Request(root + "/api/state", headers=headers(name, password))) as response:
                    state = json.load(response)
                self.assertEqual(state["self_actor"], actor)
                self.assertNotIn("OWNER_SECRET_TEST_KEY", json.dumps(state))
                self.assertNotIn("FRIEND_SECRET_TEST_KEY", json.dumps(state))
                self.assertNotIn("MEMBER3_SECRET_TEST_KEY", json.dumps(state))
                self.assertNotIn("MEMBER4_SECRET_TEST_KEY", json.dumps(state))
            with self.assertRaises(HTTPError) as wrong_host:
                urlopen(Request(root + "/api/state", headers=headers("owner", CloudHandler.passwords["user"], host="evil.test")))
            self.assertEqual(wrong_host.exception.code, 403)
            with self.assertRaises(HTTPError) as wrong_origin:
                request = Request(root + "/api/disconnect", data=b"{}", method="POST",
                                  headers={**headers("friend", CloudHandler.passwords["friend"], "https://evil.test"),
                                           "Content-Type": "application/json"})
                urlopen(request)
            self.assertEqual(wrong_origin.exception.code, 403)
            request = Request(root + "/api/disconnect", data=b"{}", method="POST",
                              headers={**headers("friend", CloudHandler.passwords["friend"], "https://lab.example.test"),
                                       "Content-Type": "application/json"})
            with urlopen(request) as response:
                state = json.load(response)
            self.assertTrue(state["accounts"]["user"]["connected"])
            self.assertFalse(state["accounts"]["friend"]["connected"])
            self.assertTrue(state["accounts"]["member3"]["connected"])
            self.assertTrue(state["accounts"]["member4"]["connected"])
            for actor in ("member3", "member4"):
                name = actor
                request = Request(root + "/api/connect", data=json.dumps({"key": actor.upper() + "_REPLACED_KEY"}).encode(), method="POST",
                                  headers={**headers(name, CloudHandler.passwords[actor], "https://lab.example.test"),
                                           "Content-Type": "application/json"})
                with urlopen(request) as response:
                    connected = json.load(response)
                self.assertEqual(connected["actor"], actor)
                self.assertEqual(self.lab.clients[actor].api_key, actor.upper() + "_REPLACED_KEY")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()

