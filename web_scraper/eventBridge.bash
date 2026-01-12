# Create EventBridge rule for daily execution
aws events put-rule \
  --name "daily-scraper-schedule" \
  --schedule-expression "cron(0 19 * * ? *)" \
  --description "Run scraper daily at 7 PM UTC (11 AM PST)" \
  --region us-west-2

# Add ECS task as target
aws events put-targets \
  --rule "daily-scraper-schedule" \
  --targets "Id"="1","Arn"="arn:aws:ecs:us-west-2:489702352871:cluster/ScheduledScraperCluster","RoleArn"="arn:aws:iam::489702352871:role/ecsTaskExecutionRole","EcsParameters"="{\"TaskDefinitionArn\":\"arn:aws:ecs:us-west-2:489702352871:task-definition/ScraperTask:5\",\"LaunchType\":\"FARGATE\",\"NetworkConfiguration\":{\"awsvpcConfiguration\":{\"Subnets\":[\"subnet-008274c59189ce8b2\"],\"SecurityGroups\":[\"sg-00aa197cbb0c71799\"],\"AssignPublicIp\":\"ENABLED\"}}}" \
  --region us-west-2