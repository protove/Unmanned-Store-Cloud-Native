# FastAPI 영상 분석 서비스 Config 설정

## 수정된 config.py (권장 버전)

```python
# video_analysis_fastapi/config.py
import os
import json
import boto3
from functools import lru_cache

# ============================================
# 1. PostgreSQL (pgvector) 연결 설정
# ============================================
# Secrets Manager에서 자동으로 가져오기
def get_db_credentials():
    """Secrets Manager에서 DB 자격증명 가져오기"""
    secret_arn = os.getenv("DB_SECRET_ARN")
    if not secret_arn:
        # 로컬 개발환경 fallback
        return {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": os.getenv("POSTGRES_PORT", "5432"),
            "database": os.getenv("POSTGRES_DB", "capstone_db"),
            "username": os.getenv("POSTGRES_USER", "capstone_user"),
            "password": os.getenv("POSTGRES_PASSWORD", "password")
        }

    # Production: Secrets Manager 사용
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=os.getenv("AWS_REGION", "ap-northeast-2")
    )

    try:
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response['SecretString'])
        return secret
    except Exception as e:
        print(f"❌ Secrets Manager 오류: {e}")
        raise


# DB 설정 캐싱 (한 번만 조회)
@lru_cache()
def get_db_config():
    creds = get_db_credentials()
    return {
        "host": creds.get("host") or creds.get("POSTGRES_HOST"),
        "port": int(creds.get("port", 5432)),
        "database": creds.get("database") or creds.get("POSTGRES_DB", "capstone_db"),
        "user": creds.get("username") or creds.get("POSTGRES_USER"),
        "password": creds.get("password") or creds.get("POSTGRES_PASSWORD")
    }


# ============================================
# 2. AWS S3 설정
# ============================================
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")

# 원본 영상 버킷 (읽기 전용)
S3_BUCKET_RAW = os.getenv("S3_BUCKET_RAW", "capstone-dev-raw")

# 썸네일 저장 버킷 (쓰기)
S3_BUCKET_THUMBNAILS = os.getenv("S3_BUCKET_THUMBNAILS", "capstone-dev-thumbnails")

# ============================================
# 3. AWS Bedrock 설정
# ============================================
AWS_BEDROCK_REGION = os.getenv("AWS_BEDROCK_REGION", "us-east-1")  # Bedrock 리전

# VLM (Vision Language Model) - 영상 분석
AWS_BEDROCK_VLM_MODEL = os.getenv(
    "AWS_BEDROCK_VLM_MODEL",
    "anthropic.claude-3-sonnet-20240229-v1:0"
)

# Embedding Model - 벡터 임베딩
AWS_BEDROCK_EMBEDDING_MODEL = os.getenv(
    "AWS_BEDROCK_EMBEDDING_MODEL",
    "amazon.titan-embed-text-v2:0"
)

# ============================================
# 4. Backend Django API 연결 (선택사항)
# ============================================
# FastAPI가 직접 DB에 저장하므로 필수는 아님
# 필요하면 Django API 호출용
BACKEND_API_URL = os.getenv(
    "BACKEND_API_URL",
    "http://capstone-alb-175357648.ap-northeast-2.elb.amazonaws.com"  # ALB DNS
)

# ============================================
# 5. 영상 분석 설정
# ============================================
# 프레임 추출 간격 (초)
FRAME_EXTRACTION_INTERVAL = float(os.getenv("FRAME_EXTRACTION_INTERVAL", "1.0"))

# 썸네일 이미지 품질 (1-100)
THUMBNAIL_QUALITY = int(os.getenv("THUMBNAIL_QUALITY", "85"))

# 최대 프레임 수 (메모리 제한)
MAX_FRAMES_PER_VIDEO = int(os.getenv("MAX_FRAMES_PER_VIDEO", "300"))

# 영상 처리 타임아웃 (초)
VIDEO_PROCESSING_TIMEOUT = int(os.getenv("VIDEO_PROCESSING_TIMEOUT", "1800"))  # 30분

# ============================================
# 6. 환경 설정
# ============================================
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# ============================================
# 7. 로깅 설정
# ============================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
```

## Batch Job Definition에 추가할 환경변수

현재 Batch Job Definition에는 다음 환경변수들이 설정되어 있습니다:

### 현재 설정 ✅

```hcl
environment = [
  {
    name  = "AWS_DEFAULT_REGION"
    value = "ap-northeast-2"
  },
  {
    name  = "SQS_QUEUE_URL"
    "value": "https://sqs.ap-northeast-2.amazonaws.com/<AWS_ACCOUNT_ID>/capstone-dev-video-processing"
  },
  {
    name  = "S3_BUCKET_RAW"
    value = "capstone-dev-raw"
  },
  {
    name  = "FASTAPI_ENDPOINT"
    value = "http://capstone-alb-175357648.ap-northeast-2.elb.amazonaws.com:8087"
  },
  {
    name  = "DB_SECRET_ARN"
    "value": "arn:aws:secretsmanager:ap-northeast-2:<AWS_ACCOUNT_ID>:secret:capstone/db-password"
  },
  {
    name  = "ENVIRONMENT"
    value = "dev"
  }
]
```

