# BedrockOps — Autonomous Cloud Operations & Audit Agent

Open-source (MIT) cloud operations agent scaffold for the
Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track;
AWS Builder + Open Source mini-challenges).

## Status — read this first (2026-10-06)
- `server.py` is built on the **official MCP Python SDK** (`mcp==2.3.0`,
  `MCPServer` — the v2 name for FastMCP) and serves Streamable HTTP at
  `/mcp`. Verified on this machine:
  - `python -m unittest tests/test_mcp.py` → exit 0, **8 tests OK**,
    including raw JSON-RPC initialize negotiating **2025-11-25**,
    tools/list, and tools/call for both tools.
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
  a live Bedrock InvokeModel call, a live AWS probe succeeding, and a
  real DynamoDB write. Those need one run at Ricket's PC with his own
  AWS login. See `.env.example` for the exact switches.
- Terraform now defines the DynamoDB table plus a least-privilege IAM
  policy matching exactly what the code calls (Bedrock invoke/list,
  Lambda/DynamoDB list, DynamoDB PutItem to the one table). HCL files
  parse (python-hcl2); `terraform validate/apply` has not run — no
  terraform binary on this VM. There is deliberately no Lambda
  function: the code has no Lambda handler, so none is claimed.
- The `/mcp/v1/*` REST/SSE routes and `/health` are a legacy
  compatibility shim from the first prototype, kept working and tested,
  but they are not part of MCP. The MCP endpoint is `/mcp`.

## Layout
```
server.py            Official MCP SDK server (Streamable HTTP, /mcp) + legacy shim
bedrock_agent.py     Bedrock router + read-only AWS probes (lazy boto3, offline fallback)
ledger.py            SHA-256 audit ledger (memory + optional DynamoDB persistence)
terraform/main.tf    DynamoDB audit table + least-privilege IAM policy
terraform/outputs.tf Table name / ARN, policy ARN outputs
tests/test_mcp.py    unittest: MCP protocol, tools, gate, ledger, DynamoDB fake client
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
