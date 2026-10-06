# Test receipt — BedrockOps

Verified by Soundwave on this VM, 2026-10-06 (America/Chicago).
Supersedes both earlier receipts (3-test FastAPI era, 8-test SDK era).

## 1. Tests
Command (repo root, local .venv, mcp==2.3.0, AWS_EC2_METADATA_DISABLED=true):
    python -m unittest tests/test_mcp.py
Result: **exit code 0 — Ran 13 tests, OK**
Coverage:
- JSON-RPC initialize negotiating protocolVersion 2025-11-25 (BedrockOps 1.0.0)
- tools/list: exactly system_probe, audit_ledger, bedrock_route, each with inputSchema
- tools/call system_probe (stub): HEALTHY/dynamodb, isError false
- tools/call audit_ledger: sha256 matches hashlib; persisted=false, store=memory (no table configured)
- tools/call bedrock_route gate: "delete the production database" -> requires_approval, live=false
- tools/call bedrock_route offline: live=false (no credentials), action=audit_ledger
- tools/call rejects unknown target_service (isError true)
- legacy /mcp/v1/tools (3 tools) and /mcp/v1/execute HEALTHY
- ledger hashing; DynamoDB PutItem path with a fake client (item shape asserted);
  failing DynamoDB client -> persisted=false, persist_error=RuntimeError, digest still returned
- live-probe failure path (BEDROCKOPS_LIVE=1, probe raising) -> UNREACHABLE/live_failed, never HEALTHY

## 2. Live server + official SDK client, opt-in live mode
Server: BEDROCKOPS_LIVE=1 python server.py
Client: mcp.ClientSession over streamable_http_client
Result: client exit code 0
- protocol: 2025-11-25; tools: ['system_probe', 'audit_ledger', 'bedrock_route']
- bedrock_route "audit last night" -> live=false, fallback_reason=NoCredentialsError (honest)
- bedrock_route "delete production" -> action=requires_approval (gate held, no AWS call)
- system_probe dynamodb with BEDROCKOPS_LIVE=1 -> UNREACHABLE, mode=live_failed, error=NoCredentialsError
  (a real AWS attempt was made and failed for lack of credentials — not faked)
- audit_ledger -> verified, persisted=false, store=memory (no AUDIT_TABLE_NAME set)

Environment check behind those results: no ~/.aws directory, no AWS
credential env vars on this VM; the SDK raises NoCredentialsError.
Proxy vars must be unset for local HTTP clients on this VM (known quirk).

## 3. Terraform
terraform/*.tf parse cleanly with python-hcl2. `terraform validate`,
`plan`, and `apply` have NOT run (no terraform binary on this VM).
No Lambda resource is defined, deliberately: the code has no handler.

## Not proven, and what closes it
A live Bedrock InvokeModel response, a successful live AWS probe, and
a real DynamoDB PutItem — all three need one run with Ricket's own AWS
credentials at his PC (aws configure / SSO, then .env.example switches).
No credential was requested, used, or stored during this work.
