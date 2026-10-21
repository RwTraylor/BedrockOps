import hashlib
import json
import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import server
from ledger import AuditLedger
from orchestrator import Orchestrator
from server import app

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
BASE_URL = "http://127.0.0.1:8000"

# One shared client: the SDK session manager behind `app` can only start
# once per process, so all test classes share a single lifespan.
_client_ctx = None
client = None


def setUpModule():
    global _client_ctx, client
    # Deterministic offline tests: no IMDS lookup, no real table.
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    os.environ.pop("AUDIT_TABLE_NAME", None)
    os.environ.pop("BEDROCKOPS_AUDIT_TABLE", None)
    os.environ.pop("BEDROCKOPS_LIVE", None)
    _client_ctx = TestClient(app, base_url=BASE_URL)
    client = _client_ctx.__enter__()


def tearDownModule():
    _client_ctx.__exit__(None, None, None)


class TestMCPProtocol(unittest.TestCase):
    """Real MCP (official SDK) over Streamable HTTP, JSON-RPC end to end."""

    def rpc(self, payload):
        return client.post("/mcp", json=payload, headers=HEADERS)

    def initialize(self):
        return self.rpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "bedrockops-test", "version": "0.1"},
            },
        })

    def test_initialize_negotiates_2025_11_25(self):
        response = self.initialize()
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertEqual(result["serverInfo"]["name"], "BedrockOps")

    def test_tools_list(self):
        self.initialize()
        response = self.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(response.status_code, 200)
        tools = response.json()["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"system_probe", "audit_ledger", "bedrock_route"})
        for tool in tools:
            self.assertIn("inputSchema", tool)

    def test_tools_call_system_probe(self):
        self.initialize()
        response = self.rpc({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "system_probe", "arguments": {"target_service": "dynamodb"}},
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertFalse(result["isError"])
        text = result["content"][0]["text"]
        self.assertIn("HEALTHY", text)
        self.assertIn("dynamodb", text)

    def test_tools_call_audit_ledger_hash(self):
        self.initialize()
        response = self.rpc({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "audit_ledger", "arguments": {"payload": "deploy-prod"}},
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertFalse(result["isError"])
        body = json.loads(result["content"][0]["text"])
        self.assertEqual(body["sha256"], hashlib.sha256(b"deploy-prod").hexdigest())
        self.assertTrue(body["verified"])
        # No table configured in tests: honest memory-only persistence.
        self.assertFalse(body["persisted"])
        self.assertEqual(body["store"], "memory")

    def test_tools_call_bedrock_route_gate(self):
        self.initialize()
        response = self.rpc({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "bedrock_route", "arguments": {"prompt": "delete the production database"}},
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertFalse(result["isError"])
        body = json.loads(result["content"][0]["text"])
        self.assertEqual(body["action"], "requires_approval")
        self.assertFalse(body["live"])

    def test_tools_call_bedrock_route_offline_is_honest(self):
        self.initialize()
        response = self.rpc({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "bedrock_route", "arguments": {"prompt": "audit last night's run"}},
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertFalse(result["isError"])
        body = json.loads(result["content"][0]["text"])
        # No AWS credentials in the test environment: must say live=false,
        # never claim a Bedrock call happened.
        self.assertFalse(body["live"])
        self.assertEqual(body["action"], "audit_ledger")

    def test_tools_call_rejects_unknown_service(self):
        self.initialize()
        response = self.rpc({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "system_probe", "arguments": {"target_service": "ec2"}},
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["result"]["isError"])


class TestLegacyCompat(unittest.TestCase):
    """Pre-SDK REST/SSE shim kept at /mcp/v1/*."""

    def test_legacy_list_tools(self):
        response = client.get("/mcp/v1/tools")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["tools"]), 3)

    def test_legacy_system_probe_execution(self):
        payload = {"name": "system_probe", "arguments": {"target_service": "dynamodb"}}
        response = client.post("/mcp/v1/execute", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("HEALTHY", response.text)


class TestLedger(unittest.TestCase):
    def test_audit_ledger_hashing(self):
        ledger = AuditLedger()
        digest = ledger.record_event("DEPLOY", {"env": "prod"})
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(ledger.entries), 1)
        self.assertFalse(ledger.entries[0]["persisted"])

    def test_dynamodb_persist_with_fake_client(self):
        class FakeDynamo:
            def __init__(self):
                self.items = []

            def put_item(self, TableName, Item):
                self.items.append((TableName, Item))
                return {}

        fake = FakeDynamo()
        ledger = AuditLedger(table_name="audit-table", session_id="sess-1", dynamodb_client=fake)
        digest = ledger.record_event("DEPLOY", {"env": "prod"})
        self.assertTrue(ledger.entries[0]["persisted"])
        self.assertEqual(len(fake.items), 1)
        table, item = fake.items[0]
        self.assertEqual(table, "audit-table")
        self.assertEqual(item["SessionId"]["S"], "sess-1")
        self.assertEqual(item["Sha256"]["S"], digest)

    def test_dynamodb_failure_is_reported_not_faked(self):
        class BrokenDynamo:
            def put_item(self, TableName, Item):
                raise RuntimeError("boom")

        ledger = AuditLedger(table_name="audit-table", dynamodb_client=BrokenDynamo())
        digest = ledger.record_event("DEPLOY", {"env": "prod"})
        self.assertEqual(len(digest), 64)
        self.assertFalse(ledger.entries[0]["persisted"])
        self.assertEqual(ledger.entries[0]["persist_error"], "RuntimeError")


class FakeConverseClient:
    """Offline stand-in for a boto3 bedrock-runtime client (Converse API)."""

    def __init__(self, reply="converse stub reply"):
        self.reply = reply
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": self.reply}],
                }
            },
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 4, "totalTokens": 9},
        }