### 추가 필요 환경변수 📝

Terraform `batch.tf`에 다음을 추가해야 합니다:

```hcl
{
  name  = "S3_BUCKET_THUMBNAILS"
  value = aws_s3_bucket.thumbnails.bucket  # 새로 만들 버킷
},
{
  name  = "AWS_BEDROCK_REGION"
  value = "us-east-1"  # Bedrock 사용 가능 리전
},
{
  name  = "AWS_BEDROCK_VLM_MODEL"
  value = "anthropic.claude-3-sonnet-20240229-v1:0"
},
{
  name  = "AWS_BEDROCK_EMBEDDING_MODEL"
  value = "amazon.titan-embed-text-v2:0"
},
{
  name  = "THUMBNAIL_QUALITY"
  value = "85"
},
{
  name  = "FRAME_EXTRACTION_INTERVAL"
  value = "1.0"
}
```

## 주요 차이점 정리

### ❌ 원본 config.py 문제점

```python
# 1. 환경변수 이름 불일치
POSTGRES_HOST = os.getenv("POSTGRES_HOST")  # ❌ Batch에서 제공 안 함
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")  # ❌ S3_BUCKET_RAW로 변경 필요

# 2. Secrets Manager 미활용
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")  # ❌ 평문 환경변수
# 실제로는 DB_SECRET_ARN으로 Secrets Manager에서 가져와야 함

# 3. Service Discovery DNS 미사용
BACKEND_API_URL = "http://backend.capstone.local:8000"  # ❌ 이런 DNS 설정 안 함
# 실제로는 ALB DNS 사용: capstone-alb-175357648.ap-northeast-2.elb.amazonaws.com

# 4. 썸네일 버킷 누락
# S3_BUCKET_THUMBNAILS 설정 없음
```

### ✅ 수정된 config.py 장점

```python
# 1. Secrets Manager 자동 파싱
def get_db_credentials():
    secret_arn = os.getenv("DB_SECRET_ARN")
    # JSON 파싱하여 host, port, username, password 추출

# 2. 환경변수 이름 일치
S3_BUCKET_RAW = os.getenv("S3_BUCKET_RAW")  # Batch 환경변수와 동일
S3_BUCKET_THUMBNAILS = os.getenv("S3_BUCKET_THUMBNAILS")

# 3. 실제 ALB DNS 사용
BACKEND_API_URL = "http://capstone-alb-175357648.ap-northeast-2.elb.amazonaws.com"

# 4. Bedrock 리전 구분
AWS_BEDROCK_REGION = "us-east-1"  # Claude 3 사용 가능 리전
AWS_REGION = "ap-northeast-2"     # S3, RDS 리전
```

## Secrets Manager Secret 구조

현재 `capstone/db-password` secret의 JSON 구조:

```json
{
  "username": "capstone_user",
  "password": "랜덤생성된비밀번호",
  "engine": "postgres",
  "host": "capstone-postgres.xxxxx.ap-northeast-2.rds.amazonaws.com",
  "port": 5432,
  "dbname": "capstone_db"
}
```

## 사용 예시 (FastAPI main.py)

```python
from fastapi import FastAPI
from config import get_db_config, S3_BUCKET_RAW, S3_BUCKET_THUMBNAILS
import psycopg2

app = FastAPI()

# DB 연결
@app.on_event("startup")
async def startup():
    db_config = get_db_config()
    conn = psycopg2.connect(
        host=db_config['host'],
        port=db_config['port'],
        database=db_config['database'],
        user=db_config['user'],
        password=db_config['password']
    )
    app.state.db = conn
    print(f"✅ PostgreSQL 연결 성공: {db_config['host']}")


@app.post("/analyze")
async def analyze_video(s3_bucket: str, s3_key: str):
    # 1. S3에서 영상 다운로드
    print(f"📥 다운로드: s3://{S3_BUCKET_RAW}/{s3_key}")

    # 2. 영상 분석
    events = await analyze_with_bedrock(video_path)

    # 3. 프레임 추출 및 썸네일 저장
    for event in events:
        frame = extract_frame(video_path, event['timestamp'])
        thumbnail_key = f"events/{event['id']}/frame.jpg"

        # S3에 썸네일 업로드
        upload_to_s3(
            bucket=S3_BUCKET_THUMBNAILS,
            key=thumbnail_key,
            body=frame
        )
        print(f"📤 썸네일 업로드: s3://{S3_BUCKET_THUMBNAILS}/{thumbnail_key}")

        event['s3_thumbnail_key'] = thumbnail_key

    # 4. PostgreSQL에 저장
    save_to_db(app.state.db, events)

    return {"status": "success", "events": events}
```

## 다음 단계

1. ✅ `video_storage` 버킷 삭제 (Terraform)
2. ✅ `thumbnails` 버킷 생성 (Terraform)
3. ✅ Batch Task Role에 thumbnails 버킷 write 권한 추가
4. ⏸️ FastAPI 프로젝트 생성 및 config.py 추가
5. ⏸️ 영상 분석 로직 구현

이렇게 수정하면 **production 환경에서 안전하게 동작**합니다! 👍
