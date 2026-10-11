resource "aws_ecr_repository" "api" {
  name                 = "payplan-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 30 most recent images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}-api"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

locals {
  healthcheck_cmd = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name = "api"
    # CI registers new revisions with each commit's image; this is only the bootstrap value.
    image        = "${aws_ecr_repository.api.repository_url}:bootstrap"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "PAYPLAN_ENVIRONMENT", value = var.environment },
      { name = "PAYPLAN_DB_HOST", value = aws_db_instance.main.address },
      { name = "PAYPLAN_DB_NAME", value = aws_db_instance.main.db_name },
      { name = "PAYPLAN_DB_USER", value = aws_db_instance.main.username },
      { name = "PAYPLAN_DB_SSLMODE", value = "require" },
      { name = "PAYPLAN_EMF_ENABLED", value = "true" },
      { name = "PAYPLAN_METRICS_NAMESPACE", value = "PayPlan" },
      { name = "PAYPLAN_SERVICE_NAME", value = "payplan-api" },
      { name = "PAYPLAN_CORS_ORIGINS", value = jsonencode(["https://${aws_cloudfront_distribution.web.domain_name}"]) },
    ]
    secrets = [{
      name      = "PAYPLAN_DB_PASSWORD"
      valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
    healthCheck = {
      command     = ["CMD", "python", "-c", local.healthcheck_cmd]
      interval    = 15
      timeout     = 3
      retries     = 3
      startPeriod = 10
    }
  }])
}

resource "aws_ecs_service" "api" {
  name                              = "${local.name}-api"
  cluster                           = aws_ecs_cluster.main.id
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.api_desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 30

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    # Deployments are driven by GitHub Actions, not Terraform.
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront]
}

resource "aws_appautoscaling_target" "api" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.api_desired_count
  max_capacity       = var.api_max_count
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.name}-api-cpu"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  policy_type        = "TargetTrackingScaling"

  target_tracking_scaling_policy_configuration {
    target_value = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