class TestConverseInvoke(unittest.TestCase):
    """v2.1: the model call goes through the provider-agnostic Converse
    API. Mocked boto3 — no network, no credentials — and every result
    must stay honest (live:true only when the mocked call succeeds)."""

    def test_converse_success_returns_live_and_text(self):
        ba = server.bedrock_agent
        fake = FakeConverseClient()
        with patch("boto3.client", return_value=fake) as mock_client:
            result = ba.invoke("check service health")
        self.assertTrue(result["live"])
        self.assertEqual(result["model"], ba.DEFAULT_MODEL_ID)
        self.assertEqual(result["response"]["text"], "converse stub reply")
        self.assertEqual(result["response"]["stop_reason"], "end_turn")
        self.assertEqual(result["action"], "system_probe")
        mock_client.assert_called_once_with("bedrock-runtime", region_name=ba.AWS_REGION)
        self.assertEqual(fake.calls[0]["modelId"], ba.DEFAULT_MODEL_ID)
        self.assertEqual(
            fake.calls[0]["messages"][0]["content"][0]["text"],
            "check service health",
        )

    def test_converse_works_with_non_anthropic_model(self):
        ba = server.bedrock_agent
        fake = FakeConverseClient(reply="nova stub reply")
        with patch.object(ba, "DEFAULT_MODEL_ID", "amazon.nova-lite-v1:0"):
            with patch("boto3.client", return_value=fake):
                result = ba.invoke("check service health")
        self.assertTrue(result["live"])
        self.assertEqual(result["model"], "amazon.nova-lite-v1:0")
        self.assertEqual(result["response"]["text"], "nova stub reply")
        self.assertEqual(fake.calls[0]["modelId"], "amazon.nova-lite-v1:0")

    def test_converse_error_is_honest(self):
        ba = server.bedrock_agent

        class DeniedConverse:
            def converse(self, **kwargs):
                raise RuntimeError(
                    "AccessDeniedException: model not available for this account"
                )

        with patch("boto3.client", return_value=DeniedConverse()):
            result = ba.invoke("check service health")
        self.assertFalse(result["live"])
        self.assertEqual(result["fallback_reason"], "RuntimeError")
        self.assertIn("AccessDeniedException", result["error"])

    def test_execute_approved_converse_success(self):
        ba = server.bedrock_agent
        fake = FakeConverseClient(reply="approved run reply")
        with patch("boto3.client", return_value=fake):
            result = ba.execute_approved("check service health")
        self.assertTrue(result["live"])
        self.assertTrue(result["executed"])
        self.assertTrue(result["approved"])
        self.assertEqual(result["response"]["text"], "approved run reply")
        self.assertEqual(fake.calls[0]["modelId"], ba.DEFAULT_MODEL_ID)

    def test_execute_approved_converse_error_is_honest(self):
        ba = server.bedrock_agent

        class ThrottledConverse:
            def converse(self, **kwargs):
                raise RuntimeError("ThrottlingException: slow down")

        with patch("boto3.client", return_value=ThrottledConverse()):
            result = ba.execute_approved("check service health")
        self.assertFalse(result["live"])
        self.assertTrue(result["executed"])
        self.assertTrue(result["approved"])
        self.assertEqual(result["fallback_reason"], "RuntimeError")
        self.assertIn("ThrottlingException", result["error"])


