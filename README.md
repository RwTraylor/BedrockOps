# BedrockOps — Autonomous Cloud Operations & Audit Agent

Open-source (MIT) cloud operations agent scaffold for the
Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track;
AWS Builder + Open Source mini-challenges).

## Status — read this first (2026-10-06)
- `server.py` is built on the **official MCP Python SDK** (`mcp==2.3.0`,
  `MCPServer` — the v2 name for FastMCP) and serves Streamable HTTP at
  `/mcp`. Verified on this machine:
  - `python -m unittest discover -s tests` → exit 0, **31 tests OK**
    (13 v1 + 13 v2: approval gate, orchestration, history read-back,
    console API; + 5 v2.1: provider-agnostic Converse invoke, mocked),
    including raw JSON-RPC initialize negotiating
    **2025-11-25**, tools/list, and tools/call for all three tools.
  - A live server + the official SDK client (`ClientSession` over
    `streamable_http_client`) listed both tools and called both
    successfully, also negotiating protocol **2025-11-25**.
  - Full proof in `TEST_RECEIPT.md`.
- Wired 2026-10-06, proven locally where possible:
  `bedrock_route` tool calls `bedrock_agent.invoke()` — gated prompts
  stop at `requires_approval`; with no AWS credentials in this
  environment it honestly returns `"live": false`
  (fallback_reason NoCredentialsError), tested. `system_probe` with
  `BEDROCKOPS_LIVE=1` makes one real read-only AWS call and, in this
  credential-less environment, correctly returns
  `UNREACHABLE / live_failed` instead of faking HEALTHY, tested.
  `audit_ledger` persists to DynamoDB when `AUDIT_TABLE_NAME` is set:
  the PutItem path is proven against a fake client in tests, and a
  failing client is reported (`persisted: false`), never faked.
- Not yet proven, because this VM has no AWS credentials (checked:
  no ~/.aws, no AWS env keys, SDK raises NoCredentialsError):
  a live Bedrock model call, a live AWS probe succeeding, and a
  real DynamoDB write. Those need one run at Ricket's PC with his own
  AWS login. See `.env.example` for the exact switches.
- Terraform now defines the DynamoDB table plus a least-privilege IAM
  policy matching exactly what the code calls (Bedrock invoke/list,
  Lambda/DynamoDB list, DynamoDB PutItem + Query to the one table).
  HCL files parse (python-hcl2); `terraform validate/apply` has not
  run — no terraform binary on this VM. There is deliberately no
  Lambda function: the code has no Lambda handler, so none is claimed.

### v2 (built 2026-10-10 on this VM; live proof still pending)
- **Operator console** at `/console`, served by the same app: request
  input, the route decision, Approve/Deny buttons on gated proposals,
  live status panels for Bedrock / DynamoDB / Lambda, and an audit
  history table. Every result is badged **live / stub / persisted**
  (persisted only when DynamoDB actually stored it).
- **Two-step approval**: a gated request creates a PENDING proposal
  and executes nothing — no probes, no model call. Approve runs it
  (`bedrock_agent.execute_approved()`) and audits the run; Deny is
  audited and executes nothing.
- **Multi-service orchestration**: one request probes Bedrock,
  DynamoDB, and Lambda in sequence, combines the results, routes, and
  writes **one** audit record for the whole run.
- **Cross-session history**: `ledger.read_history()` reads the audit
  trail back with a DynamoDB Query on the one table (same session id),
  falling back to labeled memory when no table/credentials exist.
- Still stub here: no AWS credentials on this VM, so the console shows
  `stub` / `memory (not persisted)` and says so. The live proof
  (real model reply, `persisted: true`) happens once, later, at the
  owner's PC with his own AWS sign-in. See TEST_RECEIPT.md.
- The `/mcp/v1/*` REST/SSE routes and `/health` are a legacy
  compatibility shim from the first prototype, kept working and tested,
  but they are not part of MCP. The MCP endpoint is `/mcp`.

