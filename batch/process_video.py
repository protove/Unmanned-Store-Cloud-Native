#!/usr/bin/env python3
"""
AWS Batch Video Processor
SQS 메시지를 폴링하고 FastAPI 분석 서비스를 호출하여 비디오 분석 처리
"""

import os
import json
import time
import logging
import sys
from typing import Dict, Any, Optional
from datetime import datetime

import boto3
import requests
from botocore.exceptions import ClientError

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class VideoProcessorError(Exception):
    """비디오 처리 중 발생하는 커스텀 예외"""
    pass


class VideoProcessor:
    """비디오 분석 처리를 담당하는 메인 클래스"""
    
    def __init__(self):
        """환경 변수에서 설정 로드"""
        self.sqs_queue_url = os.environ.get('SQS_QUEUE_URL')
        self.s3_bucket_raw = os.environ.get('S3_BUCKET_RAW')
        self.fastapi_endpoint = os.environ.get('FASTAPI_ENDPOINT')
        self.aws_region = os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2')
        self.environment = os.environ.get('ENVIRONMENT', 'dev')
        
        # 필수 환경 변수 검증
        self._validate_config()
        
        # AWS 클라이언트 초기화
        self.sqs_client = boto3.client('sqs', region_name=self.aws_region)
        # S3 client는 필요 없음 (FastAPI가 직접 DB에 저장)
        
        logger.info(f"VideoProcessor initialized for environment: {self.environment}")
        logger.info(f"SQS Queue: {self.sqs_queue_url}")
        logger.info(f"FastAPI Endpoint: {self.fastapi_endpoint}")
    
    def _validate_config(self):
        """필수 환경 변수가 설정되었는지 검증"""
        required_vars = [
            'SQS_QUEUE_URL',
            'S3_BUCKET_RAW',
            'FASTAPI_ENDPOINT'
        ]
        
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            raise VideoProcessorError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )
    
    def receive_message(self) -> Optional[Dict[str, Any]]:
        """SQS에서 메시지 수신 (Long Polling)"""
        try:
            logger.info("Polling SQS for messages...")
            
            response = self.sqs_client.receive_message(
                QueueUrl=self.sqs_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,  # Long polling
                VisibilityTimeout=900,  # 15분
                MessageAttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            
            if not messages:
                logger.info("No messages in queue")
                return None
            
            message = messages[0]
            logger.info(f"Received message: {message['MessageId']}")
            
            return message
            
        except ClientError as e:
            logger.error(f"Error receiving message from SQS: {e}")
            raise VideoProcessorError(f"SQS receive error: {e}")
    
    def parse_s3_event(self, message: Dict[str, Any]) -> Dict[str, str]:
        """S3 이벤트 메시지 파싱"""
        try:
            # SQS 메시지 바디 파싱
            body = json.loads(message['Body'])
            
            # S3 이벤트 레코드 추출
            records = body.get('Records')
            if not records or not isinstance(records, list) or len(records) == 0:
                logger.error(f"Invalid S3 event: 'Records' missing or empty. Body: {json.dumps(body)[:500]}")
                raise VideoProcessorError("Invalid S3 event format: 'Records' missing or empty")
            
            record = records[0]
            s3_info = record['s3']
            
            bucket = s3_info['bucket']['name']
            key = s3_info['object']['key']
            event_time = record['eventTime']
            
            logger.info(f"S3 Event: bucket={bucket}, key={key}, time={event_time}")
            
            return {
                'bucket': bucket,
                'key': key,
                'event_time': event_time,
                'size': s3_info['object'].get('size', 0)
            }
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error parsing S3 event: {e}")
            raise VideoProcessorError(f"S3 event parsing error: {e}")
    
    def call_fastapi_analysis(self, s3_event: Dict[str, str]) -> Dict[str, Any]:
        """
        FastAPI 분석 서비스 호출
        FastAPI가 S3에서 비디오를 다운로드하고 분석 후 결과를 PostgreSQL + pgvector에 직접 저장함
        """
        try:
            # VIDEO_ID 가져오기
            video_id = os.environ.get('VIDEO_ID')
            if not video_id:
                # S3 key에서 의미 있는 식별자 추출 시도
                s3_key = s3_event.get('key', '')
                derived_id = os.path.splitext(os.path.basename(s3_key))[0] if s3_key else ''
                if not derived_id:
                    logger.error("VIDEO_ID not set and cannot derive from S3 key. Aborting.")
                    raise VideoProcessorError("VIDEO_ID is required but not set")
                logger.warning(f"VIDEO_ID not set, derived from S3 key: '{derived_id}'")
                video_id = derived_id
            
            # FastAPI 엔드포인트 구성
            analysis_url = f"{self.fastapi_endpoint.rstrip('/')}/analyze"
            
            # 요청 페이로드 - memi FastAPI가 기대하는 형식으로 변경
            payload = {
                'video_id': int(video_id),
                's3_bucket': s3_event['bucket'],
                's3_key': s3_event['key'],
                'output': '/app/output',
                'detector_weights': os.getenv('DETECTOR_WEIGHTS', '/app/models/yolov8x_person_face.pt'),
                'checkpoint': os.getenv('MIVOLO_CHECKPOINT', '/app/models/model_imdb_cross_person_4.24_99.46.pth.tar'),
                'mebow_cfg': os.getenv('MEBOW_CFG', '/app/config/mebow.yaml'),
                'vlm_path': os.getenv('VLM_PATH', '/app/checkpoints/llava-fastvithd_0.5b_stage2')
            }
            
            logger.info(f"Calling FastAPI: {analysis_url}")
            logger.info(f"Payload: {json.dumps(payload, indent=2)}")
            
            # FastAPI 호출 (타임아웃 25분, 최대 2회 시도)
            # FastAPI는 S3에서 다운로드 → 분석 → PostgreSQL + pgvector에 저장
            max_attempts = 2
            last_error = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        logger.info(f"Retry attempt {attempt}/{max_attempts} after transient error")
                        time.sleep(5)  # 재시도 전 5초 대기
                    
                    response = requests.post(
                        analysis_url,
                        json=payload,
                        timeout=1500,  # 25분
                        headers={'Content-Type': 'application/json'}
                    )
                    
                    response.raise_for_status()
                    
                    result = response.json()
                    logger.info(f"✅ FastAPI response: {json.dumps(result, indent=2)}")
                    logger.info("📊 Analysis started. Check job status via FastAPI.")
                    
                    return result
                    
                except requests.exceptions.Timeout:
                    logger.error("FastAPI request timed out")
                    raise VideoProcessorError("FastAPI timeout")
                
                except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                    last_error = e
                    logger.warning(f"Transient network error (attempt {attempt}/{max_attempts}): {e}")
                    if attempt == max_attempts:
                        break
                    continue
                
                except requests.exceptions.RequestException as e:
                    logger.error(f"FastAPI request failed: {e}")
                    if hasattr(e, 'response') and e.response is not None:
                        logger.error(f"Response body: {e.response.text}")
                    raise VideoProcessorError(f"FastAPI request error: {e}")
            
            # 모든 재시도 실패
            logger.error(f"FastAPI call failed after {max_attempts} attempts")
            raise VideoProcessorError(f"FastAPI request error after retries: {last_error}")
    
    # S3 저장 로직 제거
    # FastAPI가 분석 결과를 PostgreSQL + pgvector에 직접 저장하므로
    # Batch Job은 단순히 FastAPI를 호출만 하면 됨
    
    def delete_message(self, message: Dict[str, Any]):
        """처리 완료된 메시지를 SQS에서 삭제"""
        try:
            receipt_handle = message['ReceiptHandle']
            
            logger.info(f"Deleting message: {message['MessageId']}")
            
            self.sqs_client.delete_message(
                QueueUrl=self.sqs_queue_url,
                ReceiptHandle=receipt_handle
            )
            
            logger.info("Message deleted successfully")
            
        except ClientError as e:
            logger.error(f"Error deleting message: {e}")
            # 삭제 실패 시 메시지는 visibility timeout 후 다시 나타남
            raise VideoProcessorError(f"Message deletion error: {e}")
    
    def process_message(self, message: Dict[str, Any]) -> bool:
        """
        단일 메시지 처리 파이프라인
        1. S3 이벤트 파싱
        2. FastAPI 분석 호출 (FastAPI가 PostgreSQL + pgvector에 저장)
        3. SQS 메시지 삭제
        """
        try:
            logger.info("=" * 60)
            logger.info("Starting video analysis processing")
            logger.info("=" * 60)
            
            # 1. S3 이벤트 파싱
            s3_event = self.parse_s3_event(message)
            
            # 2. FastAPI 분석 호출
            # FastAPI가 내부적으로 다음을 처리:
            # - S3에서 비디오 다운로드
            # - AI 분석 (Object Detection, Tracking, etc.)
            # - 결과를 PostgreSQL + pgvector에 저장
            analysis_result = self.call_fastapi_analysis(s3_event)
            
            # 3. 성공한 메시지 삭제
            self.delete_message(message)
            
            logger.info("=" * 60)
            logger.info("✅ Video analysis completed successfully")
            logger.info("📊 Results saved to PostgreSQL + pgvector")
            logger.info("=" * 60)
            
            return True
            
        except VideoProcessorError as e:
            logger.error(f"❌ Processing failed: {e}")
            # 처리 실패 시 메시지는 큐에 남아서 재시도됨
            return False
        
        except Exception as e:
            logger.error(f"❌ Unexpected error during processing: {e}")
            logger.exception("Full traceback:")
            return False
    
    def run(self):
        """메인 실행 루프"""
        logger.info("🚀 Video Processor started")
        
        try:
            # Lambda가 환경 변수로 S3 정보를 전달했는지 확인
            s3_bucket = os.environ.get('S3_BUCKET')
            s3_key = os.environ.get('S3_KEY')
            
            if s3_bucket and s3_key:
                # Lambda에서 전달된 환경 변수 사용
                logger.info(f"Processing from Lambda env vars: s3://{s3_bucket}/{s3_key}")
                
                s3_event = {
                    'bucket': s3_bucket,
                    'key': s3_key,
                    'event_time': datetime.utcnow().isoformat(),
                    'size': 0
                }
                
                # FastAPI 분석 호출
                result = self.call_fastapi_analysis(s3_event)
                
                if result:
                    logger.info("✅ Job completed successfully")
                    sys.exit(0)
                else:
                    logger.error("❌ Job failed")
                    sys.exit(1)
            else:
                # 환경 변수 없으면 SQS에서 폴링 (기존 로직)
                logger.info("No S3 env vars, polling SQS...")
                message = self.receive_message()
                
                if message:
                    success = self.process_message(message)
                    
                    if success:
                        logger.info("✅ Job completed successfully")
                        sys.exit(0)
                    else:
                        logger.error("❌ Job failed")
                        sys.exit(1)
                else:
                    logger.info("📭 No messages to process")
                    sys.exit(0)
                
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}")
            logger.exception("Full traceback:")
            sys.exit(1)


def main():
    """진입점"""
    try:
        processor = VideoProcessor()
        processor.run()
    except VideoProcessorError as e:
        logger.error(f"Initialization failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main()
