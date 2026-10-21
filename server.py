"""
BedrockOps - Self-Hosted MCP Server
SDK: official Model Context Protocol Python SDK (mcp 2.3.0, MCPServer)
Transport: Streamable HTTP at /mcp (spec 2025-11-25 or later)

Verified locally (see TEST_RECEIPT.md): a JSON-RPC initialize requesting
protocolVersion 2025-11-25 negotiates 2025-11-25, tools/list returns both
tools, and tools/call executes them.

Honest scope:
- system_probe returns local stub telemetry (mode="stub") by default.
  With BEDROCKOPS_LIVE=1 it makes one real read-only AWS call and
  reports mode="live", or status UNREACHABLE / mode="live_failed".
  No live call is claimed on this VM: no AWS credentials are present.
- bedrock_route calls bedrock_agent.invoke(): a live Amazon Bedrock
  call only when credentials are configured (result carries
  "live": true); otherwise a deterministic local routing decision
  with "live": false. Destructive/high-spend prompts stop at a
  human-approval gate and never reach AWS.
- audit_ledger persists to DynamoDB when AUDIT_TABLE_NAME is set
  (result says persisted true/false; on this VM it is memory-only).
- The /mcp/v1/* routes below are a legacy REST/SSE compatibility shim
  kept from the first prototype. The MCP endpoint is /mcp.

v2 additions (same honest core, new surface):
- /console serves the operator console (request input, route decision,
  Approve/Deny on gated proposals, service status panels, audit
  history). /console/api/* is its JSON backend.
- orchestrator.py runs one request across Bedrock + DynamoDB + Lambda
  probes, routes it, and writes one audit record per run. Gated
  requests stop as PENDING proposals and execute nothing until an
  operator approves; approval runs bedrock_agent.execute_approved().
- ledger.read_history() reads audit history back from DynamoDB (Query
  on the one table) with a labeled memory fallback.
- Everything is still stub on this VM: no AWS credentials are present,
  and the console badges say so (live / stub / persisted).
"""
import hashlib
import json
import os
import time
from typing import AsyncGenerator

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

import bedrock_agent
from ledger import AuditLedger
from orchestrator import Orchestrator

ALLOWED_SERVICES = ("lambda", "dynamodb", "bedrock")

ledger = AuditLedger()

mcp = MCPServer(
    "BedrockOps",
    version="1.0.0",
    instructions=(
        "BedrockOps cloud operations tools. system_probe is stub "
        "telemetry unless BEDROCKOPS_LIVE=1; audit_ledger returns a "
        "SHA-256 integrity hash and persists to DynamoDB when "
        "AUDIT_TABLE_NAME is set; bedrock_route stops gated actions "
        "for human approval and only calls Bedrock live with credentials."
    ),
)


def _probe(target_service: str) -> dict:
    if target_service not in ALLOWED_SERVICES:
        raise ValueError(
            f"target_service must be one of {list(ALLOWED_SERVICES)}, got {target_service!r}"
        )
    if os.environ.get("BEDROCKOPS_LIVE") == "1":
        try:
            result = bedrock_agent.probe_service(target_service)
            result["timestamp"] = time.time()
            return result
        except Exception as exc:  # report failure, never fake HEALTHY
            return {
                "status": "UNREACHABLE",
                "mode": "live_failed",
                "service": target_service,
                "error": type(exc).__name__,
                "timestamp": time.time(),
            }
    return {
        "status": "HEALTHY",
        "service": target_service,
        "mode": "stub",
        "latency_ms": 14.2,
        "timestamp": time.time(),
    }


def _audit(payload: str) -> dict:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    ledger.record_event("audit_ledger", {"payload": payload})
    entry = ledger.entries[-1] if ledger.entries else {}
    return {
        "verified": True,
        "sha256": digest,
        "persisted": bool(entry.get("persisted")),
        "store": "dynamodb" if entry.get("persisted") else "memory",
        "timestamp": time.time(),
    }


# v2: two-step approval + multi-service orchestration over the same ledger.
orchestrator = Orchestrator(ledger, _probe)


