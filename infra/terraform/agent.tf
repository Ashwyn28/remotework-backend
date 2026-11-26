# --- Job-search chat agent: relays /agent page turns to Claude ------------------------------
#
# Its own function and role, so only this role can get Anthropic access, it has its own logs,
# and its timeout fits a model call. Spending is capped by daily counters in DynamoDB (per viewer
# IP and for the whole site), checked before every call.
#
# No API key: the role asks AWS STS for a signed token (outbound web identity federation, enabled
# once per account) and Anthropic's federation rule accepts tokens whose subject is this role.

resource "aws_dynamodb_table" "agent_quota" {
  name         = "${var.project}-agent-quota"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "k"

  attribute {
    name = "k"
    type = "S"
  }

  # counters delete themselves two days after their day ends
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_iam_role" "agent" {
  name               = "${var.project}-agent"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "agent" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda["agent"].arn}:*"]
  }
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.agent_quota.arn]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.origin_secret.arn]
  }
  # tokens that prove this role's identity to Anthropic, and nothing else
  statement {
    actions   = ["sts:GetWebIdentityToken"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "agent" {
  role   = aws_iam_role.agent.id
  policy = data.aws_iam_policy_document.agent.json
}

resource "aws_lambda_function" "agent" {
  function_name    = "${var.project}-agent"
  role             = aws_iam_role.agent.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "jobagent.lambda_handler.handler"
  filename         = var.agent_package
  source_code_hash = filebase64sha256(var.agent_package)
  memory_size      = 512
  # one model call per request; the client gives up after 25s, CloudFront after 30s
  timeout = 29

  environment {
    variables = {
      SITE_ORIGIN = "https://${var.domain_name}"
      QUOTA_TABLE = aws_dynamodb_table.agent_quota.name
      # identifiers from the Claude Console's workload identity setup; none of them is secret
      ANTHROPIC_ORGANIZATION_ID    = var.anthropic_organization_id
      ANTHROPIC_FEDERATION_RULE_ID = var.anthropic_federation_rule_id
      ANTHROPIC_SERVICE_ACCOUNT_ID = var.anthropic_service_account_id
      ANTHROPIC_WORKSPACE_ID       = var.anthropic_workspace_id
      ORIGIN_SECRET_PARAM          = aws_ssm_parameter.origin_secret.name
      LIMIT_PER_IP_PER_DAY         = tostring(var.agent_limit_per_ip_per_day)
      LIMIT_SITE_PER_DAY           = tostring(var.agent_limit_site_per_day)
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.agent]
}

# Public URL, like the accounts API: the function refuses anything without CloudFront's header.
resource "aws_lambda_function_url" "agent" {
  function_name      = aws_lambda_function.agent.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "agent_url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.agent.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "agent_url_invoke" {
  statement_id             = "AllowInvokeThroughFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.agent.function_name
  principal                = "*"
  invoked_via_function_url = true
}
