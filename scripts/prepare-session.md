# prepare-session — Step 0 for the BedrockOps live-proof sitting

Companion to `prepare-session.ps1`. Read this before the sitting.
**No live claims:** this script prepares one PowerShell window and
proves nothing. Live proof (`live: true`, `persisted: true`,
`HEALTHY / live`) happens later, at the run, with Soundwave, one
command per message.

## What the script prepares

- Verifies PowerShell, git, python, and the AWS CLI — each missing
  tool stops the script with the exact remediation line.
- Clones or fast-forward-updates `~\bedrockops-pc`
  (`https://github.com/RwTraylor/BedrockOps`); never forces, never
  deletes.
- Confirms YOUR AWS sign-in via `aws sts get-caller-identity`. It
  never reads, prints, or stores credential values.
- Ensures the DynamoDB audit table exists:
  `bedrockops-audit-ledger`, `SessionId` String (HASH),
  `Timestamp` Number (RANGE), on-demand (`PAY_PER_REQUEST`) —
  via Terraform if terraform is on PATH, else via
  `aws dynamodb create-table`, and only after a describe-table
  check shows it missing.
- Sets four env vars in that window only:
  `BEDROCKOPS_LIVE=1`, `AUDIT_TABLE_NAME=bedrockops-audit-ledger`,
  `AWS_REGION=us-east-1`, `BEDROCK_MODEL_ID=anthropic.claude-sonnet-5`.

## Run order

1. Open **Windows PowerShell** (5.1). If the script is refused
   ("running scripts is disabled"), allow it for this window only:
   `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
2. `cd` to the folder holding the script; run `.\prepare-session.ps1`.
3. Answer the prompts (below). 
4. **Leave that window open.** Env vars die with the window; if it
   closes, re-run the script — it is idempotent.
5. In the same window, with Soundwave one command per message:
   activate the venv → run the tests → run the server → open
   `http://127.0.0.1:8000/console`.

## Consent points (nothing happens without your yes)

| # | Prompt | What it does |
|---|--------|--------------|
| 1 | Clone the repo | One-time clone into `~\bedrockops-pc` (an existing clone is only fast-forward pulled) |
| 2 | Pause after `aws configure sso` | YOU run the SSO sign-in in YOUR browser; the script only waits, then re-checks identity |
| 3 | Model access confirmation | YOU confirm `anthropic.claude-sonnet-5` shows **Access granted** in the Bedrock console (us-east-1); Anthropic's one-time use-case form is your words, your click |
| 4 | Create the table | Only if describe-table says it is missing |
| 5 | Terraform apply | Only after YOU read the plan (table + one IAM policy, nothing else) |
| 6 | venv + requirements | Creates `.venv` in the clone and installs `requirements.txt` |

## Screenshots — what to capture and where they go

Capture these outputs from the prepared window/console, eyeball each
frame first, then send them to Soundwave in chat:

1. The test run ending in `OK` with the full count.
2. `system_probe` showing `HEALTHY` with live mode on.
3. `bedrock_route` showing `live: true` and the model's actual reply.
4. `audit_ledger` showing `persisted: true`.
5. Optional: the `/console` screen with the honest badges visible.

Keep the original PNGs in the clone's `demo\` folder (next to
`RECORDING_RUNBOOK.md`) so the refreshed demo and the receipts live
together. A screenshot only counts if NO credential-looking string is
anywhere in the frame — check the title bar, other tabs, and any
terminal scrollback before sending.

## What never appears in chat, screenshots, or git

- AWS access key IDs, secret access keys, session tokens.
- The contents of `~/.aws` (config and credentials files).
- SSO codes, browser sign-in URLs/codes, one-time codes of any kind.
- `terraform.tfstate`.
- `.env` files and anything that quotes the values above.

`aws sts get-caller-identity` output (Account/UserId/Arn) is fine to
show — it contains no key material.

## If something stops

- **Script blocked by execution policy** → the one-line bypass in
  step 1 above, then re-run.
- **Still not signed in after SSO** → finish the browser flow, check
  `aws configure list`, re-run the script.
- **Model access pending** → the run waits; do the console/demo prep
  instead. Never edit Devpost "live" sentences ahead of the run.
- **Table already exists** → the script says so and creates nothing.
  That is the expected state on any re-run.
- **Region** → everything here is `us-east-1` (N. Virginia). If the
  AWS console opens in another region, switch the console picker;
  the script pins `AWS_REGION=us-east-1` regardless.
