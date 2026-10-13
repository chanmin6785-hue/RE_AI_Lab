"""Offline tests only. No API credentials or network calls."""
import contextlib
import io
import json
import os
import ssl
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import baze_models as bm


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("Unexpected request: " + request.full_url)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())

    def body(self, index=0):
        return json.loads(self.requests[index][0].data)


def gpt_reply(text="안녕하세요", response_id="resp_1", status="completed"):
    return {"id": response_id, "status": status, "model": "gpt-test",
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"output_tokens": 3}}


def claude_reply(text="안녕하세요"):
    return {"model": "claude-test", "stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": "internal", "signature": "signature-claude"},
        {"type": "text", "text": text}], "usage": {"input_tokens": 7}}


def gemini_reply():
    return {"modelVersion": "gemini-test", "candidates": [{"finishReason": "STOP", "content": {
        "role": "model", "parts": [{"text": "internal", "thought": True},
                                   {"text": "안녕하세요", "thoughtSignature": "signature-gemini"}]
    }}], "usageMetadata": {"totalTokenCount": 17}}


def grok_reply(text="안녕하세요"):
    return {"model": "grok-test", "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": text}}], "usage": {"total_tokens": 8}}


class BazeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "BAZE_API_KEY": "test-key-only", "BAZE_GPT_MODEL": "",
            "BAZE_CLAUDE_MODEL": "", "BAZE_GEMINI_MODEL": "", "BAZE_GROK_MODEL": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        # Fail closed if any test accidentally reaches an unmocked network path.
        self.network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def client(self, *responses):
        client = bm.BazeClient()
        fake = FakeOpener(*responses)
        client._opener = fake
        return client, fake

    def test_all_four_wire_routes_and_text(self):
        cases = [
            ("gpt", gpt_reply(), "/responses/"),
            ("claude", claude_reply(), "/claude/v1/messages/"),
            ("gemini", gemini_reply(), "/gemini/v1beta/models/gemini-3.8-flash:generateContent"),
            ("grok", grok_reply(), "/chat/completions/"),
        ]
        for provider, raw, route in cases:
            with self.subTest(provider=provider):
                client, fake = self.client(raw)
                reply = client.ask(provider, "한글 질문")
                self.assertEqual(reply.text, "안녕하세요")
                self.assertEqual(reply.raw, raw)
                request, timeout = fake.requests[0]
                self.assertEqual(request.full_url, bm.BASE_URL + route)
                self.assertEqual(request.method, "POST")
                self.assertEqual(request.get_header("Authorization"), "Bearer test-key-only")
                self.assertIn("한글 질문", request.data.decode("utf-8"))
                self.assertNotIn("test-key-only", request.data.decode("utf-8"))
                self.assertEqual(timeout, 120.0)
                if provider == "claude":
                    self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")

    def test_gpt_chain_and_reset(self):
        client, fake = self.client(gpt_reply(), gpt_reply(response_id="resp_2"), gpt_reply(response_id="resp_3"))
        chat = client.chat("gpt", system="시스템")
        chat.ask("첫 질문")
        chat.ask("다음 질문")
        self.assertEqual(fake.body(1)["previous_response_id"], "resp_1")
        self.assertEqual(fake.body(1)["input"], [{"role": "user", "content": "다음 질문"}])
        self.assertEqual(fake.body(1)["instructions"], "시스템")
        chat.reset()
        chat.ask("새 질문")
        self.assertNotIn("previous_response_id", fake.body(2))

    def test_claude_preserves_signed_content(self):
        client, fake = self.client(claude_reply(), claude_reply())
        chat = client.chat("claude")
        first = chat.ask("첫 질문")
        first.raw["content"][0]["signature"] = "caller-mutation"
        chat.ask("다음 질문")
        self.assertEqual(fake.body(1)["messages"][1]["content"][0]["signature"], "signature-claude")
        self.assertEqual(len(fake.body(1)["messages"]), 3)

    def test_claude_thinking_exhausts_output_budget_without_text(self):
        exhausted = {"model": "claude-test", "stop_reason": "max_tokens",
                     "content": [{"type": "thinking", "thinking": "partial", "signature": "signed"}],
                     "usage": {"output_tokens": 3000}}
        client, fake = self.client(exhausted)
        chat = client.chat("claude", max_tokens=3000)
        with self.assertRaises(bm.BazeOutputLimitError) as raised:
            chat.ask("연구 계획을 검토하세요")
        self.assertEqual(raised.exception.raw, exhausted)
        self.assertEqual(chat._history, [])
        self.assertEqual(fake.body()["max_tokens"], 3000)

    def test_gemini_preserves_signature_hides_thought_and_reset(self):
        client, fake = self.client(gemini_reply(), gemini_reply(), gemini_reply())
        chat = client.chat("gemini", system="시스템")
        first = chat.ask("첫 질문")
        self.assertNotIn("internal", first.text)
        first.raw["candidates"][0]["content"]["parts"][1]["thoughtSignature"] = "caller-mutation"
        chat.ask("다음 질문")
        self.assertEqual(fake.body(1)["contents"][1]["parts"][1]["thoughtSignature"], "signature-gemini")
        self.assertIn("systemInstruction", fake.body(1))
        chat.reset()
        chat.ask("새 질문")
        self.assertEqual(len(fake.body(2)["contents"]), 1)

    def test_grok_two_turn_context(self):
        client, fake = self.client(grok_reply(), grok_reply())
        chat = client.chat("grok", system="시스템")
        chat.ask("첫 질문")
        chat.ask("다음 질문")
        self.assertEqual([m["role"] for m in fake.body(1)["messages"]], ["system", "user", "assistant", "user"])

    def test_http_error_no_retry_no_history_and_redacted_key(self):
        error = HTTPError("https://example.invalid", 429, "Rate limit", {"Retry-After": "5"},
                          io.BytesIO(b'{"detail":{"message":"test-key-only limit"}}'))
        client, fake = self.client(error, grok_reply())
        chat = client.chat("grok")
        with self.assertRaises(bm.BazeError) as raised:
            chat.ask("실패할 질문")
        self.assertNotIn("test-key-only", str(raised.exception))
        self.assertIn("Retry-After: 5", str(raised.exception))
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(chat._history, [])
        chat.ask("다시 질문")
        self.assertNotIn("실패할 질문", json.dumps(fake.body(1), ensure_ascii=False))

    def test_bad_responses(self):
        for value in (b"<html>bad gateway</html>", {"error": {"message": "blocked"}},
                      {"promptFeedback": {"blockReason": "SAFETY"}}, URLError("offline")):
            with self.subTest(value=value):
                client, _ = self.client(value)
                chat = client.chat("gemini")
                with self.assertRaises(bm.BazeError):
                    chat.ask("질문")
                self.assertEqual(chat._history, [])

    def test_truncated_output_is_not_silently_complete(self):
        client, _ = self.client(gpt_reply("일부 답변", status="incomplete"))
        reply = client.ask("gpt", "질문")
        self.assertEqual(reply.text, "일부 답변")
        self.assertTrue(reply.warning)

    def test_models_query_and_filter(self):
        client, fake = self.client({"data": [{"id": "claude-b"}, {"id": "gpt-a"}, {"id": "claude-a"}]})
        self.assertEqual(client.list_models("claude"), ["claude-a", "claude-b"])
        self.assertEqual(fake.requests[0][0].method, "GET")
        self.assertTrue(fake.requests[0][0].full_url.endswith("/models/?type=llm"))

    def test_credits_and_usage_read_only_routes(self):
        balance = {"object": "credit_balance", **{name: {"remaining": 5000.0}
                   for name in ("monthly_allocated", "purchased", "org_granted", "total")}}
        summary = {"object": "usage_summary", "rows": [], "total": {"credits": 0}}
        client, fake = self.client(balance, summary)
        self.assertEqual(client.credits()["monthly_allocated"]["remaining"], 5000.0)
        self.assertEqual(client.usage(group_by="model", scope="member")["rows"], [])
        self.assertTrue(fake.requests[0][0].full_url.endswith("/credits/"))
        self.assertTrue(fake.requests[1][0].full_url.endswith("/usage/?by=model&scope=member"))
        self.assertTrue(all(request.method == "GET" for request, _ in fake.requests))

    def test_model_override_and_validation(self):
        client, fake = self.client()
        with patch.dict(os.environ, {"BAZE_GPT_MODEL": "gpt-env"}):
            self.assertEqual(client.chat("gpt").model, "gpt-env")
            self.assertEqual(client.chat("gpt", model="gpt-explicit").model, "gpt-explicit")
        for call in (lambda: client.chat("wrong"), lambda: client.chat("gpt", max_tokens=0),
                     lambda: client.ask("gpt", " ")):
            with self.assertRaises(ValueError):
                call()
        self.assertFalse(fake.requests)

    def test_cli_readme_model_option_between_positionals(self):
        fake = FakeOpener(gpt_reply())
        with patch.object(bm, "build_opener", return_value=fake), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(bm.main(["gpt", "--model", "gpt-custom", "안녕!"]), 0)
        self.assertEqual(fake.body()["model"], "gpt-custom")
        self.assertIn("안녕하세요", output.getvalue())

    def test_missing_key_has_no_network_request(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(bm.BazeError):
                bm.BazeClient()

    def test_system_tls_keeps_certificate_and_hostname_checks(self):
        import truststore
        context, backend = bm._make_ssl_context()
        self.assertEqual(backend, "system-truststore")
        self.assertIsInstance(context, truststore.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_missing_truststore_still_verifies_certificates(self):
        with patch.dict(sys.modules, {"truststore": None}):
            context, backend = bm._make_ssl_context()
        self.assertEqual(backend, "python-ssl")
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_certificate_error_explained_without_retry_or_bypass(self):
        error = URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
        client, fake = self.client(error)
        with self.assertRaises(bm.BazeError) as raised:
            client.ask("gpt", "질문")
        self.assertIn("SSL 인증서 검증 실패", str(raised.exception))
        self.assertEqual(len(fake.requests), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

