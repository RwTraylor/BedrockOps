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
"""
import hashlib
import json
import os
import time
from typing import AsyncGenerator

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

import bedrock_agent
from ledger import AuditLedger

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
