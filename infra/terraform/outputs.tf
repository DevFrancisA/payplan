output "app_url" {
  description = "Public URL (frontend and /api/*)"
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

# The values below map 1:1 to GitHub repository variables used by the deploy workflow.

output "AWS_DEPLOY_ROLE_ARN" {
  value = aws_iam_role.github_deploy.arn
}

output "AWS_REGION" {
  value = var.region
}

output "ECR_REPOSITORY" {
  value = aws_ecr_repository.api.name
}

output "ECS_CLUSTER" {
  value = aws_ecs_cluster.main.name
}

output "ECS_SERVICE" {
  value = aws_ecs_service.api.name
}

output "ECS_TASK_FAMILY" {
  value = aws_ecs_task_definition.api.family
}

output "ECS_SUBNETS" {
  value = join(",", aws_subnet.private[*].id)
}

output "ECS_SECURITY_GROUP" {
  value = aws_security_group.api.id
}

output "WEB_BUCKET" {
  value = aws_s3_bucket.web.bucket
}

output "CLOUDFRONT_DISTRIBUTION_ID" {
  value = aws_cloudfront_distribution.web.id
}
