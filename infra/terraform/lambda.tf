data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = toset(["sync", "api", "agent"])
  name              = "/aws/lambda/${var.project}-${each.key}"
  retention_in_days = var.log_retention_days
}

# --- Daily sync: careers sites -> data bucket ------------------------------------------

resource "aws_iam_role" "sync" {
  name               = "${var.project}-sync"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "sync" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda["sync"].arn}:*"]
  }
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/data/*", "${aws_s3_bucket.data.arn}/static/logos/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}

resource "aws_iam_role_policy" "sync" {
  role   = aws_iam_role.sync.id
  policy = data.aws_iam_policy_document.sync.json
}

resource "aws_lambda_function" "sync" {
  function_name    = "${var.project}-sync"
  role             = aws_iam_role.sync.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "jobfeed.sync_handler.handler"
  filename         = var.sync_package
  source_code_hash = filebase64sha256(var.sync_package)
  memory_size      = 512
  # a few hundred careers sites, read politely in parallel; Lambda's ceiling is 15 minutes
  timeout = 900

  environment {
    variables = {
      DATA_BUCKET = aws_s3_bucket.data.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.sync]
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.sync.arn
    }]
  })
}

resource "aws_scheduler_schedule" "sync" {
  name                         = "${var.project}-daily-sync"
  schedule_expression          = var.sync_schedule
  schedule_expression_timezone = var.sync_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.sync.arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

# --- Accounts API, reached only through CloudFront at /api -----------------------------

resource "aws_iam_role" "api" {
  name               = "${var.project}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda["api"].arn}:*"]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.users.arn]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.session_secret.arn, aws_ssm_parameter.origin_secret.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.project}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "jobapi.lambda_handler.handler"
  filename         = var.api_package
  source_code_hash = filebase64sha256(var.api_package)
  memory_size      = 256
  timeout          = 10

  environment {
    variables = {
      GOOGLE_CLIENT_ID     = var.google_client_id
      SITE_ORIGIN          = "https://${var.domain_name}"
      USERS_TABLE          = aws_dynamodb_table.users.name
      SESSION_SECRET_PARAM = aws_ssm_parameter.session_secret.name
      ORIGIN_SECRET_PARAM  = aws_ssm_parameter.origin_secret.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.api]
}

# A function URL is free (unlike API Gateway). It is public by necessity, so the function
# itself refuses any request without CloudFront's secret header.
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "api_url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# Function URLs also need lambda:InvokeFunction. Scoped to calls made through the URL, so it
# does not let anyone invoke the function directly through the Lambda API.
resource "aws_lambda_permission" "api_url_invoke" {
  statement_id             = "AllowInvokeThroughFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.api.function_name
  principal                = "*"
  invoked_via_function_url = true
}
