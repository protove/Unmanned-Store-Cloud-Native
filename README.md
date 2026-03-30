# Unmanned Store — Cloud-Native Video Analysis Pipeline

> **EC2 GPU 항시 가동 비용 문제 발견 → SQS·Lambda 온디맨드 아키텍처 2단계 재설계 완성**

무인매장 CCTV 영상에서 행동 타임라인을 추출하는 클라우드 네이티브 파이프라인입니다.  
영상 업로드부터 GPU 기반 분석까지의 전체 흐름을 **S3 → SQS → Lambda → EC2 GPU 온디맨드** 아키텍처로 설계·구현했습니다.

---

## 📌 담당 역할

| 항목 | 내용 |
|------|------|
| **역할** | S3 / SQS / EC2 GPU 파이프라인 설계·구현 |
| **팀 규모** | 3인 (AI Cloud Native, Infra — S3+SQS+EC2 GPU, Infra — Fullstack) |
| **내 파트** | 영상 업로드(S3 Pre-signed URL) → 메시지 큐(SQS) → GPU 온디맨드 분석(Lambda·EC2) 전체 흐름 |

---

## 🏗 아키텍처 진화 — 3단계

### AS-IS: GPU 상시 가동

```
Client → S3 Upload → SQS → EC2 GPU (Always ON)
                                 ↓
                           Video Analysis
```

**문제**: GPU EC2 인스턴스(g5.xlarge)가 유휴 시간에도 계속 가동 → 비용 낭비 심각

---

### TO-BE ①: Lambda + EC2 온디맨드 기동

```
Client → Pre-signed URL → S3 Upload
                              ↓
                     S3 Event Notification
                              ↓
                           SQS Queue ←→ DLQ (Dead Letter Queue)
                              ↓
                     Lambda (Trigger)
                              ↓
                     EC2 GPU On-Demand 기동
                              ↓
                        Video Analysis
                              ↓
                     PostgreSQL + pgvector
```

**해결**: 영상 업로드 시에만 Lambda가 EC2 GPU를 기동 → 유휴 비용 제거

---

### TO-BE ②: ECR + EBS 캐시 분리

```
                     EC2 GPU On-Demand 기동
                              ↓
                 ┌─────────────────────────┐
                 │   ECR (Docker Image)    │ ← 사전 빌드된 이미지
                 │   EBS (Model Cache)     │ ← 23GB 모델 캐시
                 └─────────────────────────┘
                              ↓
                     즉시 분석 시작 (빌드 없음)
```

**문제 발견**: EC2 기동 시 23GB AI 모델을 매번 다운로드 → 기동 시간 과다  
**해결**: ECR에 Docker 이미지 사전 빌드 + EBS 볼륨에 모델 캐시 → 빌드 없이 즉시 기동

---

## ⭐ STAR

| 항목 | 내용 |
|------|------|
| **S** (Situation) | EC2 GPU 인스턴스가 항시 가동되어 유휴 시간에도 비용이 발생하고 있었음 |
| **T** (Task) | S3/SQS/EC2 GPU 영상 처리 파이프라인 설계·구현 담당 |
| **A** (Action) | ① SQS → Lambda → EC2 GPU 온디맨드 기동으로 비용 문제 해결 설계 ② 빌드 중 23GB 문제 발견 → ECR + EBS 캐시 분리로 재설계 |
| **R** (Result) | 비용·빌드 문제를 연속으로 발견하고 2단계 아키텍처 재설계를 완성 |

---

## 🔧 핵심 기술 구현

### 1. S3 Pre-signed URL 기반 업로드 (`back/apps/api/`)

```
Client → JWT 인증 → Pre-signed URL 발급 → S3 Direct Upload → Upload 확인 → SQS 메시지 발행
```

- JWT 토큰 기반 사용자 인증
- S3 Pre-signed URL로 클라이언트 직접 업로드 (서버 부하 제거)
- 업로드 확인 시 SQS 메시지 자동 발행

### 2. SQS + Lambda 이벤트 파이프라인 (`lambda/sqs_to_batch.py`)

- S3 이벤트 → SQS 큐 → Lambda 자동 트리거
- **Partial Batch Response** — 실패 메시지만 재시도 (정상 메시지는 삭제)
- **에러 분류** — transient(네트워크) vs permanent(데이터) 구분하여 DLQ 정책 최적화
- video_id 추출 검증 + 구조화된 로깅

### 3. GPU Worker 가시성 타임아웃 관리 (`gpu_worker/`)

- **Visibility Timeout Manager** — 백그라운드 스레드에서 SQS 메시지 가시성 타임아웃 자동 연장
- `threading.Lock` 기반 스레드 안전한 메시지 관리
- 동적 모니터링 간격 (extension_interval의 50%)
- 3회 연속 연장 실패 시 자동 해제
- **Error Handler** — 에러 타입(TEMPORARY/PERMANENT/SYSTEM) 분류 + 지수 백오프 재시도

