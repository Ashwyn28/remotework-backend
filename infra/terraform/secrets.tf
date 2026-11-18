# Generated once and kept in SSM Parameter Store (standard tier is free). They also sit in the
# Terraform state, so keep that state private.

resource "random_password" "session_secret" {
  length  = 64
  special = false
}

resource "random_password" "origin_secret" {
  length  = 48
  special = false
}

# signs session cookies
resource "aws_ssm_parameter" "session_secret" {
  name  = "/${var.project}/session-secret"
  type  = "SecureString"
  value = random_password.session_secret.result
}

# CloudFront sends this header to the API; requests without it are refused
resource "aws_ssm_parameter" "origin_secret" {
  name  = "/${var.project}/origin-secret"
  type  = "SecureString"
  value = random_password.origin_secret.result
}
