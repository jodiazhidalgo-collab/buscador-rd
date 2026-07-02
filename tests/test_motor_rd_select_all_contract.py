from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_select_all_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rd_file(file_id, path, gb):
    return {
        "id": file_id,
        "path": path,
        "bytes": int(gb * (1024 ** 3)),
    }


def enola_pack_info(status="waiting_files_selection", links=None):
    return {
        "id": "TID123",
        "status": status,
        "progress": 0 if status == "waiting_files_selection" else 100,
        "links": links or [],
        "files": [
            rd_file("1", "/Enola.Holmes.3.(2026)[DUAL ESP-ENG][HDR10 HEVC][Bluray 1080p]-Mang0z4.mkv", 7.24),
            rd_file("2", "/.pad/326511", 0.0003),
            rd_file("3", "/.pad/1030012", 0.001),
            rd_file("4", "/Enola.Holmes.3.(2026)[DUAL ESP-ENG][HDR10 HEVC][Bluray 1080p]-Mang0z4.mkv.nfo", 0.00002),
        ],
    }


def test_video_ext_ok_uses_raw_suffix_not_normalized_text():
    motor = load_motor_module()

    assert motor.video_ext_ok("pelicula.mkv") is True
    assert motor.video_ext_ok("CARPETA/Pelicula.MKV") is True
    assert motor.video_ext_ok("/folder/video.mp4") is True
    assert motor.video_ext_ok("clip.m2ts") is True
    assert motor.video_ext_ok("readme.txt") is False
    assert motor.video_ext_ok("pelicula.mkv.nfo") is False
    assert motor.video_ext_ok("/.pad/326511") is False


def test_choose_internal_files_selects_all_and_records_blackbox(monkeypatch):
    motor = load_motor_module()
    events = []
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    ids, fname, fgb, note = motor.choose_internal_files(
        enola_pack_info(),
        wanted_title="Enola Holmes 3",
        wanted_terms=["enola", "holmes", "3"],
    )

    assert ids == "all"
    assert fname == "todos_los_archivos_rd"
    assert fgb > 7
    assert "seleccion_total_por_politica" in note
    file_list = [payload for event, payload in events if event == "rd_choose_file_list"][-1]
    assert file_list["policy"] == "select_all"
    assert file_list["files_total"] == 4
    assert file_list["files"][0]["is_video_ext"] is True
    assert file_list["files"][3]["is_video_ext"] is False


def test_rd_verify_by_addmagnet_uses_single_selectfiles_all_call(monkeypatch):
    motor = load_motor_module()
    calls = []
    events = []

    wait_info = enola_pack_info()
    done_info = enola_pack_info(status="downloaded", links=["https://real-debrid.example/link"])

    def fake_rd_call(method, path, token, **kwargs):
        calls.append((method, path, kwargs.get("data")))
        if method == "POST" and path == "/torrents/addMagnet":
            return {"id": "TID123"}
        if method == "GET" and path == "/torrents/info/TID123" and len([c for c in calls if c[1] == path]) == 1:
            return wait_info
        if method == "POST" and path == "/torrents/selectFiles/TID123":
            return {}
        if method == "GET" and path == "/torrents/info/TID123":
            return done_info
        raise AssertionError(f"unexpected RD call: {method} {path}")

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "record_rd_sent_magnet", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_find_existing_downloaded_by_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_call_with_retry", fake_rd_call)
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    result = motor.Result(
        title="Enola.Holmes.3.(2026)[DUAL ESP-ENG][HDR10 HEVC][Bluray 1080p]-Mang0z4",
        magnet="magnet:?xt=urn:btih:" + "a" * 40,
        hash="a" * 40,
        size_gb=7.24,
    )

    checked = motor.rd_verify_by_addmagnet(result, "token", idx=1, total=1)

    assert checked.rd_status == "RD_OK"
    assert checked.selected_file_ids == "all"
    select_calls = [call for call in calls if call[1] == "/torrents/selectFiles/TID123"]
    assert select_calls == [("POST", "/torrents/selectFiles/TID123", {"files": "all"})]
    assert any(event == "rd_select_all_files" for event, _payload in events)
    assert any(event == "rd_verify_select_files" and payload["files"] == "all" for event, payload in events)
    assert not any(event == "rd_verify_pack_skip" for event, _payload in events)
