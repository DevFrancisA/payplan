# Two sources of truth for service health:
#  - ALB metrics (what clients experienced, including requests that never reached a task)
#  - Application metrics the API writes as CloudWatch Embedded Metric Format log lines
#    (namespace "PayPlan": Latency, Requests, ServerErrors, ClientErrors, PaymentFailed ...)

resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alarm_actions = [aws_sns_topic.alarms.arn]
  alb_dims = {
    LoadBalancer = aws_lb.api.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx"
  alarm_description   = "API returned more than 5 server errors in 5 minutes"
  namespace           = "PayPlan"
  metric_name         = "ServerErrors"
  dimensions          = { Service = "payplan-api" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_latency_p95" {
  alarm_name          = "${local.name}-api-latency-p95"
  alarm_description   = "p95 API latency above ${var.latency_p95_threshold_ms} ms for 3 of 5 minutes"
  namespace           = "PayPlan"
  metric_name         = "Latency"
  dimensions          = { Service = "payplan-api" }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = var.latency_p95_threshold_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name}-alb-target-5xx"
  alarm_description   = "Load balancer saw 5xx responses from API targets"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = local.alb_dims
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  alarm_name          = "${local.name}-alb-unhealthy-hosts"
  alarm_description   = "At least one API task is failing health checks"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = local.alb_dims
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name}-rds-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = local.alarm_actions
}

# Unhandled exceptions are logged as JSON with level ERROR; count them as a metric too.
resource "aws_cloudwatch_log_metric_filter" "unhandled_errors" {
  name           = "${local.name}-unhandled-errors"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.level = \"ERROR\" }"

  metric_transformation {
    name          = "UnhandledErrors"
    namespace     = "PayPlan"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_dashboard" "api" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "API latency (ms)"
          region = var.region
          stat   = "p95"
          period = 60
          metrics = [
            ["PayPlan", "Latency", "Service", "payplan-api", { stat = "p50", label = "p50" }],
            ["...", { stat = "p95", label = "p95" }],
            ["...", { stat = "p99", label = "p99" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Requests and errors"
          region = var.region
          stat   = "Sum"
          period = 60
          metrics = [
            ["PayPlan", "Requests", "Service", "payplan-api"],
            [".", "ServerErrors", ".", "."],
            [".", "ClientErrors", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Payments"
          region = var.region
          stat   = "Sum"
          period = 300
          metrics = [
            ["PayPlan", "PaymentSucceeded", "Service", "payplan-api"],
            [".", "PaymentFailed", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "ECS and RDS CPU (%)"
          region = var.region
          stat   = "Average"
          period = 60
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.api.name],
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.main.identifier],
          ]
        }
      },
    ]
  })
}
