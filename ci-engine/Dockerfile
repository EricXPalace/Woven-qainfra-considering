FROM python:3.11-slim

WORKDIR /app

# Install system utilities & docker socket client support
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY tests/ ./tests/

ENV MQTT_HOST=mosquitto \
    MQTT_PORT=1883 \
    MQTT_TOPIC=safety/blackbox/dump \
    PAYLOAD_SAVE_PATH=/app/received_payload.json

CMD ["python", "app.py"]
