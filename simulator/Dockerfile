# 构建上下文是**仓库根目录**（见 docker-compose.yml）
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY simulator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# V2：新增 weather.py（气象 Mock 数据源），与 mock_sensor.py 同目录（脚本式导入）
COPY simulator/mock_sensor.py simulator/weather.py ./

RUN adduser --disabled-password --gecos "" --uid 10002 sim
USER sim

ENV MQTT_HOST=mosquitto \
    MQTT_PORT=1883 \
    SIM_INTERVAL_SECONDS=5 \
    WEATHER_INTERVAL_SECONDS=30

CMD ["python", "mock_sensor.py"]
