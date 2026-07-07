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
        curl \
        fonts-liberation \
        git \
        openssh-client \
        tar \
    && GITLEAKS_URL="$(python -c 'import json, urllib.request; data=json.load(urllib.request.urlopen("https://api.github.com/repos/gitleaks/gitleaks/releases/latest")); print(next(asset["browser_download_url"] for asset in data["assets"] if "linux_x64.tar.gz" in asset["name"]))')" \
    && curl -fsSL "$GITLEAKS_URL" -o /tmp/gitleaks.tar.gz \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    && rm -rf /var/lib/apt/lists/* /tmp/gitleaks.tar.gz

WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY requirements-dev.txt /app/requirements-dev.txt
RUN pip install -r /app/requirements-dev.txt
COPY app /app/app

EXPOSE 9007
CMD ["python", "/app/app/app.py"]
