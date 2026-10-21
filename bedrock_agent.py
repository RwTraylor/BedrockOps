"""
BedrockOps - Amazon Bedrock runtime router

Honest scope (2026-10-06): this module defines the routing harness the
submission draft describes. It creates a boto3 bedrock-runtime client
lazily, only when `invoke()` is called with real AWS credentials
available. Without credentials it returns a deterministic local routing
decision so the rest of the system (and the test suite) can run offline.
It does NOT claim a live Bedrock call has been made.
`probe_service()` makes one real read-only AWS call per service and
raises on failure rather than faking health.

v2.1 (2026-10-10): the model call now goes through the Bedrock
Converse API, which is provider-agnostic (Claude, Amazon Nova, Meta
Llama, Mistral, etc. all share one request/response shape). This
removes the old Anthropic-only InvokeModel payload, so BEDROCK_MODEL_ID
can point at any Converse-supported model without code changes.
"""
import os

DEFAULT_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-5")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def probe_service(service: str) -> dict:
    """
    Make ONE real, read-only AWS call for the named service.
    Raises on failure; the caller decides how to report it. Read-only
    probes only: list/describe, never create, modify, or delete.
    """
    from botocore.config import Config

    import boto3

    cfg = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})
    if service == "lambda":
        resp = boto3.client("lambda", region_name=AWS_REGION, config=cfg).list_functions(MaxItems=1)
        detail = {"functions_returned": len(resp.get("Functions", []))}
    elif service == "dynamodb":
        resp = boto3.client("dynamodb", region_name=AWS_REGION, config=cfg).list_tables(Limit=1)
        detail = {"tables_returned": len(resp.get("TableNames", []))}
    elif service == "bedrock":
        resp = boto3.client("bedrock", region_name=AWS_REGION, config=cfg).list_foundation_models()
        detail = {"models_returned": len(resp.get("modelSummaries", []))}
    else:
        raise ValueError(f"unknown service: {service!r}")
    return {"status": "HEALTHY", "mode": "live", "service": service, "detail": detail}

# Actions that must never execute without explicit operator approval.
GATED_ACTIONS = {"delete", "destroy", "provision_high_spend"}


def route_request(prompt: str) -> dict:
    """Deterministic local routing decision (offline fallback path)."""
    text = (prompt or "").lower()
    if any(word in text for word in GATED_ACTIONS):
        return {"action": "requires_approval", "reason": "gated action keyword", "prompt": prompt}
    if "audit" in text or "hash" in text:
        return {"action": "audit_ledger", "prompt": prompt}
    return {"action": "system_probe", "prompt": prompt}


def _converse_reply(prompt: str) -> dict:
    """
    One real Bedrock model call via the Converse API (provider-agnostic:
    the same call shape works for Anthropic, Amazon Nova, Meta Llama,
    Mistral, and the other Converse-supported families). Raises on any
    failure — callers translate that into an honest live=False result.
    Invocation only: this never mutates AWS state.
    """
    import boto3  # imported here so offline tests never require AWS

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    response = client.converse(
        modelId=DEFAULT_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 512},
    )
    message = response.get("output", {}).get("message", {})
    text = "".join(
        block.get("text", "")
        for block in message.get("content", [])
        if isinstance(block, dict)
    )
    return {
        "text": text,
        "stop_reason": response.get("stopReason"),
        "usage": response.get("usage", {}),
    }


def invoke(prompt: str) -> dict:
    """
    Call Amazon Bedrock if credentials/region are configured, else fall
    back to the local router. Returns a dict either way; the `live` flag
    says which path actually ran.
    """
    decision = route_request(prompt)
    if decision["action"] == "requires_approval":
        return {"live": False, **decision}

    try:
        payload = _converse_reply(prompt)
        return {"live": True, "model": DEFAULT_MODEL_ID, "response": payload, **decision}
    except Exception as exc:  # no credentials, no network, etc. — stay honest
        return {
            "live": False,
            "fallback_reason": type(exc).__name__,
            "error": str(exc),
            **decision,
        }


def execute_approved(prompt: str) -> dict:
    """
    Execute a request a human operator has explicitly approved.

    Makes the same Bedrock Converse call invoke() would make, but
    without re-applying the keyword gate: the v2 console gate (pending
    proposal + operator Approve click) is the control that replaces
    it. Nothing here mutates AWS state — the only outbound call is to
    Bedrock. Without credentials it returns live=False with the
    failure named, exactly like invoke(). Never call this without a
    recorded human approval in front of it.
    """
    decision = route_request(prompt)
    try:
        payload = _converse_reply(prompt)
        return {
            "live": True,
            "executed": True,
            "approved": True,
            "model": DEFAULT_MODEL_ID,
            "response": payload,
            **decision,
        }
    except Exception as exc:  # no credentials, no network, etc. — stay honest
        return {
            "live": False,
            "executed": True,
            "approved": True,
            "fallback_reason": type(exc).__name__,
            "error": str(exc),
            **decision,
        }