### 4. Terraform — S3/SQS/Lambda 인프라 (`terraform/`)

- **SQS**: DLQ 연동, Long Polling 20초, CloudWatch 알람
- **Lambda**: SQS 트리거, IAM 최소 권한
- **S3**: 이벤트 알림, 버킷 정책

---

## 🛠 기술 스택 (내 담당 범위)

| 구분 | 기술 |
|------|------|
| **Cloud** | AWS S3, SQS, Lambda, EC2 GPU (g5.xlarge), ECR, EBS |
| **Backend API** | Django REST Framework (S3 Pre-signed URL, SQS 메시지 발행) |
| **GPU Worker** | Python, boto3, threading (Visibility Timeout Manager) |
| **IaC** | Terraform (S3, SQS, Lambda 리소스) |

---

## 🐛 트러블슈팅

### 1. EC2 GPU 유휴 비용 문제

| 항목 | 내용 |
|------|------|
| **현상** | GPU EC2(g5.xlarge) 인스턴스가 영상 처리 요청이 없는 시간에도 계속 가동 |
| **원인** | SQS Long Polling 방식으로 항시 인스턴스를 유지하는 아키텍처 |
| **해결** | SQS → Lambda → EC2 온디맨드 기동으로 전환. 요청이 있을 때만 인스턴스 기동 |

### 2. 23GB AI 모델 빌드 시간 문제

| 항목 | 내용 |
|------|------|
| **현상** | EC2 온디맨드 기동 시 Docker 빌드 과정에서 23GB 모델 다운로드 필요 |
| **원인** | Docker 이미지에 모델 파일이 포함되어 있어 매 기동마다 전체 빌드 발생 |
| **해결** | ECR에 사전 빌드된 Docker 이미지 + EBS 볼륨에 모델 캐시 분리로 즉시 기동 |

### 3. SQS 메시지 중복 처리

| 항목 | 내용 |
|------|------|
| **현상** | 동일 영상에 대해 GPU 분석이 여러 번 실행됨 |
| **원인** | S3 이벤트 알림이 동일 객체에 대해 중복 발생 |
| **해결** | MessageDeduplicationId 지원 추가 + S3 이벤트 필터 규칙 강화 |

### 4. Visibility Timeout 초과로 메시지 재처리

| 항목 | 내용 |
|------|------|
| **현상** | 대용량 영상 처리 중 SQS 메시지가 다시 큐에 나타나 중복 처리 |
| **원인** | 고정 visibility timeout(5분)이 실제 처리 시간(10분+)보다 짧음 |
| **해결** | 백그라운드 스레드에서 가시성 타임아웃 동적 연장 + 스레드 안전 관리 |

---

## 📁 프로젝트 구조

```
├── back/                    # Django Backend
│   ├── apps/api/            # REST API (S3 업로드, SQS 메시지 발행)
│   │   ├── services/        # S3Service, SQSService
│   │   └── views_s3.py      # Pre-signed URL, Upload 확인
│   └── core/                # Django 설정
├── gpu_worker/              # EC2 GPU Worker
│   ├── video_processor.py   # SQS 메시지 수신 → 영상 분석
│   ├── visibility_manager.py # 가시성 타임아웃 자동 연장
│   └── error_handler.py     # 에러 분류 + 재시도
├── lambda/                  # AWS Lambda
│   └── sqs_to_batch.py      # SQS → EC2 기동 트리거
├── batch/                   # Batch 프로세서
│   └── process_video.py     # FastAPI 분석 서비스 호출
├── terraform/               # Infrastructure as Code
│   ├── sqs.tf               # SQS + DLQ + CloudWatch
│   ├── lambda.tf            # Lambda + IAM
│   └── s3.tf                # S3 + 이벤트 알림
├── front/                   # Next.js Frontend
└── nginx/                   # Reverse Proxy
```

---

## 🚀 로컬 개발 환경

### Prerequisites

- Python 3.10+, Node.js 18+, PostgreSQL 15+, Docker

### Quick Start

```bash
# 1. Clone
git clone https://github.com/protove/Unmanned-Store-Cloud-Native.git
cd Unmanned-Store-Cloud-Native

# 2. Backend
cd back && python3 -m venv env && source env/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 환경변수 설정

# 3. Frontend
cd ../front && yarn install

# 4. Docker Compose (전체 서비스)
docker-compose up -d
```

### Environment Variables

```env
# Django
SECRET_KEY=your-secret-key
DEBUG=True

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=capstone
DB_USER=postgres
DB_PASSWORD=your-password

# AWS
AWS_REGION=ap-northeast-2
S3_BUCKET_NAME=your-bucket
SQS_QUEUE_URL=your-queue-url
```

---

## 📄 License

MIT License
