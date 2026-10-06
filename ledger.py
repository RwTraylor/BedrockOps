"""
BedrockOps audit ledger.

Always records in memory (so offline runs and tests work). When a
DynamoDB table is configured, each event is ALSO persisted there:

  Configure with either:
    - env AUDIT_TABLE_NAME (or BEDROCKOPS_AUDIT_TABLE), or
    - AuditLedger(table_name="...", session_id="...", dynamodb_client=...)

Table schema (see terraform/main.tf):
  SessionId (S, partition key), Timestamp (N, sort key),
  Action (S), Details (S, JSON), Sha256 (S)

Persistence failures never raise out of record_event: the record is
kept in memory with persisted=False and persist_error set to the
exception type name. Nothing here fakes a successful write.
"""
import hashlib
import json
import os
import time


class AuditLedger:
    def __init__(self, table_name=None, session_id="bedrockops-local", dynamodb_client=None):
        self.entries = []
        self.session_id = session_id
        self.table_name = (
            table_name
            or os.environ.get("AUDIT_TABLE_NAME")
            or os.environ.get("BEDROCKOPS_AUDIT_TABLE")
        )
        self._client = dynamodb_client

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy: offline runs never pay this import cost/path

            self._client = boto3.client(
                "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")
            )
        return self._client

    def _persist(self, record) -> None:
        if not self.table_name:
            record["persisted"] = False
            record["persist_error"] = "not_configured"
            return
        try:
            self._get_client().put_item(
                TableName=self.table_name,
                Item={
                    "SessionId": {"S": self.session_id},
                    "Timestamp": {"N": str(record["timestamp"])},
                    "Action": {"S": record["action"]},
                    "Details": {"S": json.dumps(record["details"], sort_keys=True, default=str)},
                    "Sha256": {"S": record["sha256"]},
                },
            )
            record["persisted"] = True
        except Exception as exc:  # no creds, no table, no network — stay honest
            record["persisted"] = False
            record["persist_error"] = type(exc).__name__

    def record_event(self, action: str, details: dict) -> str:
        record = {
            "timestamp": time.time(),
            "action": action,
            "details": details,
        }
        raw = f"{record['timestamp']}:{action}:{str(details)}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        record["sha256"] = digest
        self._persist(record)
        self.entries.append(record)
        return digest
