# CloudWatch Log Group Subscription Filter Management
This project outlines one potential solution to automate portions of managing subscription filters for AWS CloudWatch Log Groups. The solution uses an AWS Lambda function to 1) list all log groups in an account, 2) check for existing subscription filters, and 3) create filters where none exist, with the intent to forward logs to Amazon Kinesis Firehose
### Solution Overview
The solution consists of:
* Python-based Lambda function
* IAM roles and permissions
* Configurable parameters
* Optional email notifications for operation reports
* AWS CLI scripts to implement the project

### Prerequisites
* AWS account with permissions to create Lambda functions and IAM roles
* An existing Kinesis Firehose delivery stream to receive the logs
* Familiarity with AWS services (Lambda, CloudWatch Logs, Firehose, IAM)

## IAM Setup
#### 1. Create the CloudWatch-to-Firehose Role
This role allows CloudWatch Logs to send data to your Firehose delivery stream
```
aws iam create-role \
  --role-name CloudWatchLogsToFirehoseRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "logs.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}'
```
##### Attach permissions policy
```
aws iam put-role-policy \
  --role-name CloudWatchLogsToFirehoseRole \
  --policy-name FirehoseAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "firehose:PutRecord",
                "firehose:PutRecordBatch"
            ],
            "Resource": [
                "arn:aws:firehose:*:ACCOUNT_ID:deliverystream/*"
            ]
        }
    ]
}'
```
**Note:** Replace ```ACCOUNT_ID``` with your AWS account ID

#### 2. Create a Role for the Lambda Function
```
aws iam create-role \
  --role-name LogGroupSubscriptionFiltersRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}'
```
## Attach required permissions
```
aws iam put-role-policy \
  --role-name LogGroupSubscriptionFiltersRole \
  --policy-name LambdaPermissions \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:DescribeLogGroups",
                "logs:DescribeSubscriptionFilters",
                "logs:PutSubscriptionFilter"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "sns:CreateTopic",
                "sns:Subscribe",
                "sns:Publish",
                "sns:ListTopics"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": "arn:aws:iam::ACCOUNT_ID:role/CloudWatchLogsToFirehoseRole"
        }
    ]
}'
```
**Note:** Replace ```ACCOUNT_ID``` with your AWS account ID

## Deployment
### 1. Package the Lambda Function
Find the ```lambda_function.py``` file in this repo
```zip function.zip lambda_function.py```

### 2. Create the Lambda Function
```
aws lambda create-function \
  --function-name LogGroupSubscriptionFilters \
  --runtime python3.12 \
  --timeout 300 \
  --memory-size 256 \
  --role arn:aws:iam::ACCOUNT_ID:role/LogGroupSubscriptionFiltersRole \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --environment "Variables={FIREHOSE_STREAM_NAME=YOUR_FIREHOSE_NAME,IAM_ROLE_NAME=CloudWatchLogsToFirehoseRole,EMAIL_NOTIFICATION=true,NOTIFICATION_EMAIL=YOUR_EMAIL@example.com,DRY_RUN=true}"
```
**Notes:**
* Replace ```ACCOUNT_ID``` with your AWS account ID
* Replace ```YOUR_FIREHOSE_NAME``` with your Firehose delivery stream name
* Replace ```YOUR_EMAIL@example.com``` with your notification email address
* The ```DRY_RUN=true``` flag prevents the function from making changes during testing

### 3. Test the Lambda Function
```
aws lambda invoke \
  --function-name LogGroupSubscriptionFilters \
  --payload '{"test":"true"}' \
  response.json
```
View the response
```cat response.json```

### 4. Check the Logs
```
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name "/aws/lambda/LogGroupSubscriptionFilters" \
  --order-by LastEventTime \
  --descending \
  --limit 1 \
  --query 'logStreams[0].logStreamName' \
  --output text)
```
Get the logs
```
aws logs get-log-events \
  --log-group-name "/aws/lambda/LogGroupSubscriptionFilters" \
  --log-stream-name "$LOG_STREAM"
```
### 5. Set Up Scheduled Execution
After testing and confirming the function works as expected, set up a scheduled execution:
```
aws events put-rule \
  --name DailyLogGroupSubscriptionCheck \
  --schedule-expression "rate(1 day)"
```
Add permission for EventBridge to invoke Lambda
```
aws lambda add-permission \
  --function-name LogGroupSubscriptionFilters \
  --statement-id EventBridgeInvoke \
  --action 'lambda:InvokeFunction' \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT_ID:rule/DailyLogGroupSubscriptionCheck
```  
Connect the rule to the Lambda function
```
aws events put-targets \
  --rule DailyLogGroupSubscriptionCheck \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT_ID:function:LogGroupSubscriptionFilters"
```
**Note:** Replace ```REGION``` and ```ACCOUNT_ID``` with your AWS region and account ID

### 6. Moving to Production
When you're ready to move to production, update the Lambda environment variables to turn off dry run mode:
```
aws lambda update-function-configuration \
  --function-name LogGroupSubscriptionFilters \
  --environment "Variables={FIREHOSE_STREAM_NAME=YOUR_FIREHOSE_NAME,IAM_ROLE_NAME=CloudWatchLogsToFirehoseRole,EMAIL_NOTIFICATION=true,NOTIFICATION_EMAIL=YOUR_EMAIL@example.com,DRY_RUN=false}"
```
Confirm you're getting email notifications with successful updates