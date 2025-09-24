# Dockerfile (minimal)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Streamlit: bind to 0.0.0.0 and use $PORT
CMD ["bash","-lc","streamlit run mapsScraper.py --server.address=0.0.0.0 --server.port=${PORT:-8080} --server.headless=true"]
