"""
BedrockOps demo client — the exact flow to screen-record.

Prereqs (terminal 1):
    python server.py            # MCP server on http://127.0.0.1:8000/mcp

Run (terminal 2):
    python demo/demo_client.py

Every line of output is honest about what is live vs stubbed:
system_probe says mode="stub" (or live/UNREACHABLE with BEDROCKOPS_LIVE=1),
audit_ledger says persisted true/false, bedrock_route says live true/false,
and the destructive prompt is stopped by the approval gate.
"""
import anyio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("BEDROCKOPS_URL", "http://127.0.0.1:8000/mcp")


def show(title, result):
    text = result.content[0].text if result.content else "(no content)"
    print(f"\n=== {title} (isError={result.is_error}) ===")
    print(text)


async def main():
    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("=== STEP 1: MCP initialize (Streamable HTTP) ===")
            print(f"protocol negotiated: {init.protocol_version}")
            print(f"server: {init.server_info.name} {init.server_info.version}")

            tools = await session.list_tools()
            print("\n=== STEP 2: tools/list ===")
            for tool in tools.tools:
                print(f"- {tool.name}")

            show("STEP 3: system_probe dynamodb",
                 await session.call_tool("system_probe", {"target_service": "dynamodb"}))

            show("STEP 4: bedrock_route — destructive prompt hits the human gate",
                 await session.call_tool("bedrock_route", {"prompt": "delete the production database"}))

            show("STEP 5: bedrock_route — normal audit request (live Bedrock only with credentials)",
                 await session.call_tool("bedrock_route", {"prompt": "audit last night's deployment"}))

            show("STEP 6: audit_ledger — SHA-256 + persistence state",
                 await session.call_tool("audit_ledger", {"payload": "demo-run-2026-10-06"}))

    print("\n=== DEMO COMPLETE ===")


if __name__ == "__main__":
    anyio.run(main)
