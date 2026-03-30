# 개발자 S3 접근 가이드

## 📦 사용 가능한 S3 버킷

개발자 그룹(`capstone-developers`)에 속한 사용자는 다음 S3 버킷에 접근할 수 있습니다:

1. **capstone-dev-videos** - 메인 비디오 스토리지
2. **capstone-dev-raw** - 원본 비디오 파일
3. **capstone-dev-results** - 분석 결과 저장

## 🔐 권한 요약

### 버킷 레벨 권한

- `s3:ListBucket` - 버킷 내 객체 목록 조회
- `s3:GetBucketLocation` - 버킷 리전 정보 조회
- `s3:GetBucketVersioning` - 버킷 버저닝 상태 확인
- `s3:ListAllMyBuckets` - 모든 버킷 목록 조회

### 객체 레벨 권한

- `s3:PutObject` - 파일 업로드
- `s3:GetObject` - 파일 다운로드
- `s3:DeleteObject` - 파일 삭제
- `s3:GetObjectVersion` - 특정 버전 파일 조회
- `s3:GetObjectVersionAcl` - 파일 버전 ACL 조회

## 💻 AWS CLI 사용 예시

### 1. 버킷 목록 확인

```bash
aws s3 ls
```

### 2. 특정 버킷 내용 확인

```bash
aws s3 ls s3://capstone-dev-videos/
```

### 3. 파일 업로드

```bash
# 단일 파일 업로드
aws s3 cp video.mp4 s3://capstone-dev-videos/

# 디렉토리 전체 업로드
aws s3 cp ./videos/ s3://capstone-dev-raw/ --recursive
```

### 4. 파일 다운로드

```bash
# 단일 파일 다운로드
aws s3 cp s3://capstone-dev-videos/video.mp4 ./

# 디렉토리 전체 다운로드
aws s3 cp s3://capstone-dev-results/ ./results/ --recursive
```

### 5. 파일 삭제

```bash
aws s3 rm s3://capstone-dev-videos/old-video.mp4
```

### 6. 파일 동기화

```bash
# 로컬 → S3 동기화
aws s3 sync ./local-folder/ s3://capstone-dev-videos/

# S3 → 로컬 동기화
aws s3 sync s3://capstone-dev-results/ ./local-results/
```

## 🐍 Python (boto3) 사용 예시

### 설치

```bash
pip install boto3
```

### 파일 업로드

```python
import boto3

s3 = boto3.client('s3')

# 파일 업로드
s3.upload_file('video.mp4', 'capstone-dev-videos', 'videos/video.mp4')

# 메타데이터와 함께 업로드
s3.upload_file(
    'video.mp4',
    'capstone-dev-videos',
    'videos/video.mp4',
    ExtraArgs={'Metadata': {'uploaded-by': 'developer'}}
)
```

### 파일 다운로드

```python
import boto3

s3 = boto3.client('s3')

# 파일 다운로드
s3.download_file('capstone-dev-videos', 'videos/video.mp4', 'local-video.mp4')
```

### 파일 목록 조회

```python
import boto3

s3 = boto3.client('s3')

# 버킷 내 모든 객체 목록
response = s3.list_objects_v2(Bucket='capstone-dev-videos')
for obj in response.get('Contents', []):
    print(f"{obj['Key']} - {obj['Size']} bytes - {obj['LastModified']}")
```

### 파일 삭제

```python
import boto3

s3 = boto3.client('s3')

# 단일 파일 삭제
s3.delete_object(Bucket='capstone-dev-videos', Key='videos/old-video.mp4')

# 여러 파일 삭제
s3.delete_objects(
    Bucket='capstone-dev-videos',
    Delete={
        'Objects': [
            {'Key': 'videos/old1.mp4'},
            {'Key': 'videos/old2.mp4'}
        ]
    }
)
```

### Pre-signed URL 생성 (임시 다운로드 링크)

```python
import boto3

s3 = boto3.client('s3')

# 1시간 동안 유효한 다운로드 링크 생성
url = s3.generate_presigned_url(
    'get_object',
    Params={
        'Bucket': 'capstone-dev-videos',
        'Key': 'videos/video.mp4'
    },
    ExpiresIn=3600  # 1시간
)
print(f"다운로드 링크: {url}")
```

## 🔒 보안 모범 사례

### 1. AWS Credentials 관리

- **절대로 코드에 직접 하드코딩하지 마세요!**
- AWS CLI 설정 사용: `aws configure`
- 환경 변수 사용:
  ```bash
  export AWS_ACCESS_KEY_ID=your_access_key
  export AWS_SECRET_ACCESS_KEY=your_secret_key
  export AWS_DEFAULT_REGION=ap-northeast-2
  ```

### 2. .gitignore 설정

프로젝트 루트에 다음 내용 추가:

```
# AWS Credentials
.aws/
*.pem
*.key
.env
.env.local
```

### 3. IAM 사용자 자격 증명 발급

관리자에게 요청하여 IAM 사용자 생성 및 Access Key 발급:

- 사용자 이름: `seungbeom-dev` 또는 `doyeon-dev`
- 그룹: `capstone-developers`
- Access Key 발급 후 안전하게 보관

## 📊 현재 개발자 그룹 멤버

- **seungbeom-dev** - 개발자
- **doyeon-dev** - 개발자

## 🆘 문제 해결

### Access Denied 오류 발생 시

```bash
# 현재 사용자 확인
aws sts get-caller-identity

# 출력 예시:
# {
#     "UserId": "AIDAXXXXXXXXX",
#     "Account": "<AWS_ACCOUNT_ID>",
#     "Arn": "arn:aws:iam::<AWS_ACCOUNT_ID>:user/seungbeom-dev"
# }
```

### 자격 증명 재설정

```bash
aws configure
# AWS Access Key ID [None]: YOUR_ACCESS_KEY
# AWS Secret Access Key [None]: YOUR_SECRET_KEY
# Default region name [None]: ap-northeast-2
# Default output format [None]: json
```

## 📞 지원

문제가 발생하거나 추가 권한이 필요한 경우:

- 관리자: siheon-admin
- Slack: #capstone-support
- Email: admin@capstone-project.com

## 🔄 업데이트 이력

- **2025-10-27**: 초기 S3 접근 권한 설정
  - 3개 S3 버킷에 대한 읽기/쓰기/삭제 권한 부여
  - PowerUserAccess 기본 권한 유지
