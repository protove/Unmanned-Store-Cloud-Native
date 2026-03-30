"""
Lambda Function: SQS to AWS Batch Trigger
SQS에 메시지가 들어오면 자동으로 AWS Batch Job을 제출
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Any

import boto3
from botocore.exceptions import ClientError

# 로깅 설정
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS 클라이언트
batch_client = boto3.client('batch')

# 환경 변수
JOB_QUEUE = os.environ.get('BATCH_JOB_QUEUE')
JOB_DEFINITION = os.environ.get('BATCH_JOB_DEFINITION')

# 재시도 가능한 일시적 에러 코드
TRANSIENT_ERROR_CODES = {
    'ThrottlingException', 'ServiceUnavailable',
    'TooManyRequestsException', 'InternalError',
}


def _is_transient_error(error: Exception) -> bool:
    """일시적 에러 여부 판별 (재시도 가능)"""
    if isinstance(error, ClientError):
        return error.response['Error']['Code'] in TRANSIENT_ERROR_CODES
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    return False


def _extract_video_id(body: dict, s3_key: str) -> str | None:
    """메시지 body 또는 S3 key에서 video_id 추출"""
    # 1) body에서 직접 추출
    try:
        if 'video' in body and 'id' in body['video']:
            return str(body['video']['id'])
    except (TypeError, KeyError):
        pass
    # 2) S3 key 패턴에서 추출 (예: uploads/36/video.mp4 → 36)
    parts = s3_key.split('/')
    if len(parts) >= 2:
        candidate = parts[-2]
        if candidate.isdigit():
            return candidate
    return None


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda 핸들러 - SQS 이벤트를 받아서 Batch Job 제출
    
    Args:
        event: SQS 이벤트
        context: Lambda 컨텍스트
    
    Returns:
        처리 결과
    """
    
    record_count = len(event.get('Records', []))
    logger.info(f"Received SQS event: record_count={record_count}")
    
    # 환경 변수 검증
    if not JOB_QUEUE or not JOB_DEFINITION:
        logger.error("Missing required environment variables")
        raise ValueError("BATCH_JOB_QUEUE and BATCH_JOB_DEFINITION must be set")
    
    successful_jobs = []
    failed_jobs = []
    
    # SQS 레코드 처리
    for record in event.get('Records', []):
        try:
            message_id = record['messageId']
            receipt_handle = record['receiptHandle']
            
            logger.info(f"Processing message: {message_id}")
            
            # 메시지 바디 파싱
            body = json.loads(record['body'])
            
            # S3 이벤트 정보 추출
            s3_records = body.get('Records', [])
            if not s3_records:
                logger.error(f"No S3 records in message: message_id={message_id}")
                failed_jobs.append({
                    'message_id': message_id,
                    'error': 'No S3 records in message body',
                    'transient': False,
                })
                continue
            
            s3_record = s3_records[0]
            bucket = s3_record['s3']['bucket']['name']
            key = s3_record['s3']['object']['key']
            
            # video_id 추출 (필수)
            video_id = _extract_video_id(body, key)
            if not video_id:
                logger.error(f"video_id 추출 실패: message_id={message_id}, s3_key={key}")
                failed_jobs.append({
                    'message_id': message_id,
                    'error': f'video_id extraction failed for key={key}',
                    'transient': False,
                })
                continue
            
            # Batch Job 제출
            job_name = f"video-process-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{message_id[:8]}"
            
            logger.info(
                f"Submitting Batch job: job_name={job_name}, "
                f"video_id={video_id}, s3=s3://{bucket}/{key}"
            )
            
            container_env = [
                {'name': 'S3_BUCKET', 'value': bucket},
                {'name': 'S3_KEY', 'value': key},
                {'name': 'MESSAGE_ID', 'value': message_id},
                {'name': 'VIDEO_ID', 'value': video_id},
            ]
            
            response = batch_client.submit_job(
                jobName=job_name,
                jobQueue=JOB_QUEUE,
                jobDefinition=JOB_DEFINITION,
                containerOverrides={
                    'environment': container_env
                },
                tags={
                    'Source': 'Lambda-SQS-Trigger',
                    'MessageId': message_id,
                    'S3Bucket': bucket
                }
            )
            
            job_id = response['jobId']
            
            logger.info(
                f"Batch job submitted: job_id={job_id}, "
                f"video_id={video_id}, message_id={message_id}"
            )
            
            successful_jobs.append({
                'message_id': message_id,
                'job_id': job_id,
                'job_name': job_name,
                'video_id': video_id,
                's3_bucket': bucket,
                's3_key': key,
            })
            
        except ClientError as e:
            transient = _is_transient_error(e)
            error_code = e.response['Error']['Code']
            logger.error(
                f"AWS error: message_id={record.get('messageId')}, "
                f"error_code={error_code}, transient={transient}"
            )
            failed_jobs.append({
                'message_id': record.get('messageId'),
                'error': str(e),
                'transient': transient,
            })

        except Exception as e:
            transient = _is_transient_error(e)
            logger.error(
                f"Unexpected error: message_id={record.get('messageId')}, "
                f"error_type={type(e).__name__}, transient={transient}",
                exc_info=True,
            )
            failed_jobs.append({
                'message_id': record.get('messageId'),
                'error': str(e),
                'transient': transient,
            })
    
    # 결과 요약
    result = {
        'total_messages': len(event.get('Records', [])),
        'successful_jobs': len(successful_jobs),
        'failed_jobs': len(failed_jobs),
        'jobs': successful_jobs,
        'failures': failed_jobs
    }
    
    logger.info(
        f"Processing complete: total={result['total_messages']}, "
        f"success={result['successful_jobs']}, failed={result['failed_jobs']}"
    )
    
    # 실패한 메시지만 SQS에 남겨서 재시도 (batchItemFailures)
    failed_message_ids = {f['message_id'] for f in failed_jobs}
    if failed_message_ids:
        logger.warning(
            f"Returning batchItemFailures: count={len(failed_message_ids)}, "
            f"message_ids={failed_message_ids}"
        )
        return {
            'batchItemFailures': [
                {'itemIdentifier': msg_id}
                for msg_id in failed_message_ids
            ]
        }
    
    return result
