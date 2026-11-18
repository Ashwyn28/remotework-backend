data "aws_route53_zone" "main" {
  name = var.hosted_zone_name
}

# --- Certificate (must be in us-east-1 for CloudFront) ---------------------------------

resource "aws_acm_certificate" "site" {
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.site.domain_validation_options : option.domain_name => option
  }
  zone_id = data.aws_route53_zone.main.zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "site" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

# --- CloudFront ------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${var.project}-s3"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# app routes like /company/monzo have no file; serve the app shell and let it route
resource "aws_cloudfront_function" "spa" {
  name    = "${var.project}-spa"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      var last = request.uri.split('/').pop();
      if (last.indexOf('.') === -1) {
        request.uri = '/index.html';
      }
      return request;
    }
  JS
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${var.project}-security-headers"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      preload                    = false
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    content_security_policy {
      override = true
      # 'unsafe-inline' scripts: SvelteKit's app shell starts the app from an inline script.
      # Google's sign-in button needs its script, frame, styles and connections allowed.
      content_security_policy = join("; ", [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/client",
        "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src 'self' https://accounts.google.com/gsi/",
        "frame-src https://accounts.google.com/gsi/",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
      ])
    }
  }
}

locals {
  site_origin = "site"
  data_origin = "data"
  api_origin  = "api"
  # https://<id>.lambda-url.<region>.on.aws/ -> <id>.lambda-url.<region>.on.aws
  api_domain = replace(replace(aws_lambda_function_url.api.function_url, "https://", ""), "/", "")
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  comment             = "${var.project}: site, board data and accounts API"
  aliases             = [var.domain_name]
  default_root_object = "index.html"
  # Europe and North America edge locations only: the cheapest price class
  price_class = "PriceClass_100"

  origin {
    origin_id                = local.site_origin
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  origin {
    origin_id                = local.data_origin
    domain_name              = aws_s3_bucket.data.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  origin {
    origin_id   = local.api_origin
    domain_name = local.api_domain
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_secret.result
    }
  }

  # the app shell and its assets
  default_cache_behavior {
    target_origin_id           = local.site_origin
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa.arn
    }
  }

  # board.json (cached for the five minutes its Cache-Control header allows)
  ordered_cache_behavior {
    path_pattern               = "/data/*"
    target_origin_id           = local.data_origin
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  # company logos
  ordered_cache_behavior {
    path_pattern               = "/static/*"
    target_origin_id           = local.data_origin
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  # accounts API: never cached; cookies, headers and body pass through
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = local.api_origin
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_route53_record" "site" {
  for_each = toset(["A", "AAAA"])
  zone_id  = data.aws_route53_zone.main.zone_id
  name     = var.domain_name
  type     = each.value
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
