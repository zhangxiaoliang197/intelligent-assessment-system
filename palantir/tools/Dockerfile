FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulate_events.py .

# Unbuffered stdout so logs appear immediately in docker compose logs
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "simulate_events.py"]
