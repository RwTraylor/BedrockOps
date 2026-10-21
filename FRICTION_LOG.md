# BedrockOps — Friction Log

Drafted by Soundwave from the actual build record (2026-10-06 v1 build,
2026-10-10 v2 build). Format per item: Task / Steps / Expected vs
Actual / Severity / Workaround / Suggestion. Nothing here is invented:
every entry either appears in TEST_RECEIPT.md, the git history, or was
hit while building v2 on this VM.

## 1. No live AWS proof — every "live" path is capped at stub
- **Task:** Prove a real Bedrock InvokeModel, a successful live probe,
  and a real DynamoDB write.
- **Steps:** Ran the full suite and the live-mode server on the build VM.
- **Expected:** One credentialed run closes all three. **Actual:** This
  VM has no AWS credentials (no ~/.aws, no AWS env keys; the SDK raises
  NoCredentialsError), so results are honestly labeled instead:
  `live: false` with `fallback_reason: NoCredentialsError`, probes
  `UNREACHABLE / live_failed`, audit `persisted: false / store: memory`.
- **Severity:** High — it caps the Technical Implementation score until
  proven.
- **Workaround:** The credentialed live-proof PC session (Soundwave's
  session sheet): owner signs in to AWS himself, flips
  `BEDROCKOPS_LIVE=1` + `AUDIT_TABLE_NAME`, re-runs.
- **Suggestion:** Keep the honesty labels in the code and the console
  badges forever; a stub result must never render as "live".

## 2. IAM policy trailed the code by one permission (Query)
- **Task:** Add cross-session audit history read-back (ledger
  `read_history()`, DynamoDB Query on the one table).
- **Steps:** Reviewed `terraform/main.tf` against the new code path.
- **Expected:** Policy already matches what the code calls. **Actual:**
  v1 policy allowed `dynamodb:PutItem` only — the v2 Query would have
  been denied live.
- **Severity:** Medium.
- **Workaround / Fix:** Terraform updated in v2 (`PutItem` + `Query`,
  same single table ARN, nothing else widened). `terraform validate`
  has not run — no terraform binary on this VM.
- **Suggestion:** Re-diff policy statements against code on every ledger
  change; run `terraform validate` in the same sitting as the first
  `plan`.

## 3. v1 was terminal-only
- **Task:** Present BedrockOps to judges as an operator tool.
- **Steps:** Reviewed the v1 submission surface.
- **Expected:** A console an operator (and a judge) can drive. **Actual:**
  v1 offered MCP tools plus a scripted terminal demo client; the
  approval gate existed but was only visible as JSON in a transcript.
- **Severity:** Medium (Design criterion).
- **Workaround / Fix:** v2 adds the operator console at `/console`
  (request input, route decision, Approve/Deny, service status panels,
  audit history table, honest badges).
- **Suggestion:** Film demos through the UI; keep the terminal as the
  fallback view, not the product.

## 4. The approval gate is substring keyword matching
- **Task:** Stop destructive/high-spend requests before anything runs.
- **Steps:** `route_request()` lowercases the prompt and checks for
  `delete` / `destroy` / `provision_high_spend`.
- **Expected:** Semantic risk detection. **Actual:** False positives
  gate harmless prompts ("delete-protection report", "do not delete"),
  and risky synonyms ("terminate", "drop", "purge") slip past. It
  fails closed, which is the safe direction, but it is crude.
- **Severity:** Medium.
- **Workaround:** The v2 two-step gate puts a human on every gated
  prompt (Approve/Deny), so false positives cost one click; audited
  either way.
- **Suggestion:** Move risk classification to the routed model call and
  keep the keyword list as a hard backstop that can only add gates,
  never remove them.

## 5. Console endpoints have no authentication
- **Task:** Expose Approve/Deny over HTTP for the console.
- **Steps:** Added `/console/api/*` routes on the same app as `/mcp`.
- **Expected:** Operator-only control. **Actual:** Anyone who can reach
  the port can approve a proposal. Fine for a localhost demo; unsafe
  beyond it.
- **Severity:** Medium (High if the port is ever exposed).
- **Workaround:** Run the demo bound to 127.0.0.1; never port-forward
  the console.
- **Suggestion:** Add a shared-token header check to `/console/api/*`
  before any non-local deployment.

## 6. History read-back is scoped to one session partition
- **Task:** Read audit history across sessions from DynamoDB.
- **Steps:** `read_history()` issues one Query with
  `SessionId = :sid` (least privilege, matches terraform).
