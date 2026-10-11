variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "api_max_count" {
  type    = number
  default = 6
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "github_repository" {
  description = "owner/repo allowed to deploy through GitHub Actions OIDC"
  type        = string
}

variable "create_github_oidc_provider" {
  description = "Set false if the account already has the token.actions.githubusercontent.com provider"
  type        = bool
  default     = true
}

variable "alarm_email" {
  description = "Optional address subscribed to alarm notifications"
  type        = string
  default     = ""
}

variable "latency_p95_threshold_ms" {
  type    = number
  default = 500
}
