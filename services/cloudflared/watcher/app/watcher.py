import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


API_BASE = "https://api.cloudflare.com/client/v4"
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def env(name, default=""):
    return os.getenv(name, default).strip()


ACCOUNT_ID = env("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = env("CLOUDFLARE_API_TOKEN")
WORKERS_DEV_SUBDOMAIN = env("WORKERS_DEV_SUBDOMAIN", "lacabraesmia-cloudflared")
WORKER_NAME = env("WORKER_NAME", "cloudflared")
KV_NAMESPACE_TITLE = env("KV_NAMESPACE_TITLE", "cloudflared_tunnel_state")
KV_KEY_CURRENT_URL = env("KV_KEY_CURRENT_URL", "current_url")
GATEWAY_KEY = env("GATEWAY_KEY")
CLOUDFLARED_LOG = Path(env("CLOUDFLARED_LOG", "/app/logs/cloudflared/cloudflared.log"))
STATE_FILE = Path(env("STATE_FILE", "/app/data/estado/tunnel_state.json"))
LINK_FILE = Path(env("LINK_FILE", "/app/data/estado/enlace_usuario.txt"))
WORKER_SOURCE = Path(env("WORKER_SOURCE", "/app/worker/gateway_worker.js"))
LOG_FILE = Path(env("WATCHER_LOG", "/app/logs/watcher/watcher.log"))
POLL_SECONDS = float(env("POLL_SECONDS", "4"))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def auth_headers():
    return {"Authorization": f"Bearer {API_TOKEN}"}


def cf_request(method, path, **kwargs):
    if not ACCOUNT_ID:
        raise RuntimeError("Falta CLOUDFLARE_ACCOUNT_ID")
    if not API_TOKEN:
        raise RuntimeError("Falta CLOUDFLARE_API_TOKEN")

    headers = kwargs.pop("headers", {})
    headers.update(auth_headers())
    url = f"{API_BASE}{path}"
    response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    text = response.text[:2000]

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Cloudflare no devolvio JSON: HTTP {response.status_code} {text}") from exc

    if not response.ok or not payload.get("success", False):
        errors = payload.get("errors") or []
        raise RuntimeError(f"Cloudflare fallo {method} {path}: HTTP {response.status_code} {errors or text}")

    return payload.get("result")


def ensure_workers_dev_subdomain():
    try:
        result = cf_request("GET", f"/accounts/{ACCOUNT_ID}/workers/subdomain")
        current = (result or {}).get("subdomain") or ""
        if current:
            logging.info("workers.dev subdomain activo: %s", current)
            return current
    except Exception as exc:
        logging.warning("No se pudo leer workers.dev subdomain: %s", exc)

    result = cf_request(
        "PUT",
        f"/accounts/{ACCOUNT_ID}/workers/subdomain",
        json={"subdomain": WORKERS_DEV_SUBDOMAIN},
        headers={"Content-Type": "application/json"},
    )
    current = (result or {}).get("subdomain") or WORKERS_DEV_SUBDOMAIN
    logging.info("workers.dev subdomain creado: %s", current)
    return current


def list_kv_namespaces():
    result = cf_request("GET", f"/accounts/{ACCOUNT_ID}/storage/kv/namespaces?per_page=100")
    return result or []


def ensure_kv_namespace():
    for item in list_kv_namespaces():
        if item.get("title") == KV_NAMESPACE_TITLE:
            logging.info("KV existente: %s", KV_NAMESPACE_TITLE)
            return item["id"]

    result = cf_request(
        "POST",
        f"/accounts/{ACCOUNT_ID}/storage/kv/namespaces",
        json={"title": KV_NAMESPACE_TITLE},
        headers={"Content-Type": "application/json"},
    )
    namespace_id = result["id"]
    logging.info("KV creado: %s", KV_NAMESPACE_TITLE)
    return namespace_id


def deploy_worker(namespace_id):
    worker_code = WORKER_SOURCE.read_text(encoding="utf-8")
    metadata = {
        "main_module": "gateway_worker.js",
        "compatibility_date": "2026-07-03",
        "bindings": [
            {"type": "kv_namespace", "name": "TUNNEL_STATE", "namespace_id": namespace_id},
            {"type": "plain_text", "name": "KV_KEY_CURRENT_URL", "text": KV_KEY_CURRENT_URL},
            {"type": "plain_text", "name": "GATEWAY_KEY", "text": GATEWAY_KEY},
        ],
    }
    files = {
        "metadata": ("metadata", json.dumps(metadata), "application/json"),
        "gateway_worker.js": (
            "gateway_worker.js",
            worker_code.encode("utf-8"),
            "application/javascript+module",
        ),
    }
    cf_request("PUT", f"/accounts/{ACCOUNT_ID}/workers/scripts/{WORKER_NAME}", files=files)
    logging.info("Worker desplegado: %s", WORKER_NAME)

    cf_request(
        "POST",
        f"/accounts/{ACCOUNT_ID}/workers/scripts/{WORKER_NAME}/subdomain",
        json={"enabled": True, "previews_enabled": False},
        headers={"Content-Type": "application/json"},
    )
    logging.info("workers.dev habilitado para Worker: %s", WORKER_NAME)


def put_kv_text(namespace_id, key, value):
    response = requests.put(
        f"{API_BASE}/accounts/{ACCOUNT_ID}/storage/kv/namespaces/{namespace_id}/values/{key}",
        headers={**auth_headers(), "Content-Type": "text/plain; charset=utf-8"},
        data=value.encode("utf-8"),
        timeout=30,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"KV no devolvio JSON: HTTP {response.status_code} {response.text[:500]}") from exc
    if not response.ok or not payload.get("success", False):
        raise RuntimeError(f"KV fallo: HTTP {response.status_code} {payload.get('errors') or response.text[:500]}")


def read_cloudflared_log():
    if not CLOUDFLARED_LOG.exists():
        return ""
    return CLOUDFLARED_LOG.read_text(encoding="utf-8", errors="ignore")


def latest_tunnel_url():
    matches = TUNNEL_RE.findall(read_cloudflared_log())
    if not matches:
        return ""
    return matches[-1].rstrip("/")


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_link(worker_url):
    LINK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if GATEWAY_KEY:
        link = f"{worker_url}/?key={GATEWAY_KEY}"
    else:
        link = worker_url
    LINK_FILE.write_text(link + "\n", encoding="utf-8")


def bootstrap_cloudflare():
    if not API_TOKEN:
        logging.error("Falta CLOUDFLARE_API_TOKEN. El vigilante seguira leyendo el tunel, pero no puede publicar Cloudflare.")
        return None, ""
    if not GATEWAY_KEY:
        logging.warning("Falta GATEWAY_KEY. El Worker quedara sin llave de entrada.")

    subdomain = ensure_workers_dev_subdomain()
    namespace_id = ensure_kv_namespace()
    deploy_worker(namespace_id)
    worker_url = f"https://{WORKER_NAME}.{subdomain}.workers.dev"
    save_link(worker_url)
    return namespace_id, worker_url


def publish_tunnel(namespace_id, worker_url, tunnel_url):
    put_kv_text(namespace_id, KV_KEY_CURRENT_URL, tunnel_url)
    state = {
        "updated_at": now_iso(),
        "tunnel_url": tunnel_url,
        "worker_url": worker_url,
        "kv_key": KV_KEY_CURRENT_URL,
    }
    save_state(state)
    save_link(worker_url)
    logging.info("Tunel publicado: %s -> %s", worker_url, tunnel_url)


def main():
    setup_logging()
    logging.info("Vigilante arrancando")
    namespace_id = None
    worker_url = ""

    try:
        namespace_id, worker_url = bootstrap_cloudflare()
    except Exception as exc:
        logging.exception("No se pudo preparar Cloudflare: %s", exc)

    last_state = load_state()
    last_url = (last_state.get("tunnel_url") or "").rstrip("/")

    while True:
        try:
            tunnel = latest_tunnel_url()
            if tunnel and tunnel != last_url:
                logging.info("Nueva URL de tunel detectada: %s", tunnel)
                last_url = tunnel
                if namespace_id and worker_url:
                    publish_tunnel(namespace_id, worker_url, tunnel)
                else:
                    save_state({"updated_at": now_iso(), "tunnel_url": tunnel, "worker_url": worker_url})
        except Exception as exc:
            logging.exception("Error vigilando/publicando tunel: %s", exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
