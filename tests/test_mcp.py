import hashlib
import json
import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import server
from ledger import AuditLedger
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


class TestLiveProbeFailure(unittest.TestCase):
    def test_live_probe_failure_is_unreachable_not_healthy(self):
        with patch.dict(os.environ, {"BEDROCKOPS_LIVE": "1"}):
            with patch.object(server.bedrock_agent, "probe_service", side_effect=RuntimeError("no creds")):
                result = server._probe("lambda")
        self.assertEqual(result["status"], "UNREACHABLE")
        self.assertEqual(result["mode"], "live_failed")


if __name__ == "__main__":
    unittest.main()
