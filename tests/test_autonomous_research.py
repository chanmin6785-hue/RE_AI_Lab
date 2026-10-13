import json
import copy
from pathlib import Path
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from pptx import Presentation
from docx import Document

from app import Lab, next_credit_check
from baze_models import BazeError, Reply


class ResearchClient:
    calls = []
    balance = 8000
    monthly_balance = None

    def __init__(self, key, timeout):
        self.api_key = key

    def list_models(self):
        return ["gpt-test", "claude-test", "gemini-test", "grok-test"]

    def credits(self):
        amount = type(self).balance
        monthly = type(self).monthly_balance
        return {"monthly_allocated": {"remaining": amount if monthly is None else monthly},
                "total": {"remaining": amount}}

    def ask(self, provider, prompt, model, max_tokens):
        type(self).calls.append((provider, prompt, model))
        phase = prompt.split("단계: ", 1)[1].split(";", 1)[0] if "단계: " in prompt else ""
        text = {
            "role_selection": "MY_ROLE: 실험 설계\n" + "\n".join(
                f"ROLE_{name.upper()}: 검증과 분석" for name in ("gpt", "claude", "gemini", "grok")),
            "topic_selection": "RESEARCH_TOPIC: 네 모델 답변 비교\nRESEARCH_QUESTION: 동일 질문에 대한 응답은 어떻게 다른가?",
            "plan_discussion": "대조군과 재현 방법을 검토한다.\nNEXT: DRAFT",
            "plan_report": "# 연구계획보고서\n\nAI 생성 사례를 쓰고 실제 모델 응답을 관찰한다.",
            "plan_slides": "SLIDE 1: 연구 질문\n- 동일 질문의 응답 차이\nSLIDE 2: 실험 계획\n- 네 모델 독립 호출",
            "plan_script": "# 계획발표 대본\n첫 장은 연구 질문입니다.",
            "experiment_discussion": "대조군을 유지한다.\nNEXT: CASES" if "실험 주기: 1" in prompt and "실험 분석 자료: 아직" in prompt else (
                "결과를 중간 발표에서 검토한다.\nNEXT: MIDDLE" if "실험 주기: 1" in prompt else (
                    "새 사례로 재검증한다.\nNEXT: CASES" if "실험 분석 자료: 아직" in prompt else "최종 검토로 간다.\nNEXT: FINAL")),
            "experiment_cases": 'CASES_JSON: [{"prompt":"2+2는?", "expected":"4", "source_note":"AI 생성"}]',
            "experiment_analysis": "# 실제 응답 해석\n문자 수는 품질이 아니다.",
            "middle_slides": "SLIDE 1: 중간 결과\n- 실제 모델 응답을 수집했다.",
            "middle_script": "# 중간발표 대본\n관찰값을 설명합니다.",
            "final_discussion": "증거와 한계를 확인했다.\nNEXT: FINAL",
            "final_report": "# 최종 연구보고서\n실제 모델 응답과 AI 생성 사례를 구분한다.",
            "final_slides": "SLIDE 1: 최종 결과\n- 관찰값과 한계",
            "final_script": "# 최종발표 대본\n결과와 한계를 발표합니다.",
        }.get(phase, "4")
        return Reply(provider, model, text, {"input_tokens": 10}, {"id": f"fake-{len(type(self).calls)}"})


class AutonomousResearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(__file__).resolve().parent / ("auto_test_" + uuid4().hex)
        self.temp.mkdir()
        ResearchClient.calls = []
        ResearchClient.balance = 8000
        ResearchClient.monthly_balance = None
        self.lab = Lab(ResearchClient, self.temp)
        for actor in ("user", "friend", "member3", "member4"):
            self.lab.connect("KEY_" + actor, actor=actor)
        self.models = {name: name + "-test" for name in ("gpt", "claude", "gemini", "grok")}
        self.assignments = dict(zip(self.models, ("user", "friend", "member3", "member4")))

    def tearDown(self):
        if self.lab.worker:
            self.lab.worker.join(5)
        shutil.rmtree(self.temp)

    def advance_until(self, status, limit=40):
        for _ in range(limit):
            if self.lab.worker:
                self.lab.worker.join(5)
            if self.lab.status == status:
                return
            self.lab.auto["last_wake_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            self.lab.auto_wake()
        self.fail(f"did not reach {status}: {self.lab.status} {self.lab.auto.get('stage')} {self.lab.error}")

    def test_plan_middle_final_revisions_real_evidence_and_pptx(self):
        self.lab.start(None, self.models, self.assignments)
        self.advance_until("waiting_review")
        self.assertEqual(self.lab.auto["stage"], "plan_review")
        self.assertEqual(len(self.lab.deliverables()), 5)
        report = self.lab.project / "presentations" / "plan" / "report.docx"
        self.assertIn("연구계획보고서", " ".join(p.text for p in Document(str(report)).paragraphs))
        plan = self.lab.project / "presentations" / "plan" / "slides.pptx"
        self.assertGreaterEqual(len(Presentation(str(plan)).slides), 3)
        self.assertEqual(len(self.lab.auto["observations"]), 0)
        self.lab.review("plan_review", False, "대조 조건을 더 명확히", "friend")
        self.advance_until("waiting_review")
        self.assertEqual(self.lab.auto["stage"], "plan_review")
        self.assertEqual(self.lab.auto["revision"]["plan"], 2)
        self.lab.review("plan_review", True, "계획 확인", "user")
        self.advance_until("waiting_review")
        self.assertEqual(self.lab.auto["stage"], "middle_review")
        self.assertGreater(len(self.lab.auto["observations"]), 0)
        self.assertTrue((self.lab.project / "data/processed/observations.jsonl").exists())
        cases = (self.lab.project / "datasets/cycle_01_ai_generated_cases.jsonl").read_text(encoding="utf-8")
        self.assertIn("AI_GENERATED", cases)
        analysis = json.loads((self.lab.project / "results/cycle_01_analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(analysis["evidence"], "OBSERVED_BAZE")
        self.lab.review("middle_review", True, "중간 검토 완료", "member3")
        self.advance_until("waiting_review")
        self.assertEqual(self.lab.auto["stage"], "final_review")
        self.assertTrue((self.lab.project / "presentations/final/report.md").exists())
        self.lab.review("final_review", True, "최종 검토 완료", "member4")
        self.assertEqual(self.lab.status, "completed")
        self.assertEqual([row["stage"] for row in self.lab.auto["reviews"]],
                         ["plan_review", "plan_review", "middle_review", "final_review"])

    def test_low_credit_waits_without_paid_call(self):
        ResearchClient.balance = 0
        self.lab.start(None, self.models, self.assignments)
        self.lab.worker.join(5)
        self.assertEqual(self.lab.status, "waiting_budget")
        self.assertEqual(ResearchClient.calls, [])
        self.assertTrue(self.lab.auto["next_due_at"])
        self.lab.auto_wake()
        self.assertEqual(ResearchClient.calls, [])
        ResearchClient.balance = 8000
        self.lab.auto["next_due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.lab.auto["last_wake_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.lab.auto_wake()
        self.lab.worker.join(5)
        self.assertGreater(len(ResearchClient.calls), 0)

    def test_next_credit_check_uses_upcoming_midnight_window(self):
        kst = ZoneInfo("Asia/Seoul")
        day = datetime(2026, 10, 14, 0, 5, tzinfo=kst)
        self.assertEqual(next_credit_check(day), datetime(2026, 10, 14, 0, 10, tzinfo=kst))
        self.assertEqual(next_credit_check(day + timedelta(minutes=10)),
                         datetime(2026, 10, 15, 0, 10, tzinfo=kst))

    def test_positive_total_credit_allows_calls_even_when_monthly_is_zero(self):
        ResearchClient.balance = 1
        ResearchClient.monthly_balance = 0
        self.lab.start(None, self.models, self.assignments)
        self.lab.worker.join(5)
        self.assertGreater(len(ResearchClient.calls), 0)
        self.assertNotEqual(self.lab.status, "waiting_budget")

    def test_gateway_credit_rejection_waits_then_retries_with_new_audit_number(self):
        ResearchClient.balance = 1
        for client in self.lab.clients.values():
            client.ask = lambda *args, **kwargs: (_ for _ in ()).throw(BazeError("HTTP 402: insufficient credits"))
        self.lab.start(None, self.models, self.assignments)
        self.lab.worker.join(5)
        self.assertEqual(self.lab.status, "waiting_budget")
        self.assertEqual(self.lab.activities[-1]["status"], "failed")
        failed_turn = self.lab.activities[-1]["turn"]
        for client in self.lab.clients.values():
            del client.ask
        self.lab.auto["next_due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.lab.auto["last_wake_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.lab.auto_wake()
        self.lab.worker.join(5)
        self.assertGreater(len(ResearchClient.calls), 0)
        self.assertGreater(self.lab.activities[-1]["turn"], failed_turn)

    def test_overview_reads_complete_archived_dialogue(self):
        self.lab.start(None, self.models, self.assignments)
        self.advance_until("waiting_review")
        with self.lab.lock:
            for number in range(205):
                self.lab._append("system", f"기록 확인 {number}")
        overview = self.lab.research_overview()
        self.assertGreater(overview["counts"]["all"], len(self.lab.messages))
        self.assertEqual(overview["counts"]["models"], len(ResearchClient.calls))
        self.assertTrue(any(section["key"] == "roles" for section in overview["sections"]))
        self.assertEqual(len(overview["roles"]), 4)
        self.assertIn("검토", overview["current"]["task"])

    def test_restore_recreates_empty_folders_and_missing_role_file(self):
        self.lab.start(None, self.models, self.assignments)
        self.lab.worker.join(5)
        self.assertEqual(self.lab.auto["stage"], "topic")
        snapshot = copy.deepcopy(self.lab._snapshot())
        snapshot["status"] = "waiting_budget"
        snapshot["error"] = "[Errno 2] No such file or directory: 'research/role_selection.md'"
        files = {path.relative_to(self.lab.project): path.read_bytes()
                 for path in self.lab.project.rglob("*") if path.is_file()
                 and path.name != "role_selection.md"}

        class MissingRoleStore:
            def load(self, target):
                project = target / snapshot["project_name"]
                for relative, content in files.items():
                    path = project / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                return copy.deepcopy(snapshot)

            def save(self, project, state):
                files.update({path.relative_to(project): path.read_bytes()
                              for path in project.rglob("*") if path.is_file()})

        restored = Lab(ResearchClient, self.temp / "restored", project_store=MissingRoleStore())
        role_file = restored.project / "research" / "role_selection.md"
        self.assertTrue(role_file.exists())
        self.assertIn("GPT", role_file.read_text(encoding="utf-8"))
        self.assertIn(Path("research/role_selection.md"), files)
        self.assertEqual(restored.error, "")
        self.assertTrue((restored.project / "presentations" / "final").is_dir())


if __name__ == "__main__":
    unittest.main()