class TestApprovalGate(unittest.TestCase):
    """v2 two-step approval: gated requests execute nothing until approved."""

    def make_orchestrator(self):
        calls = {"probe": 0}

        def fake_probe(service):
            calls["probe"] += 1
            return {"status": "HEALTHY", "mode": "stub", "service": service}

        test_ledger = AuditLedger()
        return Orchestrator(test_ledger, fake_probe), test_ledger, calls

    def test_gated_request_creates_pending_and_executes_nothing(self):
        orch, test_ledger, calls = self.make_orchestrator()
        with patch.object(server.bedrock_agent, "invoke") as mock_invoke, \
             patch.object(server.bedrock_agent, "execute_approved") as mock_exec:
            out = orch.submit("delete the production database")
        self.assertEqual(out["status"], "pending")
        self.assertEqual(out["proposal"]["status"], "PENDING")
        self.assertEqual(calls["probe"], 0)  # nothing executed, not even probes
        mock_invoke.assert_not_called()
        mock_exec.assert_not_called()
        actions = [e["action"] for e in test_ledger.entries]
        self.assertEqual(actions, ["proposal_created"])

    def test_approve_executes_and_audits(self):
        orch, test_ledger, calls = self.make_orchestrator()
        proposal_id = orch.submit("delete the production database")["proposal"]["id"]
        out = orch.approve(proposal_id)
        self.assertEqual(out["status"], "executed")
        self.assertEqual(out["proposal"]["status"], "EXECUTED")
        run = out["run"]
        self.assertTrue(run["approved"])
        self.assertEqual(run["mode"], "stub")  # no credentials on this VM
        self.assertEqual(calls["probe"], 3)  # bedrock + dynamodb + lambda
        self.assertEqual(set(run["probes"]), {"bedrock", "dynamodb", "lambda"})
        self.assertEqual(run["audit"]["store"], "memory")
        self.assertFalse(run["audit"]["persisted"])
        run_records = [e for e in test_ledger.entries if e["action"] == "orchestration_run"]
        self.assertEqual(len(run_records), 1)  # one audit record for the whole run
        self.assertTrue(run_records[0]["details"]["approved"])
        self.assertEqual(run_records[0]["details"]["proposal_id"], proposal_id)
        with self.assertRaises(ValueError):
            orch.approve(proposal_id)  # second approval is refused

    def test_deny_executes_nothing_and_is_audited(self):
        orch, test_ledger, calls = self.make_orchestrator()
        proposal_id = orch.submit("destroy the staging cluster")["proposal"]["id"]
        with patch.object(server.bedrock_agent, "invoke") as mock_invoke, \
             patch.object(server.bedrock_agent, "execute_approved") as mock_exec:
            out = orch.deny(proposal_id)
        self.assertEqual(out["status"], "denied")
        self.assertEqual(calls["probe"], 0)
        mock_invoke.assert_not_called()
        mock_exec.assert_not_called()
        actions = [e["action"] for e in test_ledger.entries]
        self.assertEqual(actions, ["proposal_created", "proposal_denied"])
        self.assertEqual(orch.proposals[proposal_id]["status"], "DENIED")
        with self.assertRaises(ValueError):
            orch.deny(proposal_id)  # already decided


