# Demo recording runbook — one take, target 2:30 (hard cap 3:00)
# Rules checked 2026-10-06: public YouTube/Vimeo, English, <3:00,
# no third-party trademarks or copyrighted music, label simulated parts.

## Setup (before you hit record)
- Fresh clone of the BedrockOps repo, venv ready: `pip install -r requirements.txt`
- Two terminals, font large enough to read on video, dark theme fine.
- Optional honest upgrade: if recording on a machine with your AWS login,
  set BEDROCKOPS_LIVE=1 and AUDIT_TABLE_NAME=<your table> first, and say
  so on camera. Otherwise the defaults are fine — the labels in the output
  already say stub/memory/live:false, and that honesty is a feature, not a flaw.

## The take
Terminal 1: `python server.py`  (leave the startup banner on screen)
Terminal 2:
1. (0:00–0:15) Say the hook while the banner shows:
   "BedrockOps turns a plain-language ops request into an audited,
   gated AWS action, through a real MCP server. Watch it answer."
2. (0:15–0:25) Run: `python -m unittest tests/test_mcp.py`
   Say: "Thirteen tests, exit zero, including the MCP handshake."
3. (0:25–2:10) Run: `python demo/demo_client.py`
   Narrate the six printed steps as they appear:
   initialize negotiates 2025-11-25 → tools/list → system_probe →
   the delete prompt stops at requires_approval (pause on this; it's
   the safety story) → audit routing says live:false without
   credentials → audit_ledger shows sha256 + persisted state.
4. (2:10–2:30) Close on the repo README in the browser (after push):
   MIT license, setup in three commands, and:
   "Open source, MIT, link below. Next: the same run, live on AWS."

## After recording
- Trim dead air at the head/tail only. Keep it unedited during the tool calls.
- Upload to YouTube as Public, title: "BedrockOps — MCP cloud ops agent (Amazon Developer Hackathon)"
- Paste the URL into artifacts/SUBMISSION_DRAFT.md (video field) and the Devpost form.

## Honesty checklist while narrating
- Say "stub telemetry" when system_probe shows mode="stub". Do not say "live AWS health".
- Say "would call Bedrock live with credentials" for bedrock_route when live=false.
- Say "in-memory for this run" when persisted=false.
