output "audit_ledger_table_name" {
  description = "Name of the DynamoDB audit ledger table"
  value       = aws_dynamodb_table.audit_ledger.name
}

output "audit_ledger_table_arn" {
  description = "ARN of the DynamoDB audit ledger table"
  value       = aws_dynamodb_table.audit_ledger.arn
}

output "bedrockops_app_policy_arn" {
  description = "ARN of the least-privilege IAM policy for the BedrockOps server (attach to its host/Lambda/execution role)"
  value       = aws_iam_policy.bedrockops_app.arn
}
