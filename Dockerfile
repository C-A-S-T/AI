FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt requirements-policy-compare.txt requirements-docker.txt ./

RUN pip install --no-cache-dir -r requirements-docker.txt

COPY src/ ./src/

RUN mkdir -p /app/data/embeddings

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
