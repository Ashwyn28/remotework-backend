output "site_url" {
  value = "https://${var.domain_name}"
}

output "site_bucket" {
  value = aws_s3_bucket.site.id
}

output "data_bucket" {
  value = aws_s3_bucket.data.id
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "sync_function" {
  value = aws_lambda_function.sync.function_name
}

output "api_function" {
  value = aws_lambda_function.api.function_name
}
