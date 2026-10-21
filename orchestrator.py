"""
BedrockOps operator orchestration (v2).

One submitted request probes Bedrock + DynamoDB + Lambda in sequence,
combines the results, routes, and writes ONE audit record of the
whole run. Gated requests (see bedrock_agent.GATED_ACTIONS) never
execute on submit: they create a PENDING proposal — no probes, no
model call — and only run after an operator approves in the console.
Denials are audited and execute nothing.

Honesty rules mirror the rest of the codebase: probe results carry
their mode (live / stub / live_failed), route results carry live
true/false, and the audit record's persisted flag is whatever the
ledger actually did (DynamoDB write or memory fallback).
"""
import hashlib
import threading
import time
import uuid

import bedrock_agent

PROBE_ORDER = ("bedrock", "dynamodb", "lambda")


class Orchestrator:
    """Two-step approval + multi-service orchestration over a ledger."""

    def __init__(self, ledger, probe_fn):
        self.ledger = ledger
        self.probe_fn = probe_fn
        self.proposals = {}
        self._lock = threading.Lock()

    # -- submissions ---------------------------------------------------

    def submit(self, prompt: str) -> dict:
        """Route a request. Gated -> PENDING proposal, nothing executes."""
        decision = bedrock_agent.route_request(prompt)
        if decision["action"] == "requires_approval":
            proposal = {
                "id": uuid.uuid4().hex[:12],
                "prompt": prompt,
                "route": decision,
                "status": "PENDING",
                "created_at": time.time(),
                "result": None,
            }
            with self._lock:
                self.proposals[proposal["id"]] = proposal
            self.ledger.record_event(
                "proposal_created",
                {
                    "proposal_id": proposal["id"],
                    "prompt": prompt,
                    "route_action": decision["action"],
                },
            )
            return {
                "status": "pending",
                "proposal": self._public(proposal),
                "route": decision,
            }
        run = self._run(prompt, decision, approved=False)
        return {"status": "executed", "run": run, "route": decision}

    def approve(self, proposal_id: str) -> dict:
        """Execute a PENDING proposal (probes + route + one audit record)."""
        proposal = self._get_pending(proposal_id)
        decision = bedrock_agent.route_request(proposal["prompt"])
        run = self._run(
            proposal["prompt"], decision, approved=True, proposal_id=proposal_id
        )
        with self._lock:
            proposal["status"] = "EXECUTED"
            proposal["result"] = run
        return {
            "status": "executed",
            "proposal": self._public(proposal),
            "run": run,
        }

    def deny(self, proposal_id: str) -> dict:
        """Deny a PENDING proposal: audited, nothing executes."""
        proposal = self._get_pending(proposal_id)
        with self._lock:
            proposal["status"] = "DENIED"
        digest = self.ledger.record_event(
            "proposal_denied",
            {"proposal_id": proposal_id, "prompt": proposal["prompt"]},
        )
        return {
            "status": "denied",
            "proposal": self._public(proposal),
            "audit_sha256": digest,
        }

    def list_proposals(self) -> list:
        with self._lock:
            props = [self._public(p) for p in self.proposals.values()]
        return sorted(props, key=lambda p: p["created_at"], reverse=True)

    # -- internals -------------------------------------------------------

    def _get_pending(self, proposal_id: str) -> dict:
        with self._lock:
            proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown proposal: {proposal_id}")
        if proposal["status"] != "PENDING":
            raise ValueError(
                f"proposal {proposal_id} is {proposal['status']}, not PENDING"
            )
        return proposal

    def _run(self, prompt, decision, approved, proposal_id=None) -> dict:
        probes = {}
        for service in PROBE_ORDER:
            try:
                probes[service] = self.probe_fn(service)
            except Exception as exc:  # a probe failure is reported, not faked
                probes[service] = {
                    "status": "ERROR",
                    "mode": "error",
                    "service": service,
                    "error": type(exc).__name__,
                }

        if decision["action"] == "audit_ledger":
            route_result = {
                "action": "audit_ledger",
                "live": False,
                "payload_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            }
        elif approved:
            # Human approval already happened; run the approved path.
            route_result = bedrock_agent.execute_approved(prompt)
        else:
            route_result = bedrock_agent.invoke(prompt)

        audit_details = {
            "prompt": prompt,
            "route": decision,
            "approved": approved,
            "probes": {
                svc: {"status": p.get("status"), "mode": p.get("mode")}
                for svc, p in probes.items()
            },
            "route_live": bool(route_result.get("live")),
        }
        if proposal_id:
            audit_details["proposal_id"] = proposal_id
        digest = self.ledger.record_event("orchestration_run", audit_details)
        entry = self.ledger.entries[-1] if self.ledger.entries else {}

        any_live = bool(route_result.get("live")) or any(
            p.get("mode") == "live" for p in probes.values()
        )
        return {
            "prompt": prompt,
            "route": decision,
            "approved": approved,
            "probes": probes,
            "result": route_result,
            "mode": "live" if any_live else "stub",
            "audit": {
                "sha256": digest,
                "persisted": bool(entry.get("persisted")),
                "store": "dynamodb" if entry.get("persisted") else "memory",
            },
            "timestamp": time.time(),
        }

    @staticmethod
    def _public(proposal: dict) -> dict:
        return {
            k: proposal[k]
            for k in ("id", "prompt", "route", "status", "created_at", "result")
        }
