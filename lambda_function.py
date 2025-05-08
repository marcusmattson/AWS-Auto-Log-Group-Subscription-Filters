import boto3
import os
import json
from datetime import datetime

def lambda_handler(event, context):
    # Auto-detect the current account ID from the Lambda context
    account_id = context.invoked_function_arn.split(":")[4]
    region = os.environ.get('AWS_REGION')
    
    # Configuration from environment variables (for easy parameterization)
    firehose_stream_name = os.environ.get('FIREHOSE_STREAM_NAME')
    filter_name = os.environ.get('FILTER_NAME', 'CloudWatchToFirehose')
    filter_pattern = os.environ.get('FILTER_PATTERN', '')
    email_notification = os.environ.get('EMAIL_NOTIFICATION', 'true').lower() == 'true'
    notification_email = os.environ.get('NOTIFICATION_EMAIL')
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    
    # Construct the Firehose ARN
    firehose_arn = f"arn:aws:firehose:{region}:{account_id}:deliverystream/{firehose_stream_name}"
    
    # Construct the Role ARN - this is the role CloudWatch Logs will use
    role_name = os.environ.get('IAM_ROLE_NAME', 'CloudWatchLogsToFirehoseRole')
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    
    logs_client = boto3.client('logs')
    sns_client = boto3.client('sns')
    
    # Set retention policy on this Lambda's log group
    function_name = context.function_name
    log_group_name = f"/aws/lambda/{function_name}"
    try:
        logs_client.put_retention_policy(
            logGroupName=log_group_name,
            retentionInDays=30
        )
    except Exception as e:
        print(f"Could not set retention policy: {str(e)}")
    
    # Get all log groups
    paginator = logs_client.get_paginator('describe_log_groups')
    log_groups = []
    
    for page in paginator.paginate():
        for log_group in page.get('logGroups', []):
            log_group_name = log_group['logGroupName']
            log_groups.append(log_group_name)
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'account_id': account_id,
        'region': region,
        'firehose_stream': firehose_stream_name,
        'dry_run': dry_run,
        'total_log_groups': len(log_groups),
        'existing_filters': 0,
        'new_filters_added': 0,
        'would_update': 0,
        'failed_updates': 0,
        'details': {
            'log_groups_with_filters': [],
            'log_groups_updated': [],
            'log_groups_would_update': [],
            'log_groups_failed': []
        }
    }
    
    # Process each log group
    for log_group_name in log_groups:
        try:
            # Check if subscription filter exists
            response = logs_client.describe_subscription_filters(
                logGroupName=log_group_name
            )
            
            if not response.get('subscriptionFilters'):
                # Create subscription filter
                try:
                    if not dry_run:
                        logs_client.put_subscription_filter(
                            logGroupName=log_group_name,
                            filterName=filter_name,
                            filterPattern=filter_pattern,
                            destinationArn=firehose_arn,
                            roleArn=role_arn
                        )
                        results['new_filters_added'] += 1
                        results['details']['log_groups_updated'].append(log_group_name)
                    else:
                        results['would_update'] += 1
                        results['details']['log_groups_would_update'].append(log_group_name)
                except Exception as e:
                    results['failed_updates'] += 1
                    results['details']['log_groups_failed'].append({
                        'log_group': log_group_name,
                        'error': str(e)
                    })
            else:
                results['existing_filters'] += 1
                results['details']['log_groups_with_filters'].append(log_group_name)
        except Exception as e:
            results['failed_updates'] += 1
            results['details']['log_groups_failed'].append({
                'log_group': log_group_name,
                'error': str(e)
            })
    
    # Send email notification if enabled
    if email_notification and notification_email:
        try:
            # Create a summary message
            summary = f"""
CloudWatch Log Subscription Filter Report

Account: {account_id}
Region: {region}
Timestamp: {results['timestamp']}
Firehose: {firehose_stream_name}
Dry Run Mode: {dry_run}

Summary:
- Total Log Groups: {results['total_log_groups']}
- Log Groups with Existing Filters: {results['existing_filters']}
- Log Groups Successfully Updated: {results['new_filters_added']}
- Log Groups That Would Be Updated (Dry Run): {results['would_update']}
- Log Groups Failed to Update: {results['failed_updates']}

See Lambda CloudWatch logs for full details.
            """
            
            # Create SNS topic if it doesn't exist or use existing
            topic_name = f"CloudWatchFilterMonitor-{account_id}"
            
            # Check if topic exists, create if not
            topics = sns_client.list_topics()
            topic_arn = None
            
            for topic in topics.get('Topics', []):
                if topic_name in topic['TopicArn']:
                    topic_arn = topic['TopicArn']
                    break
                    
            if not topic_arn:
                response = sns_client.create_topic(Name=topic_name)
                topic_arn = response['TopicArn']
                # Subscribe the email
                sns_client.subscribe(
                    TopicArn=topic_arn,
                    Protocol='email',
                    Endpoint=notification_email
                )
            
            # Publish the notification
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"CloudWatch Log Filter Report - {account_id} - {results['new_filters_added']} Updates",
                Message=summary
            )
            
            results['notification_sent'] = True
            
        except Exception as e:
            results['notification_error'] = str(e)
    
    # Print results to CloudWatch logs
    print(json.dumps(results, indent=2))
    return results