- **Expected:** The full audit trail. **Actual:** Restarts using the
  same session id see prior records; a different session id cannot.
  "Cross-session" therefore means across process restarts of the same
  operator session, not across operators.
- **Severity:** Low.
- **Workaround:** Keep the default session id for the demo trail.
- **Suggestion:** Only if cross-operator history becomes a real
  requirement, add a dedicated index partition — do not widen to Scan.

## 7. Test harness: the MCP app's session manager starts once per process
- **Task:** Add HTTP tests for the v2 console.
- **Steps:** Tried to give the new tests their own module + TestClient.
- **Expected:** Independent test modules. **Actual:** The SDK session
  manager behind the ASGI app can only start once per process (noted at
  the top of `tests/test_mcp.py` since v1), so the console tests had to
  join the existing module and share its one TestClient lifespan.
- **Severity:** Low.
- **Workaround:** Shared module-level client; unit tests (approval,
  orchestration, history) construct their own Orchestrator/AuditLedger
  and stay independent of HTTP.
- **Suggestion:** Leave it; splitting the file breaks the suite. The
  constraint is documented in the test module header comment.

## 8. boto3 first call stalls on IMDS; VM proxy quirk for local clients
- **Task:** Keep offline tests and local console checks fast and honest.
- **Steps:** Ran tests and the live server locally.
- **Expected:** Immediate NoCredentialsError. **Actual:** Without
  `AWS_EC2_METADATA_DISABLED=true`, boto3 stalls on the EC2 metadata
  lookup; separately, this VM's proxy vars make httpx misroute
  127.0.0.1 unless they are unset for local clients (recorded in
  TEST_RECEIPT.md during v1).
- **Severity:** Low.
- **Workaround:** Tests set the IMDS switch in `setUpModule`; local run
  commands use the proxy-unset env block (see README).
- **Suggestion:** Keep the env block at the top of every run instruction,
  not buried in a footnote — done in the README console section.

## 9. Terraform has never been validated/applied
- **Task:** Create the audit table + IAM policy as code.
- **Steps:** Authored `terraform/main.tf` (v1) and the v2 Query addition.
- **Expected:** `terraform validate` clean before claiming IaC.
  **Actual:** The HCL parses (python-hcl2), but there is no terraform
  binary on this VM, so validate/plan/apply have never run. No Lambda
  resource is defined, deliberately: the code has no handler.
- **Severity:** Medium.
- **Workaround:** The live-proof session sheet includes a console-path
  table creation as the fallback.
- **Suggestion:** Run init/plan/validate in the same PC sitting, before
  apply, and only with the owner's AWS sign-in.

## 10. Scope honesty: "execution" is a Bedrock call, not an AWS mutation
- **Task:** Make Approve actually do something after the human gate.
- **Steps:** Built `bedrock_agent.execute_approved()` for the v2 flow.
- **Expected:** Approved actions execute. **Actual:** Execution means
  the routed request runs (Bedrock InvokeModel when credentialed, the
  deterministic local router otherwise) and is audited. BedrockOps
  deliberately has no code path that deletes or provisions AWS
  resources, even after approval.
- **Severity:** Info — scope clarity, recorded so nobody over-claims it.
- **Workaround:** n/a.
- **Suggestion:** If a future tool adds mutating actions, each one
  needs its own confirmation, dry-run, and rollback story — the
  two-step gate alone is not enough.

## 11. Anthropic access gate forced a provider-agnostic invoke
- **Task:** Make the live model call possible on the owner's new AWS
  account.
- **Steps:** Defaulted the router to `anthropic.claude-sonnet-5` and
  built the call as an Anthropic-only InvokeModel payload.
- **Expected:** New account + use-case form = invocable model.
  **Actual:** Anthropic refuses first-time invocation on the account
  until its use-case approval lands ("not available for this
  account") — a vendor-side gate with no stated ETA, sitting in front
  of an otherwise finished live proof.
- **Severity:** Medium.
- **Workaround:** v2.1 (2026-10-10): the invoke path now uses the
  Bedrock Converse API, which is provider-agnostic, so any
  Converse-supported model works through the same code — including
  Amazon Nova, which normally answers immediately on a new account.
  `BEDROCK_MODEL_ID` selects the model; the Claude default is
  unchanged, and nothing was claimed live before a real call happens.
- **Suggestion:** Never pin a demo-critical path to a single vendor's
  approval queue; prefer provider-agnostic APIs (Converse over
  per-vendor InvokeModel payloads) whenever the contract allows.
