#################### 0️⃣ Build stage ####################
FROM python:3.13-slim AS builder
WORKDIR /mcp

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# (/install 하위) 파이썬 패키지 설치
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


#################### 1️⃣ Runtime stage ##################
FROM python:3.13-slim
WORKDIR /mcp

# 환경변수 설정 
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501

# 비루트 사용자 생성 (보안 목적)
RUN useradd -m appuser

# 빌드된 파이썬 패키지 복사(루트 권한)
COPY --from=builder /install /usr/local 

# 이후 명렁을 전부 appuser(비루트)로 수행
USER appuser

# 소스 코드 복사 및 appuser로 권한 변경       
COPY --chown=appuser:appuser . .                                      

EXPOSE 8501

# Streamlit entrypoint
CMD sh -c 'streamlit run mcp_host/app.py \
           --server.port=${PORT} \
           --server.address=0.0.0.0'