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

## 4. v2 addendum — operator console, approval, orchestration, history
Built and verified on this VM, 2026-10-10. Extends the receipt above;
nothing in sections 1–3 changed.

### Tests
Command (repo root, local .venv):
    python -m unittest discover -s tests
Result: **exit code 0 — Ran 26 tests, OK** (13 v1 + 13 new v2)
New coverage:
- Gated request creates a PENDING proposal and executes nothing
  (probe count 0; invoke/execute_approved mocks uncalled); the only
  ledger write is `proposal_created`.
- Approve runs the full orchestration (3 probes in sequence), writes
  exactly one `orchestration_run` record with approved=true, refuses a
  second approval.
- Deny executes nothing and is audited (`proposal_denied`).
- Non-gated orchestration in stub mode: probes bedrock/dynamodb/lambda
  in order, one audit record, route result honestly `live: false`.
- History read-back: DynamoDB Query path proven against a fake client
  (item shape, one Query on the one table); no-table and
  failing-client cases fall back to memory with source labeled.
- Console API over HTTP: page served, status panels all `stub`,
  gate → approve → history flow, deny flow, approve-after-deny = 409,
  empty prompt = 400.

### Console proof (stub mode, real HTTP against `python server.py`)
- GET /console → 200, console HTML.
- GET /console/api/status → all three services
  `{"status": "HEALTHY", "mode": "stub"}` — badged stub, not live.
- POST /console/api/request {"prompt": "delete the production database"}
  → `{"status": "pending", "proposal": {"id": "d97a98c60af7",
  "status": "PENDING", ...}}` — nothing executed.
- POST /console/api/request {"prompt": "check service health"}
  → executed run: probes bedrock/dynamodb/lambda all stub,
  result live=false (NoCredentialsError), one audit record,
  `{"persisted": false, "store": "memory"}`.
- POST /console/api/proposals/approve {"id": "d97a98c60af7"}
  → proposal EXECUTED; run audited (sha256 98d00be8adff…).
- Second gated prompt → proposal e595e2b5eda9 → DENY →
  `{"status": "denied", "audit_sha256": "34f67227d8e0…"}`.
- GET /console/api/history → `source: memory, persisted: False`,
  5 entries: proposal_created ×2, orchestration_run ×2,
  proposal_denied ×1. Read-back works; it does NOT claim DynamoDB,
  because no table is configured on this VM.

### Live proof: PENDING (not claimed)
A live Bedrock InvokeModel response, a successful live AWS probe, a
real DynamoDB PutItem, and a DynamoDB Query read of a prior session's
records all still need the one credentialed run at Ricket's PC
(aws configure / SSO, then .env.example switches). Terraform also
gained `dynamodb:Query` on the audit table (v2); validate/apply
remain unrun. No credential was requested, used, or stored during
this work.

## Not proven, and what closes it
A live Bedrock InvokeModel response, a successful live AWS probe, and
a real DynamoDB PutItem — all three need one run with Ricket's own AWS
credentials at his PC (aws configure / SSO, then .env.example switches).
No credential was requested, used, or stored during this work.

## 5. v2.1 addendum — provider-agnostic invoke (Converse API)
Changed on this VM, 2026-10-10, after sections 1–4 above were written.
Sections 1–4 are historical and unchanged; this section supersedes
their wording wherever they say "InvokeModel."

What changed:
- `bedrock_agent.py`: the Anthropic-only InvokeModel payload is gone.
  `invoke()` and `execute_approved()` now share one helper,
  `_converse_reply()`, which calls the Bedrock **Converse API**
  (`bedrock-runtime.converse`). Converse has one request/response
  shape across model families, so `BEDROCK_MODEL_ID` can name any
  Converse-supported model — Claude, Amazon Nova, Meta Llama,
  Mistral, DeepSeek, Qwen — with no code change. The default stays
  `anthropic.claude-sonnet-5`; the env var still wins.
- Why: on a new AWS account, Anthropic models refuse invocation until
  the one-time use-case-details approval lands ("not available for
  this account"). The live proof must not depend on that vendor gate,
  so non-Anthropic models (Amazon Nova normally answers immediately on
  a new account) now work through the identical code path.
- Honest contract unchanged: no credentials / any call error still
  returns `live: false` with the exception named (`fallback_reason` =
  exception type, plus `error` = its message). No fabricated reply,
  no silent fallback that pretends to be live. Scope unchanged: the
  only outbound call is a model invocation; no code path mutates AWS
  resources, before or after approval.
- `.env.example` + README document the resolution order and the two
  instant-access fallbacks (`amazon.nova-lite-v1:0`,
  `amazon.nova-pro-v1:0`). The default was NOT switched to Nova.

### Tests
Command (repo root, local .venv, AWS_EC2_METADATA_DISABLED=true):
    python -m unittest discover -s tests
Result: **exit code 0 — Ran 31 tests in 0.498s — OK**
(26 pre-existing, all still green and unweakened; + 5 new:
mocked Converse success → parsed text + `live: true`; same call with
`amazon.nova-lite-v1:0` → works, correct model ID sent; mocked
Converse error → `live: false`, `fallback_reason` + real error
string; `execute_approved` success and error under the same mocks.
All boto3 calls are mocked; no network is used.)

### Live proof: PENDING (not claimed)
A live Bedrock Converse response (any provider), a successful live
AWS probe, a real DynamoDB PutItem, and a DynamoDB Query read of a
prior session's records still all need the one credentialed run at
Ricket's PC. No credential was requested, used, or stored during
this work.