### Model choice (v2.1)
The model call goes through the Bedrock **Converse API**, which is
provider-agnostic — one request/response shape for Claude, Amazon
Nova, Meta Llama, Mistral, and the other Converse-supported models.
`BEDROCK_MODEL_ID` wins when set; the default is
`anthropic.claude-sonnet-5` (the primary target). On a brand-new AWS
account, Anthropic models refuse invocation ("not available for this
account") until the one-time use-case-details form is approved; until
then, `amazon.nova-lite-v1:0` or `amazon.nova-pro-v1:0` normally work
immediately, through the identical code path — set the env var and
nothing else changes. Errors still return `live: false` with the real
error named; no path fabricates a model reply.

## Architecture
```
                 ┌──────────────────────────────────────────────┐
  Operator ────► │  /console  (web UI)    /mcp  (MCP, SDK)      │
  (browser)      │        │                   ▲                 │
                 │        ▼                   │ tools/call      │
                 │  /console/api/*     system_probe             │
                 │        │            audit_ledger             │
                 ▼        ▼            bedrock_route             │
            ┌─────────────────────┐      │                       │
            │   orchestrator.py   │──────┘                       │
            │  gate -> PENDING    │                              │
            │  proposal           │   probes (read-only, lazy    │
            │  Approve -> execute │────────► boto3)              │
            │  Deny    -> audit   │   Bedrock / DynamoDB /       │
            └─────────┬───────────┘   Lambda, sequence           │
                      │ one audit record per run                 │
                      ▼                                          │
            ┌─────────────────────┐   PutItem + Query (one       │
            │     ledger.py       │── table, terraform IAM) ──►  │
            │  SHA-256 chain      │   DynamoDB audit table       │
            │  + read_history()   │   (falls back to labeled     │
            └─────────────────────┘    memory when not live)     │
                 └──────────────────────────────────────────────┘
```
Safety shape: gated prompts never execute on submit; approval is a
human click; approval itself only runs a Bedrock call (no code path
mutates AWS resources); every outcome is labeled live / stub /
persisted exactly as it happened.

## Layout
```
server.py            Official MCP SDK server (Streamable HTTP, /mcp) + console + legacy shim
orchestrator.py      v2: two-step approval, multi-service probes, one audit record per run
bedrock_agent.py     Bedrock router + approved execution + read-only probes (offline fallback)
ledger.py            SHA-256 audit ledger (memory + DynamoDB persist + Query read-back)
terraform/main.tf    DynamoDB audit table + least-privilege IAM policy (PutItem + Query)
terraform/outputs.tf Table name / ARN, policy ARN outputs
tests/test_mcp.py    unittest: MCP protocol, tools, gate, ledger, approval, orchestration, history, console
FRICTION_LOG.md      Build/usage friction log (honest, from the real build record)
.env.example         Runtime switches (no secrets)
requirements.txt
LICENSE              MIT
```

## Setup
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run the tests
```bash
python -m unittest discover -s tests -v
# or, from the repo root:
python -m unittest tests/test_mcp.py
```

## Run the server
```bash
python server.py
# MCP (Streamable HTTP): http://127.0.0.1:8000/mcp
# Health:                http://127.0.0.1:8000/health
# Legacy shim:           GET /mcp/v1/tools, POST /mcp/v1/execute
```
Or `uvicorn server:app --host 0.0.0.0 --port 8000` for the ASGI app.

## Run the operator console (v2)
One command, after the venv setup above:
```bash
python server.py
# then open: http://127.0.0.1:8000/console
```
What you get (all stub on a credential-less machine, badged as such):
type an ops request → see the route decision → gated actions wait as
PENDING proposals until you click Approve (execute + audit) or Deny
(audit only) → status panels for Bedrock/DynamoDB/Lambda → audit
history table read back from the ledger. For a live run, set the
switches from `.env.example` first (`BEDROCKOPS_LIVE=1`,
`AUDIT_TABLE_NAME=bedrockops-audit-ledger`, real AWS credentials via
your own sign-in).

The console API has **no authentication** — it is a local demo
surface. Keep it on localhost; do not port-forward it.

Note for this VM only: local HTTP clients must run with the proxy vars
unset (`env -u http_proxy -u https_proxy -u no_proxy ...`), or httpx
misroutes localhost. This is an environment quirk, not an app setting.

## Demo
See `demo/RECORDING_RUNBOOK.md` for the one-take, under-3-minute
recording script, `demo/demo_client.py` for the client that drives the
six narrated steps, and `demo/demo_transcript_2026-10-06.txt` for a
real offline run (stub/memory/live:false labels and all).

## Infrastructure (optional, requires an AWS account)
```bash
cd terraform
terraform init
terraform plan   # review before any apply; apply creates real resources
```

## What a judge should not yet conclude
The tests prove a real official-SDK MCP server speaking 2025-11-25
with three working tools, an approval gate, and a DynamoDB write path
proven against a fake client. They do not prove a live Bedrock call,
a successful live AWS probe, or a real DynamoDB write — this build VM
has no AWS credentials, and the code says so in every result
(`"live": false`, `persisted: false`, `UNREACHABLE`). One credentialed
run at the owner's PC closes those three, using `.env.example`.
