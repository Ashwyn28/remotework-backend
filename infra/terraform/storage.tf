data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
}

# --- The site's static files (deploy-site.sh uploads them) ---------------------------

resource "aws_s3_bucket" "site" {
  bucket = "${var.project}-site-${local.account_id}"
}

# --- Data written by the sync: data/board.json and static/logos/* --------------------

resource "aws_s3_bucket" "data" {
  bucket = "${var.project}-data-${local.account_id}"
}

# keep yesterday's board.json for a month, so a bad sync can be rolled back
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
  depends_on = [aws_s3_bucket_versioning.data]
}

# both buckets are private: only CloudFront can read them
resource "aws_s3_bucket_public_access_block" "private" {
  for_each                = { site = aws_s3_bucket.site.id, data = aws_s3_bucket.data.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "private" {
  for_each = { site = aws_s3_bucket.site.id, data = aws_s3_bucket.data.id }
  bucket   = each.value
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "private" {
  for_each = { site = aws_s3_bucket.site.id, data = aws_s3_bucket.data.id }
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "cloudfront_reads" {
  for_each = { site = aws_s3_bucket.site.arn, data = aws_s3_bucket.data.arn }

  statement {
    sid       = "CloudFrontReadsObjects"
    actions   = ["s3:GetObject"]
    resources = ["${each.value}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }

  statement {
    sid       = "HttpsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value, "${each.value}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket     = aws_s3_bucket.site.id
  policy     = data.aws_iam_policy_document.cloudfront_reads["site"].json
  depends_on = [aws_s3_bucket_public_access_block.private]
}

resource "aws_s3_bucket_policy" "data" {
  bucket     = aws_s3_bucket.data.id
  policy     = data.aws_iam_policy_document.cloudfront_reads["data"].json
  depends_on = [aws_s3_bucket_public_access_block.private]
}

# --- Accounts: answers and saved roles ------------------------------------------------

resource "aws_dynamodb_table" "users" {
  name                        = "${var.project}-users"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "sub"
  deletion_protection_enabled = true

  attribute {
    name = "sub"
    type = "S"
  }

  # restore to any second in the last 35 days
  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}
