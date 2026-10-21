# BedrockOps — Devpost v2 replacement copy (DRAFT — NOT SUBMITTED)

> **Internal draft. Do not paste into Devpost yet.**
> Lines marked `[AFTER LIVE RUN: ...]` describe things that must be
> proven in a credentialed live run first. Delete a bracketed line —
> and keep only what printed `live: true` / `persisted: true` —
> after the run. **Nothing in this file has been submitted anywhere.**
> The v1 listing stays exactly as it is unless v2 passes every gate.

---

## What the judges should run first

1. `python -m unittest discover -s tests` — the full suite, no AWS credentials needed; every stub path is tested and labeled.
2. `python server.py`, then open `http://127.0.0.1:8000/console` — the operator console; submit a gated request and watch it wait as PENDING until a human clicks Approve or Deny.
3. [AFTER LIVE RUN: with `BEDROCKOPS_LIVE=1`, `AUDIT_TABLE_NAME=bedrockops-audit-ledger`, and your own AWS sign-in, re-run and watch the badges turn `live` / `persisted` — the audit row is then readable in the DynamoDB table.]

---

## Draft project description (full)

### The problem

Coverage outside business hours usually means one solo operator — or a
two-person team — holding real production risk at 2 a.m. The dangerous
moment is not a lack of tools; it is a tired human (or an eager AI)
running the wrong action with nobody accountable for the yes.
BedrockOps is built for that moment: an AI operations agent that is
not allowed to act on a gated request until a named human approves it,
and that keeps the receipt either way.

### What BedrockOps is now

BedrockOps is an open-source (MIT) cloud operations agent built on the
**official MCP Python SDK** — a Streamable HTTP server (protocol
2025-11-25) exposing three tools: `system_probe`, `bedrock_route`,
and `audit_ledger`. v2 adds an **operator console** at `/console`,
served by the same app: type an ops request, see the route decision,
watch service status panels for Bedrock / DynamoDB / Lambda, and read
the audit history back in the same screen. Every result is badged
exactly as it happened — `live`, `stub`, or `persisted` — and the
code returns `"live": false` / `persisted: false` rather than
simulating success when credentials or services are absent.

### Two-step approval: the gate is the feature

A destructive or high-spend request does not execute. It becomes a
**PENDING proposal**: no probes run, no model call fires. A human
clicks **Approve** — only then does the routed request execute
(`bedrock_agent.execute_approved()`) — or **Deny**, which executes
nothing. Both outcomes are written to the audit ledger. Approval in
BedrockOps deliberately runs a routed Bedrock model call; there is
**no code path that mutates AWS resources**, even after approval.
That scope limit is a design decision, stated here on purpose.

### Multi-service orchestration, one audit record

A single request can probe **Bedrock, DynamoDB, and Lambda in
sequence**, combine the results, route, and write exactly **one**
`orchestration_run` audit record for the whole run — orchestration,
not a single API call dressed up as one. Probes are read-only and
fail closed: an unreachable service reports `UNREACHABLE`, it never
fakes `HEALTHY`.

### Audit history that survives restarts

The ledger is a SHA-256-chained audit trail persisted to a single
DynamoDB table (`bedrockops-audit-ledger`: `SessionId` String
partition key, `Timestamp` Number sort key, on-demand billing).
`read_history()` reads it back with a DynamoDB **Query on that one
table** — scoped to the operator session, so restarts of the same
session see the trail; it never widens to a Scan. When no table or
credentials exist, the fallback is labeled `source: memory` — history
that is *not* persisted is never presented as persisted. Terraform
defines exactly this: the table plus a least-privilege IAM policy
(`PutItem` + `Query`, one table ARN, nothing else).

### Named impact scenario

A solo cloud-ops operator is paged at 02:00 for a degraded service.
The request that would "fix it fast" is also the one that could delete
the production database. In BedrockOps, that request stops at the
gate as a pending proposal; the operator reads the route decision,
approves the safe action (or denies the dangerous one), and the
approved run completes with its audit record persisted and readable
across sessions — a named human accountable for the yes, with the
receipt to prove it. No invented users, no testimonials; this is the
workflow the tool is built to serve.

### Reproducible architecture

