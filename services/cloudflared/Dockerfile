FROM cloudflare/cloudflared:latest AS cloudflared-bin

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=cloudflared-bin /usr/local/bin/cloudflared /usr/local/bin/cloudflared

COPY watcher/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY watcher/app/ /app/watcher/
COPY worker/ /app/worker/
COPY supervisor.py /app/supervisor.py

CMD ["python", "/app/supervisor.py"]
