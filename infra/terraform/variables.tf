variable "project" {
  description = "Prefix for every resource name."
  type        = string
  default     = "orbbits-job"
}

variable "aws_region" {
  description = "Region for the buckets, Lambdas and table. London keeps data close to UK users."
  type        = string
  default     = "eu-west-2"
}

variable "hosted_zone_name" {
  description = "Existing Route 53 hosted zone."
  type        = string
  default     = "orbbits.io"
}

variable "domain_name" {
  description = "Address the site is served on."
  type        = string
  default     = "jobs.orbbits.io"
}

variable "google_client_id" {
  description = "OAuth client for Sign in with Google. The site's https origin must be listed under its Authorised JavaScript origins."
  type        = string
  default     = "601837645469-i46geu02ca7rthamniuehgkp5ithjbl9.apps.googleusercontent.com"
}

variable "sync_schedule" {
  description = "When the listings sync runs (EventBridge Scheduler expression, in sync_timezone)."
  type        = string
  default     = "cron(0 6 * * ? *)"
}

variable "sync_timezone" {
  type    = string
  default = "Europe/London"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "sync_package" {
  description = "Zip built by infra/package.py."
  type        = string
  default     = "../../.local/build/sync.zip"
}

variable "api_package" {
  description = "Zip built by infra/package.py."
  type        = string
  default     = "../../.local/build/api.zip"
}
