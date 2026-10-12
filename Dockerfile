FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY model_aggregator ./model_aggregator
COPY frontend ./frontend

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "AGGREGATOR_HOST=0.0.0.0 AGGREGATOR_PORT=${PORT:-8080} python -m model_aggregator.server"]