class TestOrchestrationStub(unittest.TestCase):
    """v2 orchestration in stub mode: probes + route + one audit record."""

    def test_non_gated_request_runs_full_orchestration(self):
        probed = []

        def fake_probe(service):
            probed.append(service)
            return {"status": "HEALTHY", "mode": "stub", "service": service}

        test_ledger = AuditLedger()
        orch = Orchestrator(test_ledger, fake_probe)
        out = orch.submit("check service health")
        self.assertEqual(out["status"], "executed")
        run = out["run"]
        self.assertEqual(probed, ["bedrock", "dynamodb", "lambda"])  # sequence
        self.assertEqual(run["route"]["action"], "system_probe")
        self.assertEqual(run["mode"], "stub")
        self.assertFalse(run["result"]["live"])  # no credentials: honest
        run_records = [e for e in test_ledger.entries if e["action"] == "orchestration_run"]
        self.assertEqual(len(run_records), 1)
        self.assertEqual(run_records[0]["details"]["probes"]["bedrock"]["mode"], "stub")

    def test_audit_route_records_payload_hash(self):
        test_ledger = AuditLedger()
        orch = Orchestrator(
            test_ledger,
            lambda svc: {"status": "HEALTHY", "mode": "stub", "service": svc},
        )
        out = orch.submit("audit last night's run")
        self.assertEqual(out["run"]["route"]["action"], "audit_ledger")
        self.assertEqual(
            out["run"]["result"]["payload_sha256"],
            hashlib.sha256("audit last night's run".encode("utf-8")).hexdigest(),
        )


class TestHistoryRead(unittest.TestCase):
    """v2 cross-session history: DynamoDB Query read-back + honest fallback."""

    def test_history_falls_back_to_memory_without_table(self):
        test_ledger = AuditLedger()
        test_ledger.record_event("FIRST", {"n": 1})
        test_ledger.record_event("SECOND", {"n": 2})
        history = test_ledger.read_history()
        self.assertEqual(history["source"], "memory")
        self.assertFalse(history["persisted"])
        self.assertEqual([e["action"] for e in history["entries"]], ["SECOND", "FIRST"])

    def test_history_reads_dynamodb_with_fake_client(self):
        class FakeDynamo:
            def __init__(self):
                self.queries = []

            def put_item(self, TableName, Item):
                return {}

            def query(self, **kwargs):
                self.queries.append(kwargs)
                return {"Items": [{
                    "SessionId": {"S": "sess-1"},
                    "Timestamp": {"N": "1728000000.5"},
                    "Action": {"S": "DEPLOY"},
                    "Details": {"S": json.dumps({"env": "prod"})},
                    "Sha256": {"S": "abc123"},
                }]}

        fake = FakeDynamo()
        test_ledger = AuditLedger(table_name="audit-table", session_id="sess-1", dynamodb_client=fake)
        history = test_ledger.read_history()
        self.assertEqual(history["source"], "dynamodb")
        self.assertTrue(history["persisted"])
        entry = history["entries"][0]
        self.assertEqual(entry["action"], "DEPLOY")
        self.assertEqual(entry["details"], {"env": "prod"})
        self.assertTrue(entry["persisted"])
        self.assertEqual(entry["store"], "dynamodb")
        self.assertEqual(len(fake.queries), 1)  # one table, one Query
        self.assertIn("SessionId = :sid", fake.queries[0]["KeyConditionExpression"])
        self.assertEqual(fake.queries[0]["TableName"], "audit-table")

    def test_history_dynamodb_failure_falls_back_to_memory(self):
        class BrokenDynamo:
            def put_item(self, TableName, Item):
                raise RuntimeError("write boom")

            def query(self, **kwargs):
                raise RuntimeError("read boom")

        test_ledger = AuditLedger(table_name="audit-table", dynamodb_client=BrokenDynamo())
        test_ledger.record_event("LOCAL_ONLY", {"n": 1})
        history = test_ledger.read_history()
        self.assertEqual(history["source"], "memory")
        self.assertFalse(history["persisted"])
        self.assertEqual(history["read_error"], "RuntimeError")
        self.assertEqual(history["entries"][0]["action"], "LOCAL_ONLY")
        self.assertFalse(history["entries"][0]["persisted"])


