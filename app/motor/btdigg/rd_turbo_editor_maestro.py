#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Editor Maestro Plex - BTDigg + RD opción 1 limpia.

Este archivo es el puente limpio para el Editor Maestro.
No muestra el menú viejo 1-7. Solo hace:
  --search  buscar en BTDigg/RD/qBit y guardar resultados mostrados
  --send    enviar selección 1, 1,3, A, T o S a JDownloader/RD

No toca config.json ni rd_token.txt.
"""
import argparse
from urllib import request as urlrequest, parse as urlparse, error as urlerror
import importlib.util
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ENGINE_FILE_DEFAULT = APP_DIR / "rd_turbo_pro.py"
SHOWN_FILE = Path(os.environ.get("EDITOR_MAESTRO_SHOWN_FILE", str(APP_DIR / "exports" / "EDITOR_MAESTRO_SHOWN.json")))
SAFEOUT_FILE = Path(os.environ.get("EDITOR_MAESTRO_SAFEOUT", str(Path(tempfile.gettempdir()) / "btdigg_rd_safeout.log")))

ORDERED_LINKS_FILE = Path(os.environ.get("EDITOR_MAESTRO_ORDERED_LINKS_FILE", str(APP_DIR / "last_links_ordenado.txt")))


def _clean_one_line(value):
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return " ".join(text.split()).strip()


def _display_name_for_result(r):
    for attr in ("selected_file_name", "btdigg_file_name", "title"):
        value = _clean_one_line(getattr(r, attr, ""))
        if value:
            return value
    return "Resultado sin nombre"


def _magnet_for_record(r):
    for attr in ("magnet", "torrent_url", "source_url"):
        value = str(getattr(r, attr, "") or "").strip()
        if value:
            return value
    return ""


def write_ordered_links(selected, downloads):
    """Archivo bonito para el botón Links qB. No toca el last_links.txt plano que usa JDownloader."""
    try:
        ORDERED_LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        selected = list(selected or [])
        downloads = [str(x).strip() for x in (downloads or []) if str(x).strip()]
        lines = []
        if not downloads:
            ORDERED_LINKS_FILE.write_text("No hay enlaces generados.\n", encoding="utf-8")
            return
        for i, link in enumerate(downloads, 1):
            if selected:
                if len(selected) == 1:
                    name = _display_name_for_result(selected[0])
                elif i <= len(selected):
                    name = _display_name_for_result(selected[i - 1])
                else:
                    name = _display_name_for_result(selected[-1])
            else:
                name = f"Enlace {i:02d}"
            lines.append(f"[{i:02d}] {name}")
            lines.append(link)
            lines.append("")
        ORDERED_LINKS_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print(f"Enlaces ordenados guardados en: {ORDERED_LINKS_FILE}")
    except Exception as e:
        print(f"Aviso: no pude crear last_links_ordenado.txt: {e}")



class _SafeStream:
    """Salida 100% a archivo para que el Editor no dependa del stdout de Windows."""
    def __init__(self, base=None, name="stdout"):
        self.base = base
        self.name = name
        self.encoding = "utf-8"
        self.errors = "replace"
        try:
            SAFEOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def write(self, data):
        if data is None:
            return 0
        text = str(data)
        try:
            with SAFEOUT_FILE.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(text)
                fh.flush()
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            with SAFEOUT_FILE.open("a", encoding="utf-8", errors="replace") as fh:
                fh.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def reconfigure(self, *args, **kwargs):
        return None


def _setup_console():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # Fix 18: nada se imprime al stdout real. Todo va a SAFEOUT.
    sys.stdout = _SafeStream(None, "stdout")
    sys.stderr = _SafeStream(None, "stderr")


def load_engine(engine_path: str):
    path = Path(engine_path or ENGINE_FILE_DEFAULT).resolve()
    if not path.exists():
        raise FileNotFoundError(f"No encuentro motor base: {path}")
    spec = importlib.util.spec_from_file_location("rd_turbo_pro_base", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rd_turbo_pro_base"] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_min_gb(engine, raw: str) -> float:
    try:
        return float(engine._parse_gb_input(raw))
    except Exception:
        try:
            return max(0.0, float(str(raw or "").replace(",", ".")))
        except Exception:
            return 0.0


def save_shown(results):
    SHOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in results or []:
        try:
            rows.append(dict(r.__dict__))
        except Exception:
            pass
    SHOWN_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resultados guardados para el Editor: {len(rows)}")


def load_shown(engine):
    if not SHOWN_FILE.exists():
        print("No hay resultados guardados. Haz una búsqueda primero.")
        return []
    rows = json.loads(SHOWN_FILE.read_text(encoding="utf-8"))
    fields = set(engine.Result.__dataclass_fields__.keys())
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kwargs = {k: row.get(k) for k in fields if k in row}
        try:
            out.append(engine.Result(**kwargs))
        except Exception:
            pass
    return out


def select_from_choice(engine, shown, choice: str):
    choice = (choice or "").strip().lower()
    if not shown or choice in ("", "s", "salir", "0"):
        return []
    if choice in ("a", "instant", "instantaneos", "validos", "valid"):
        valid = [r for r in shown if engine._is_working_status(r.rd_status)]
        if not valid:
            print("No hay resultados válidos RD en el TOP mostrado. Elige números concretos o T.")
        return valid
    if choice in ("t", "todos", "all"):
        return shown[:]
    selected = []
    import re
    for part in re.split(r"[,;\s]+", choice):
        if part and part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(shown):
                selected.append(shown[idx - 1])
    out, seen = [], set()
    for r in selected:
        key = r.hash or r.magnet or r.torrent_url or r.source_url
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def do_search(engine, args):
    token = engine.read_token()
    query = (args.query or "").strip()
    pages = (args.pages or str(engine.CONFIG.get("default_pages", "1-5"))).strip()
    try:
        raw_mode = int(float(str(args.mode or 0).strip() or 0))
    except Exception:
        raw_mode = 0
    mode = engine.coerce_mode(raw_mode) if hasattr(engine, "coerce_mode") else raw_mode
    min_gb = parse_min_gb(engine, args.min_gb)

    if not query:
        print("ERROR: búsqueda vacía.")
        save_shown([])
        return 2

    engine.CURRENT_QUERY = query
    engine.CURRENT_MIN_SIZE_GB = min_gb

    print("BTDigg + RD - opción 1 limpia")
    print(f"Búsqueda: {query}")
    print(f"Páginas: {pages}")
    print(f"Modo: {mode}")
    if min_gb > 0:
        print(f"GB mínimo: {min_gb:g}")
    print("")

    engine.diag("editor_clean_search_start", query=query, pages=pages, mode=mode, min_gb=min_gb)
    engine.cancel_checkpoint("editor.before_search")
    results = engine.search_btdigg_browser_auto_quality_aware(query, pages, mode)
    engine.cancel_checkpoint("editor.after_search")
    print(f"\nEncontrados {len(results)} resultados brutos. Filtrando...")
    prepared = engine.prepare_results(results, mode, token)
    engine.cancel_checkpoint("editor.after_prepare")
    shown = engine.display_results(prepared)
    engine.cancel_checkpoint("editor.before_save_shown")
    save_shown(shown)
    try:
        temp_ids = [str(getattr(r, "rd_torrent_id", "") or "").strip() for r in shown if str(getattr(r, "rd_torrent_id", "") or "").strip() and not getattr(r, "rd_existing", False)]
        with engine.non_cancelable_cleanup():
            engine.cleanup_unselected_verified(shown, [], token)
        print(f"Real-Debrid temporal limpio: {len(temp_ids)} id(s) revisado(s).")
        engine.diag("editor_clean_search_rd_cleanup", temp_ids=len(temp_ids))
    except Exception as e:
        print(f"AVISO: no pude limpiar temporales RD: {e!r}")
        try:
            engine.diag("editor_clean_search_rd_cleanup_error", error=repr(e))
        except Exception:
            pass
    print("\nRESULTADOS LISTOS. Escribe abajo 1, 1,3, A, T o S y pulsa Enviar.")
    engine.diag("editor_clean_search_end", shown=len(shown))
    return 0



def send_selected_to_rdt_client(selected):
    """
    Envía los magnets seleccionados a RDT-Client usando API compatible qBittorrent.
    No toca búsqueda, filtros ni Real-Debrid.
    """
    magnets = []
    for r in selected:
        try:
            m = _magnet_for_record(r)
        except Exception:
            m = ""
        m = str(m or "").strip()
        if m.startswith("magnet:"):
            magnets.append(m)

    magnets = list(dict.fromkeys(magnets))

    if not magnets:
        print("RDT-Client: no hay magnets para enviar.")
        return False

    api_url = "http://rdtclient:6500/api/v2/torrents/add"
    data = urlparse.urlencode({
        "urls": "\n".join(magnets),
        "category": "movies",
        "paused": "false",
        "stopped": "false",
        "contentLayout": "Original",
    }).encode("utf-8")

    req = urlrequest.Request(
        api_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace").strip()
            print(f"RDT-Client: enviado OK ({len(magnets)} magnet/s).")
            if body:
                print(f"RDT-Client respuesta: {body[:200]}")
            return True
    except urlerror.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"RDT-Client ERROR HTTP {e.code}: {body[:250]}")
        return False
    except Exception as e:
        print(f"RDT-Client ERROR: {e}")
        return False


def do_send(engine, args):
    token = engine.read_token()
    choice = (args.choice or "").strip()
    print(f"Selección recibida: {choice or '(vacía)'}")
    shown = load_shown(engine)
    selected = select_from_choice(engine, shown, choice)
    if not selected:
        try:
            engine.cleanup_unselected_verified(shown, [], token)
        except Exception:
            pass
        print("No se manda nada.")
        return 0
    try:
        engine.cleanup_unselected_verified(shown, selected, token)
    except Exception:
        pass
    print(f"Seleccionados: {len(selected)}")
    downloads = engine.convert_selected_to_download_links(selected, token)
    write_ordered_links(selected, downloads)

    print("Enviando a RDT-Client...")
    send_selected_to_rdt_client(selected)

    engine.deliver_to_jdownloader(downloads)
    print("\nENVÍO TERMINADO.")
    engine.diag("editor_clean_send_end", selected=len(selected), downloads=len(downloads))
    return 0


def main():
    _setup_console()
    try:
        SAFEOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with SAFEOUT_FILE.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write("\n--- ARRANQUE MOTOR BTDIGG RD ---\n")
    except Exception:
        pass
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--engine", default=str(ENGINE_FILE_DEFAULT))
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--query", default="")
    parser.add_argument("--pages", default="1-5")
    parser.add_argument("--mode", default="0")
    parser.add_argument("--min-gb", default="")
    parser.add_argument("--choice", default="")
    args = parser.parse_args()
    engine = load_engine(args.engine)
    try:
        if args.search:
            return do_search(engine, args)
        if args.send:
            return do_send(engine, args)
        print("Uso interno Editor Maestro: --search o --send")
        return 2
    except engine.UserCancelled as e:
        try:
            engine.diag("editor_clean_cancelled", reason=str(e))
        except Exception:
            pass
        print("\nCancelado por el usuario. Limpieza terminada.")
        return 130
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
        return 130
    except Exception as e:
        try:
            engine.diag("editor_clean_fatal", error=repr(e))
            engine.log(f"EDITOR CLEAN FATAL: {e}")
        except Exception:
            pass
        print(f"\nERROR FATAL EDITOR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
