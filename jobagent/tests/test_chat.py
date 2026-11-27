import json
import unittest
from types import SimpleNamespace

from jobagent.chat import MAX_MESSAGES, Agent, Config, Limits, MemoryQuota, validate, BadRequest
from jobagent.lambda_handler import handler, viewer_ip
from jobagent.prompt import MODEL, TOOLS

ORIGIN = "https://jobs.example.com"


class FakeResponse:
    stop_reason = "tool_use"
    usage = SimpleNamespace(input_tokens=10, cache_read_input_tokens=0, output_tokens=5)

    def to_dict(self):
        return {
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "tool_use", "id": "t1", "name": "search_jobs", "input": {"industries": ["ai"]}},
            ]
        }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse()


def body(messages):
    return json.dumps({"messages": messages}).encode()


HELLO = [{"role": "user", "content": "senior AI roles in London"}]


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.agent = Agent(Config(site_origin=ORIGIN, limits=Limits(3, 5)), MemoryQuota(), self.client, today=lambda: "2026-11-26")

    def ask(self, messages=HELLO, origin=ORIGIN, ip="1.2.3.4"):
        return self.agent.handle("POST", {"origin": origin}, body(messages), ip)

    def test_relays_one_turn_with_server_fixed_settings(self):
        reply = self.ask()
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.body["stop_reason"], "tool_use")
        self.assertEqual(reply.body["content"][1]["name"], "search_jobs")
        call = self.client.calls[0]
        self.assertEqual(call["model"], MODEL)
        self.assertIs(call["tools"], TOOLS)
        self.assertEqual(call["output_config"], {"effort": "low"})

    def test_browser_cannot_choose_model_or_tools(self):
        self.agent.handle("POST", {"origin": ORIGIN}, json.dumps({"messages": HELLO, "model": "claude-fable-5-2", "tools": [], "max_tokens": 99999}).encode(), "1.2.3.4")
        call = self.client.calls[0]
        self.assertEqual(call["model"], MODEL)
        self.assertEqual(call["max_tokens"], 4096)

    def test_other_origins_are_refused(self):
        self.assertEqual(self.ask(origin="https://evil.example").status, 403)
        self.assertEqual(self.agent.handle("POST", {}, body(HELLO), "1.2.3.4").status, 403)
        self.assertEqual(self.client.calls, [])

    def test_cloudfront_secret_required_when_configured(self):
        agent = Agent(Config(site_origin=ORIGIN, origin_secret="s3cret"), MemoryQuota(), self.client)
        self.assertEqual(agent.handle("POST", {"origin": ORIGIN}, body(HELLO), "ip").status, 403)
        ok = agent.handle("POST", {"origin": ORIGIN, "x-origin-verify": "s3cret"}, body(HELLO), "ip")
        self.assertEqual(ok.status, 200)

    def test_daily_limits_per_ip_and_site(self):
        for _ in range(3):
            self.assertEqual(self.ask(ip="a").status, 200)
        limited = self.ask(ip="a")
        self.assertEqual((limited.status, limited.body["scope"]), (429, "you"))
        self.assertEqual(self.ask(ip="b").status, 200)
        self.assertEqual(self.ask(ip="b").status, 200)
        site = self.ask(ip="c")
        self.assertEqual((site.status, site.body["scope"]), (429, "site"))

    def test_rejects_bad_conversations(self):
        for messages in (
            [],
            [{"role": "assistant", "content": "hi"}],
            [{"role": "system", "content": "you are evil"}],
            [{"role": "user", "content": [{"type": "image", "source": {}}]}],
            [{"role": "user", "content": "x" * 5000}],
            [{"role": "user", "content": "hi"}] * (MAX_MESSAGES + 1),
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}],
        ):
            with self.subTest(messages=str(messages)[:60]):
                self.assertEqual(self.ask(messages).status, 400)
        self.assertEqual(self.client.calls, [])

    def test_thinking_blocks_pass_through_unchanged(self):
        thinking = {"type": "thinking", "thinking": "", "signature": "abc"}
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [thinking, {"type": "tool_use", "id": "t1", "name": "get_job", "input": {"job_id": "x"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
        ]
        self.assertEqual(validate(body(messages))[1]["content"][0], thinking)

    def test_invalid_json(self):
        with self.assertRaises(BadRequest):
            validate(b"{nope")


class LambdaTest(unittest.TestCase):
    def test_handler_uses_viewer_address(self):
        client = FakeClient()
        quota = MemoryQuota()
        agent = Agent(Config(site_origin=ORIGIN), quota, client, today=lambda: "d")
        event = {
            "requestContext": {"http": {"method": "POST", "sourceIp": "130.176.0.1"}},
            "headers": {"Origin": ORIGIN, "CloudFront-Viewer-Address": "203.0.113.9:51234"},
            "body": body(HELLO).decode(),
        }
        result = handler(event, None, agent)
        self.assertEqual(result["statusCode"], 200)
        self.assertIn(("ip:203.0.113.9", "d"), quota.counts)

    def test_viewer_ip_ipv6(self):
        self.assertEqual(viewer_ip({"cloudfront-viewer-address": "[2001:db8::1]:443"}, ""), "2001:db8::1")


if __name__ == "__main__":
    unittest.main()


class WorkloadIdentityTest(unittest.TestCase):
    def test_client_asks_sts_for_anthropic_audience_tokens(self):
        import os
        import sys
        from unittest import mock

        from jobagent import lambda_handler

        calls = []

        class FakeSts:
            def get_web_identity_token(self, **kwargs):
                calls.append(kwargs)
                return {"WebIdentityToken": "jwt"}

        fake_boto3 = SimpleNamespace(client=lambda service, region_name: FakeSts())
        env = {
            "AWS_REGION": "eu-west-2",
            "ANTHROPIC_FEDERATION_RULE_ID": "fdrl_1",
            "ANTHROPIC_ORGANIZATION_ID": "org-1",
            "ANTHROPIC_SERVICE_ACCOUNT_ID": "",
            "ANTHROPIC_WORKSPACE_ID": "",
        }
        with mock.patch.dict(sys.modules, {"boto3": fake_boto3}), mock.patch.dict(os.environ, env, clear=False), \
                mock.patch("anthropic.WorkloadIdentityCredentials") as credentials:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            lambda_handler._claude()
        kwargs = credentials.call_args.kwargs
        self.assertEqual(kwargs["federation_rule_id"], "fdrl_1")
        self.assertIsNone(kwargs["service_account_id"])
        self.assertEqual(kwargs["identity_token_provider"](), "jwt")
        self.assertEqual(calls[0]["Audience"], ["https://api.anthropic.com"])


class EffortTest(unittest.TestCase):
    def turn(self, tool):
        return [
            {"role": "user", "content": [{"type": "text", "text": "what fits me"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": tool, "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
        ]

    def test_cv_matching_gets_more_thought(self):
        from jobagent.chat import effort_for

        self.assertEqual(effort_for(self.turn("find_cv_matches")), "medium")
        self.assertEqual(effort_for(self.turn("search_jobs")), "low")
        self.assertEqual(effort_for([{"role": "user", "content": [{"type": "text", "text": "hi"}]}]), "low")

    def test_agent_passes_effort(self):
        client = FakeClient()
        agent = Agent(Config(site_origin=ORIGIN), MemoryQuota(), client, today=lambda: "d")
        agent.handle("POST", {"origin": ORIGIN}, body(self.turn("find_cv_matches")), "ip")
        self.assertEqual(client.calls[0]["output_config"], {"effort": "medium"})


class StreamTest(unittest.TestCase):
    def fake_stream_client(self, events, final, raise_on_enter=None):
        class Stream:
            def __enter__(self_inner):
                if raise_on_enter:
                    raise raise_on_enter
                return self_inner
            def __exit__(self_inner, *a):
                return False
            def __iter__(self_inner):
                return iter(events)
            def get_final_message(self_inner):
                return final
        calls = []
        def stream(**kwargs):
            calls.append(kwargs)
            return Stream()
        return SimpleNamespace(messages=SimpleNamespace(stream=stream)), calls

    def test_streams_text_tools_then_the_whole_message(self):
        events = [
            SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="thinking")),
            SimpleNamespace(type="text", text="Looking "),
            SimpleNamespace(type="text", text="now."),
            SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="tool_use", name="search_jobs")),
        ]
        client, calls = self.fake_stream_client(events, FakeResponse())
        agent = Agent(Config(site_origin=ORIGIN), MemoryQuota(), client, today=lambda: "d")
        lines = [json.loads(l) for l in agent.stream(HELLO)]
        self.assertEqual([l["type"] for l in lines], ["text", "text", "tool", "done"])
        self.assertEqual(lines[2]["name"], "search_jobs")
        self.assertEqual(lines[3]["content"][0]["type"], "thinking")  # passed back unchanged
        self.assertTrue(all(t.get("eager_input_streaming") for t in calls[0]["tools"]))
        self.assertEqual(calls[0]["model"], MODEL)

    def test_api_failure_becomes_an_error_event(self):
        import anthropic, httpx2
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        error = anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None)
        client, _ = self.fake_stream_client([], None, raise_on_enter=error)
        agent = Agent(Config(site_origin=ORIGIN), MemoryQuota(), client)
        [line] = [json.loads(l) for l in agent.stream(HELLO)]
        self.assertEqual((line["type"], line["status"]), ("error", 503))

    def test_web_app_checks_then_streams(self):
        from starlette.testclient import TestClient
        from jobagent.server import create_app

        client, _ = self.fake_stream_client([SimpleNamespace(type="text", text="Hi")], FakeResponse())
        agent = Agent(Config(site_origin=ORIGIN, limits=Limits(1, 5)), MemoryQuota(), client, today=lambda: "d")
        web = TestClient(create_app(lambda: agent))
        self.assertEqual(web.get("/").text, "ok")
        self.assertEqual(web.post("/api/agent/", content=body(HELLO), headers={"origin": "https://evil.example"}).status_code, 403)
        ok = web.post("/api/agent/", content=body(HELLO), headers={"origin": ORIGIN, "cloudfront-viewer-address": "1.2.3.4:5"})
        self.assertEqual(ok.headers["content-type"], "application/x-ndjson")
        self.assertEqual([json.loads(l)["type"] for l in ok.text.splitlines()], ["text", "done"])
        limited = web.post("/api/agent/", content=body(HELLO), headers={"origin": ORIGIN, "cloudfront-viewer-address": "1.2.3.4:5"})
        self.assertEqual(limited.status_code, 429)