class TestConsoleAPI(unittest.TestCase):
    """v2 operator console HTTP surface (shares the module TestClient)."""

    def test_console_page_served(self):
        response = client.get("/console")
        self.assertEqual(response.status_code, 200)
        self.assertIn("BedrockOps Operator Console", response.text)
        self.assertIn("Pending proposals", response.text)

    def test_console_status_badges_stub(self):
        body = client.get("/console/api/status").json()
        self.assertEqual(set(body["services"]), {"bedrock", "dynamodb", "lambda"})
        for svc in body["services"].values():
            self.assertEqual(svc["mode"], "stub")

    def test_console_gate_approve_history_flow(self):
        out = client.post(
            "/console/api/request", json={"prompt": "delete the production database NOW"}
        ).json()
        self.assertEqual(out["status"], "pending")
        pid = out["proposal"]["id"]
        props = client.get("/console/api/proposals").json()["proposals"]
        self.assertTrue(any(p["id"] == pid and p["status"] == "PENDING" for p in props))
        approved = client.post("/console/api/proposals/approve", json={"id": pid}).json()
        self.assertEqual(approved["status"], "executed")
        self.assertEqual(approved["run"]["mode"], "stub")
        self.assertFalse(approved["run"]["audit"]["persisted"])
        history = client.get("/console/api/history").json()
        self.assertEqual(history["source"], "memory")
        runs = [e for e in history["entries"] if e["action"] == "orchestration_run"]
        self.assertTrue(any(e["details"].get("proposal_id") == pid for e in runs))

    def test_console_deny_flow(self):
        out = client.post(
            "/console/api/request", json={"prompt": "provision_high_spend on everything"}
        ).json()
        self.assertEqual(out["status"], "pending")
        pid = out["proposal"]["id"]
        denied = client.post("/console/api/proposals/deny", json={"id": pid}).json()
        self.assertEqual(denied["status"], "denied")
        props = client.get("/console/api/proposals").json()["proposals"]
        self.assertTrue(any(p["id"] == pid and p["status"] == "DENIED" for p in props))
        conflict = client.post("/console/api/proposals/approve", json={"id": pid})
        self.assertEqual(conflict.status_code, 409)

    def test_console_request_requires_prompt(self):
        response = client.post("/console/api/request", json={"prompt": "  "})
        self.assertEqual(response.status_code, 400)


class TestLiveProbeFailure(unittest.TestCase):
    def test_live_probe_failure_is_unreachable_not_healthy(self):
        with patch.dict(os.environ, {"BEDROCKOPS_LIVE": "1"}):
            with patch.object(server.bedrock_agent, "probe_service", side_effect=RuntimeError("no creds")):
                result = server._probe("lambda")
        self.assertEqual(result["status"], "UNREACHABLE")
        self.assertEqual(result["mode"], "live_failed")


if __name__ == "__main__":
    unittest.main()