@mcp.tool()
def system_probe(target_service: str) -> dict:
    """Run a diagnostic telemetry probe on a target AWS service.

    target_service: one of "lambda", "dynamodb", "bedrock".
    Stub telemetry (mode="stub") unless BEDROCKOPS_LIVE=1, in which case
    one real read-only AWS call is made (mode="live"), or the result is
    UNREACHABLE / live_failed. Health is never faked.
    """
    return _probe(target_service)


@mcp.tool()
def audit_ledger(payload: str) -> dict:
    """Calculate the SHA-256 state integrity hash of a payload for audit compliance.

    Persists the event to DynamoDB when AUDIT_TABLE_NAME is configured;
    the result states persisted true/false and the store actually used.
    """
    return _audit(payload)


@mcp.tool()
def bedrock_route(prompt: str) -> dict:
    """Route a plain-language operations request, with a human gate.

    Destructive or high-spend requests return action="requires_approval"
    and never reach AWS. Otherwise this calls Amazon Bedrock when
    credentials are configured ("live": true in the result) or returns
    a deterministic local routing decision ("live": false).
    """
    return bedrock_agent.invoke(prompt)


# ---------------------------------------------------------------------------
# Legacy compatibility shim (pre-SDK prototype API). Not part of MCP.
# ---------------------------------------------------------------------------

LEGACY_TOOLS = [
    {
        "name": "system_probe",
        "description": "Executes diagnostic telemetry probe on target AWS infrastructure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_service": {"type": "string", "enum": list(ALLOWED_SERVICES)}
            },
            "required": ["target_service"],
        },
    },
    {
        "name": "audit_ledger",
        "description": "Calculates SHA-256 state integrity hash for audit compliance.",
        "inputSchema": {
            "type": "object",
            "properties": {"payload": {"type": "string"}},
            "required": ["payload"],
        },
    },
    {
        "name": "bedrock_route",
        "description": "Routes a plain-language ops request with a human approval gate; live Bedrock only with credentials.",
        "inputSchema": {
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
        },
    },
]


@mcp.custom_route("/mcp/v1/tools", methods=["GET"])
async def legacy_list_tools(request: Request):
    return JSONResponse({"tools": LEGACY_TOOLS})


@mcp.custom_route("/mcp/v1/execute", methods=["POST"])
async def legacy_execute_tool(request: Request):
    data = await request.json()
    tool_name = data.get("name")
    params = data.get("arguments", {})

    async def event_stream() -> AsyncGenerator[str, None]:
        yield f"event: start\ndata: {json.dumps({'status': 'executing', 'tool': tool_name})}\n\n"
        try:
            if tool_name == "system_probe":
                output = _probe(params.get("target_service", "unknown"))
            elif tool_name == "audit_ledger":
                output = _audit(params.get("payload", ""))
            elif tool_name == "bedrock_route":
                output = bedrock_agent.invoke(params.get("prompt", ""))
            else:
                output = {"error": f"Unknown tool: {tool_name}"}
        except ValueError as exc:
            output = {"error": str(exc)}
        yield f"event: result\ndata: {json.dumps(output)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok", "server": "BedrockOps", "mcp_endpoint": "/mcp"})


# ---------------------------------------------------------------------------
# Operator console (v2). Served by the same app; local-demo surface with
# no authentication — bind to localhost outside a trusted demo machine.
# ---------------------------------------------------------------------------

CONSOLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BedrockOps Operator Console</title>
<style>
 body{font-family:system-ui,sans-serif;margin:2rem;background:#0f1420;color:#e6ecf5}
 h1{font-size:1.4rem;margin-bottom:.2rem}
 .sub{color:#9fb0c9;margin-bottom:1.2rem}
 .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:1.2rem}
 .card{background:#182136;border:1px solid #263354;border-radius:8px;padding:1rem;margin-bottom:1.2rem}
 .card h3{margin:.1rem 0 .5rem;text-transform:capitalize}
 .badge{display:inline-block;padding:.1rem .5rem;border-radius:999px;font-size:.75rem;font-weight:600}
 .live{background:#14532d;color:#bbf7d0}.stub{background:#713f12;color:#fde68a}
 .persisted{background:#1e3a8a;color:#bfdbfe}.memory{background:#374151;color:#e5e7eb}
 .bad{background:#7f1d1d;color:#fecaca}.pending{background:#713f12;color:#fde68a}
 textarea{width:100%;box-sizing:border-box;background:#0f1420;color:#e6ecf5;border:1px solid #263354;border-radius:6px;padding:.6rem}
 button{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:.5rem 1rem;cursor:pointer}
 button.deny{background:#b91c1c} button.ghost{background:#263354}
 table{width:100%;border-collapse:collapse;font-size:.85rem}
 th,td{border-bottom:1px solid #263354;padding:.4rem;text-align:left;vertical-align:top}
 pre{background:#0b0f1a;border:1px solid #263354;border-radius:6px;padding:.7rem;overflow:auto;font-size:.8rem}
</style>
</head>
<body>
<h1>BedrockOps Operator Console</h1>
<div class="sub">Two-step approval &middot; multi-service orchestration &middot; honest live / stub / persisted badges. <span id="modeBanner"></span></div>

<div class="grid" id="statusPanels"></div>

<section class="card">
 <h3>New operations request</h3>
 <form id="reqForm">
  <textarea id="prompt" rows="3" placeholder="e.g. check service health / audit last night's run / delete the production database"></textarea>
  <p><button type="submit">Submit request</button> <button type="button" class="ghost" id="refreshBtn">Refresh panels</button></p>
 </form>
 <div id="routeBox"></div>
</section>

<section class="card">
 <h3>Pending proposals (human gate)</h3>
 <div id="proposals"><em>Loading...</em></div>
</section>

<section class="card">
 <h3>Audit history <span id="historySource"></span></h3>
 <table><thead><tr><th>Time</th><th>Action</th><th>Details</th><th>SHA-256</th><th>Store</th></tr></thead>
 <tbody id="historyBody"></tbody></table>
</section>

<script>
const $ = id => document.getElementById(id);
function esc(s){return String(s??"").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function badgeMode(mode){ if(mode==="live") return '<span class="badge live">live</span>'; if(mode==="live_failed") return '<span class="badge bad">unreachable</span>'; if(mode==="error") return '<span class="badge bad">error</span>'; return '<span class="badge stub">stub</span>'; }
function badgeStore(persisted){ return persisted ? '<span class="badge persisted">persisted</span>' : '<span class="badge memory">memory (not persisted)</span>'; }
async function loadStatus(){
  const r = await fetch('/console/api/status'); const data = await r.json();
  $('statusPanels').innerHTML = Object.entries(data.services).map(([name, svc]) =>
    `<div class="card"><h3>${esc(name)}</h3><div>${esc(svc.status)} ${badgeMode(svc.mode)}</div>` +
    (svc.error ? `<div>error: ${esc(svc.error)}</div>` : '') +
    (svc.detail ? `<div>${esc(JSON.stringify(svc.detail))}</div>` : '') + `</div>`).join('');
  const modes = Object.values(data.services).map(s => s.mode);
  $('modeBanner').textContent = modes.every(m => m === 'stub') ? 'STUB MODE: no live AWS calls are being made.' : '';
}
async function loadProposals(){
  const r = await fetch('/console/api/proposals'); const data = await r.json();
  if(!data.proposals.length){ $('proposals').innerHTML = '<em>No proposals yet.</em>'; return; }
  $('proposals').innerHTML = data.proposals.map(p =>
    `<div style="border-bottom:1px solid #263354;padding:.5rem 0">
       <div><strong>${esc(p.id)}</strong> <span class="badge ${p.status==='PENDING'?'pending':''}">${esc(p.status)}</span></div>
       <div>${esc(p.prompt)}</div>
       <div>route: ${esc(p.route.action)} (${esc(p.route.reason||'routed')})</div>
       ${p.status==='PENDING' ? `<button onclick="decide('${p.id}','approve')">Approve &amp; execute</button> <button class="deny" onclick="decide('${p.id}','deny')">Deny</button>` : ''}
     </div>`).join('');
}
async function loadHistory(){
  const r = await fetch('/console/api/history'); const data = await r.json();
  $('historySource').innerHTML = '&mdash; source: ' + esc(data.source) + ' ' + badgeStore(data.persisted);
  $('historyBody').innerHTML = data.entries.map(e =>
    `<tr><td>${esc(new Date(e.timestamp*1000).toLocaleTimeString())}</td><td>${esc(e.action)}</td>` +
    `<td>${esc(JSON.stringify(e.details).slice(0,140))}</td><td>${esc(String(e.sha256||'').slice(0,12))}&hellip;</td>` +
    `<td>${e.persisted ? '<span class="badge persisted">persisted</span>' : '<span class="badge memory">memory</span>'}</td></tr>`).join('');
}
async function decide(id, action){
  const r = await fetch('/console/api/proposals/' + action, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id})});
  const data = await r.json();
  if(data.run){
    const run = data.run;
    $('routeBox').innerHTML = `<p>Approved run: route <strong>${esc(run.route.action)}</strong> ${badgeMode(run.mode)} audit ${badgeStore(run.audit.persisted)}</p><pre>${esc(JSON.stringify(run, null, 2))}</pre>`;
  }
  await refresh();
}
async function refresh(){ await Promise.all([loadStatus(), loadProposals(), loadHistory()]); }
$('reqForm').addEventListener('submit', async ev => {
  ev.preventDefault();
  const prompt = $('prompt').value.trim();
  if(!prompt) return;
  const r = await fetch('/console/api/request', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({prompt})});
  const data = await r.json();
  if(data.status === 'pending'){
    $('routeBox').innerHTML = `<p><span class="badge pending">PENDING APPROVAL</span> Route: <strong>${esc(data.route.action)}</strong> &mdash; ${esc(data.route.reason||'')}. Nothing executed. Approve or deny below.</p>`;
  } else if(data.run){
    const run = data.run;
    $('routeBox').innerHTML = `<p>Route: <strong>${esc(run.route.action)}</strong> ${badgeMode(run.mode)} audit ${badgeStore(run.audit.persisted)}</p><pre>${esc(JSON.stringify(run, null, 2))}</pre>`;
  } else {
    $('routeBox').innerHTML = '<pre>' + esc(JSON.stringify(data, null, 2)) + '</pre>';
  }
  await refresh();
});
$('refreshBtn').addEventListener('click', refresh);
refresh();
</script>
</body>
</html>
"""


@mcp.custom_route("/console", methods=["GET"])
async def console_page(request: Request):
    return HTMLResponse(CONSOLE_HTML)


@mcp.custom_route("/console/api/status", methods=["GET"])
async def console_status(request: Request):
    return JSONResponse(
        {"services": {svc: _probe(svc) for svc in ("bedrock", "dynamodb", "lambda")}}
    )


@mcp.custom_route("/console/api/request", methods=["POST"])
async def console_request(request: Request):
    data = await request.json()
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required"}, status_code=400)
    return JSONResponse(orchestrator.submit(prompt))


@mcp.custom_route("/console/api/proposals", methods=["GET"])
async def console_proposals(request: Request):
    return JSONResponse({"proposals": orchestrator.list_proposals()})


async def _console_decide(request: Request, action: str):
    data = await request.json()
    proposal_id = data.get("id", "")
    try:
        if action == "approve":
            return JSONResponse(orchestrator.approve(proposal_id))
        return JSONResponse(orchestrator.deny(proposal_id))
    except KeyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@mcp.custom_route("/console/api/proposals/approve", methods=["POST"])
async def console_approve(request: Request):
    return await _console_decide(request, "approve")


@mcp.custom_route("/console/api/proposals/deny", methods=["POST"])
async def console_deny(request: Request):
    return await _console_decide(request, "deny")


@mcp.custom_route("/console/api/history", methods=["GET"])
async def console_history(request: Request):
    return JSONResponse(ledger.read_history(limit=50))


# ASGI app for `uvicorn server:app` and for tests.
# stateless_http + json_response keeps each JSON-RPC call self-contained.
app = mcp.streamable_http_app(stateless_http=True, json_response=True)


if __name__ == "__main__":
    # Official SDK runner: Streamable HTTP on 0.0.0.0:8000, path /mcp.
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8000,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
