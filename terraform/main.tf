terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

resource "aws_dynamodb_table" "audit_ledger" {
  name         = "bedrockops-audit-ledger"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "SessionId"
  range_key    = "Timestamp"

  attribute {
    name = "SessionId"
    type = "S"
  }

  attribute {
    name = "Timestamp"
    type = "N"
  }

  tags = {
    Environment = "hackathon"
    Project     = "BedrockOps"
  }
}

# Least-privilege policy for the self-hosted BedrockOps server.
# Matches exactly what the code calls:
#   bedrock_agent.probe_service / invoke, ledger._persist.
# No create/delete permissions anywhere; probes are read-only and the
# only write is PutItem to this one audit table.
resource "aws_iam_policy" "bedrockops_app" {
  name = "bedrockops-app-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "BedrockInvokeAndList"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:ListFoundationModels"]
        Resource = "*"
      },
      {
        Sid      = "ReadOnlyProbes"
        Effect   = "Allow"
        Action   = ["lambda:ListFunctions", "dynamodb:ListTables"]
        Resource = "*"
      },
      {
        Sid      = "AuditLedgerWriteOnly"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.audit_ledger.arn
      }
    ]
  })

  tags = {
    Environment = "hackathon"
    Project     = "BedrockOps"
  }
}
