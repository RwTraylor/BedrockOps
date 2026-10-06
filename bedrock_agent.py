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
"""
import json
import os

DEFAULT_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
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
        import boto3  # imported here so offline tests never require AWS

        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        })
        response = client.invoke_model(modelId=DEFAULT_MODEL_ID, body=body)
        payload = json.loads(response["body"].read())
        return {"live": True, "model": DEFAULT_MODEL_ID, "response": payload, **decision}
    except Exception as exc:  # no credentials, no network, etc. — stay honest
        return {"live": False, "fallback_reason": type(exc).__name__, **decision}
