import boto3
from app.config import settings

sqs = boto3.client(
    "sqs",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION
)

sqs.purge_queue(
    QueueUrl=settings.SQS_QUEUE_URL
)

print("SQS queue purged successfully")