```
Operator ──► /console (web UI) ──► orchestrator.py
                                  gate -> PENDING proposal
                                  Approve -> execute + audit
                                  Deny    -> audit only
MCP client ─► /mcp (official SDK, Streamable HTTP, 2025-11-25)
                                  system_probe / bedrock_route / audit_ledger
Probes (read-only, boto3): Bedrock, DynamoDB, Lambda
Ledger: SHA-256 chain -> DynamoDB PutItem + Query (one table)
infra: terraform/main.tf (table + least-privilege IAM)
```

One command runs it locally (`python server.py`); the console is a
localhost demo surface with no authentication — documented as such,
never to be port-forwarded. **26 automated tests** cover the MCP
protocol, the approval gate (submit executes nothing), the deny path,
stub orchestration, history read-back and its memory fallback, and the
console API — all without AWS credentials.

### Friction log

What building this actually taught us is in the repo, unedited:
**[FRICTION_LOG.md](https://github.com/RwTraylor/BedrockOps/blob/main/FRICTION_LOG.md)**
— ten real items in Task / Steps / Expected vs Actual / Severity /
Workaround / Suggestion format, including the honest headliner: no
live AWS proof existed at build time, so every live path ships
labeled until a credentialed run closes it.

### Live proof — the part this draft does not claim

[AFTER LIVE RUN: BedrockOps was run live on the owner's own AWS account: `system_probe` returned HEALTHY in live mode, `bedrock_route` returned `live: true` with a real `anthropic.claude-sonnet-5` response, and `audit_ledger` returned `persisted: true` against the real `bedrockops-audit-ledger` table, with the records read back via Query. Demo refreshed to show `live: true` / `persisted: true`.]

[AFTER LIVE RUN: `terraform validate` / `plan` ran during the same sitting; the applied (or console-created) table matches `terraform/main.tf` — PutItem + Query on the one table ARN.]

Until those brackets are earned, the honest shipped sentence is the
one already in the README: the tests prove a real official-SDK MCP
server with a working approval gate, orchestration, and a DynamoDB
write path proven against a fake client; a live Bedrock call, a
successful live AWS probe, and a real DynamoDB write are **not yet
proven**, because the build machine has no AWS credentials — and the
code says so in every result.

---

## 240-word version (about 240 words)

BedrockOps is an open-source (MIT) cloud operations agent for solo and small-team operators who cover incidents outside business hours and still need a human accountable for what runs. An operator types a request into a local web console. BedrockOps routes it, probes Bedrock, DynamoDB, and Lambda in sequence, and shows the route decision with honest badges: live, stub, or persisted. Anything destructive or expensive stops as a pending proposal and executes nothing. A human clicks Approve before the action runs, or Deny to stop it; both outcomes are written to a SHA-256-chained audit ledger. The ledger persists to a single DynamoDB table and reads back across sessions, so the trail survives restarts. Built on the official MCP Python SDK (Streamable HTTP, protocol 2025-11-25) with three tools — system_probe, bedrock_route, audit_ledger — the same safety shape serves MCP clients and the console. Terraform defines exactly the table and the least-privilege IAM the code calls (PutItem + Query, one table). Twenty-six automated tests run without credentials, and every code path that has not seen a live AWS account says so instead of faking it. BedrockOps is scoped honestly: approval gates execution, execution is a routed model call, and no code path mutates AWS resources. It was designed for the 2 a.m. page: one tired operator, real risk, and a system that waits for a human yes before it acts, then keeps the receipt. The friction log of what building it taught us ships in the repo.

[AFTER LIVE RUN: swap "has not seen a live AWS account" claims as needed and add one sentence with the live result — and only what the run actually printed.]

---

## Paste checklist (for the human doing the Devpost edit)

- [ ] Live run completed and screenshots verified — no credential
      visible in any frame.
- [ ] Every `[AFTER LIVE RUN: ...]` bracket either deleted (claim
      proven) or the whole line removed (claim not proven). No
      bracket text ships.
- [ ] The 240-word version re-read against the same rule.
- [ ] Friction-log link confirmed live in the public repo.
- [ ] Save is the owner's click, via the owner's signed-in session.
- [ ] v1 wording replaced only where the run changed the facts.
