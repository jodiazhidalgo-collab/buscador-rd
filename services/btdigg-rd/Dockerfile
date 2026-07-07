FROM python:3.11-bookworm

ARG CHROMIUM_VERSION=147.0.7727.137-1~deb12u1

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BROWSER_BIN=/usr/bin/chromium

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium=${CHROMIUM_VERSION} \
        chromium-common=${CHROMIUM_VERSION} \
        chromium-sandbox=${CHROMIUM_VERSION} \
        ca-certificates \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY app /app/app

EXPOSE 9007
CMD ["python", "/app/app/app.py"]
