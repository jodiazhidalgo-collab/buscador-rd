from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_pack_selection_contract_{uuid.uuid4().hex}"
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


def no_video_pack_info():
    return {
        "id": "TID404",
        "status": "waiting_files_selection",
        "progress": 0,
        "links": [],
        "files": [
            rd_file("1", "/readme.txt", 0.001),
            rd_file("2", "/.pad/326511", 0.0003),
            rd_file("3", "/Enola.Holmes.3.(2026).nfo", 0.00002),
        ],
    }


def small_mp4_pack_info(status="waiting_files_selection", links=None):
    return {
        "id": "TIDPRESI",
        "status": status,
        "progress": 0 if status == "waiting_files_selection" else 100,
        "links": links or [],
        "files": [
            {
                "id": "1",
                "path": "/Torrente Presidente (DonTorrent).mp4",
                "bytes": int(22.49 * 1024 * 1024),
            },
        ],
    }


def mixed_noise_pack_info(status="waiting_files_selection", links=None):
    return {
        "id": "TIDMIXED",
        "status": status,
        "progress": 0 if status == "waiting_files_selection" else 100,
        "links": links or [],
        "files": [
            rd_file("1", "/Movie.Title.2026.1080p.mkv", 4.2),
            rd_file("2", "/Movie.Title.2026.sample.mkv", 0.03),
            rd_file("3", "/Subs/Movie.Title.2026.srt", 0.0001),
            rd_file("4", "/Proof/Movie.Title.2026.nfo", 0.0001),
            rd_file("5", "/Archives/Movie.Title.2026.part01.rar", 1.4),
            rd_file("6", "/readme.txt", 0.001),
        ],
    }


def test_video_ext_ok_uses_raw_suffix_not_normalized_text():
    motor = load_motor_module()

    assert motor.video_ext_ok("pelicula.mkv") is True
    assert motor.video_ext_ok("CARPETA/Pelicula.MKV") is True
    assert motor.video_ext_ok("/folder/video.mp4") is True
    assert motor.video_ext_ok("clip.m2ts") is True
    assert motor.video_ext_ok("open-movie.webm") is True
    assert motor.video_ext_ok("old-release.mpeg") is True
    assert motor.video_ext_ok("readme.txt") is False
    assert motor.video_ext_ok("pelicula.mkv.nfo") is False
    assert motor.video_ext_ok("/.pad/326511") is False


def test_rd_verify_by_addmagnet_selects_all_and_marks_ok(monkeypatch):
    motor = load_motor_module()
    calls = []
    events = []
    info_reads = 0

    wait_info = enola_pack_info()
    done_info = enola_pack_info(status="downloaded", links=["https://real-debrid.example/link"])

    def fake_rd_call(method, path, token, **kwargs):
        nonlocal info_reads
        calls.append((method, path, kwargs.get("data")))
        if method == "POST" and path == "/torrents/addMagnet":
            return {"id": "TID123"}
        if method == "GET" and path == "/torrents/info/TID123":
            info_reads += 1
            return wait_info if info_reads == 1 else done_info
        if method == "POST" and path == "/torrents/selectFiles/TID123":
            return {}
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
    assert checked.rd_status != "PACK_SIN_COINCIDENCIA"
    select_calls = [call for call in calls if call[1] == "/torrents/selectFiles/TID123"]
    assert select_calls == [("POST", "/torrents/selectFiles/TID123", {"files": "all"})]
    waiting_events = [payload for event, payload in events if event == "rd_waiting_files_selection"]
    assert len(waiting_events) == 1
    assert waiting_events[0]["files_total"] == 4
    assert waiting_events[0]["video_files"] == 1
    assert waiting_events[0]["files"][0]["kind"] == "video"
    assert waiting_events[0]["files"][0]["path"].endswith(".mkv")
    decision_events = [payload for event, payload in events if event == "rd_select_files_decision"]
    assert len(decision_events) == 1
    assert decision_events[0]["candidate_trace_id"].startswith("rd-001-")
    assert decision_events[0]["files"] == "all"
    assert decision_events[0]["selection_mode"] == "all"
    assert decision_events[0]["file_rows"][0]["path"].endswith(".mkv")
    assert any(event == "rd_verify_select_files" and payload["files"] == "all" for event, payload in events)
    assert any(event == "rd_verify_post_select_poll" and payload["candidate_trace_id"].startswith("rd-001-") for event, payload in events)
    assert any(event == "rd_verify_ok" and payload["candidate_trace_id"].startswith("rd-001-") for event, payload in events)
    assert not any(event == "rd_verify_pack_skip" for event, _payload in events)


def test_rd_verify_by_addmagnet_without_valid_video_selects_all_and_marks_ok(monkeypatch):
    motor = load_motor_module()
    calls = []
    events = []
    deleted = []
    info_reads = 0

    done_info = no_video_pack_info()
    done_info["status"] = "downloaded"
    done_info["progress"] = 100
    done_info["links"] = ["https://real-debrid.example/text-pack-link"]

    def fake_rd_call(method, path, token, **kwargs):
        nonlocal info_reads
        calls.append((method, path, kwargs.get("data")))
        if method == "POST" and path == "/torrents/addMagnet":
            return {"id": "TID404"}
        if method == "GET" and path == "/torrents/info/TID404":
            info_reads += 1
            return no_video_pack_info() if info_reads == 1 else done_info
        if method == "POST" and path == "/torrents/selectFiles/TID404":
            return {}
        raise AssertionError(f"unexpected RD call: {method} {path}")

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "record_rd_sent_magnet", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_find_existing_downloaded_by_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_call_with_retry", fake_rd_call)
    monkeypatch.setattr(motor, "rd_delete_torrent", lambda tid, token, why, release_slot=False: deleted.append((tid, why, release_slot)))
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    result = motor.Result(
        title="Enola.Holmes.3.(2026).nfo",
        magnet="magnet:?xt=urn:btih:" + "b" * 40,
        hash="b" * 40,
        size_gb=0.001,
    )

    checked = motor.rd_verify_by_addmagnet(result, "token", idx=1, total=1)

    assert checked.rd_status == "RD_OK"
    assert checked.selected_file_ids == "all"
    assert deleted == []
    select_calls = [call for call in calls if call[1] == "/torrents/selectFiles/TID404"]
    assert select_calls == [("POST", "/torrents/selectFiles/TID404", {"files": "all"})]
    assert any(event == "rd_select_files_decision" and payload["selection_mode"] == "all" for event, payload in events)
    assert not any(event == "rd_verify_pack_skip" for event, _payload in events)


def test_rd_verify_by_addmagnet_small_mp4_selects_all_instead_of_pack_skip(monkeypatch):
    motor = load_motor_module()
    calls = []
    events = []
    info_reads = 0

    wait_info = small_mp4_pack_info()
    done_info = small_mp4_pack_info(status="downloaded", links=["https://real-debrid.example/presi"])

    def fake_rd_call(method, path, token, **kwargs):
        nonlocal info_reads
        calls.append((method, path, kwargs.get("data")))
        if method == "POST" and path == "/torrents/addMagnet":
            return {"id": "TIDPRESI"}
        if method == "GET" and path == "/torrents/info/TIDPRESI":
            info_reads += 1
            return wait_info if info_reads == 1 else done_info
        if method == "POST" and path == "/torrents/selectFiles/TIDPRESI":
            return {}
        raise AssertionError(f"unexpected RD call: {method} {path}")

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "record_rd_sent_magnet", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_find_existing_downloaded_by_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_call_with_retry", fake_rd_call)
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    result = motor.Result(
        title="Torrente Presidente (DonTorrent)",
        magnet="magnet:?xt=urn:btih:a1ae72797bcf893ff3d5b4160d08e7016ed2a534",
        hash="a1ae72797bcf893ff3d5b4160d08e7016ed2a534",
        size_gb=0.022,
    )

    checked = motor.rd_verify_by_addmagnet(result, "token", idx=1, total=1)

    assert checked.rd_status == "RD_OK"
    assert checked.selected_file_ids == "all"
    select_calls = [call for call in calls if call[1] == "/torrents/selectFiles/TIDPRESI"]
    assert select_calls == [("POST", "/torrents/selectFiles/TIDPRESI", {"files": "all"})]
    waiting = [payload for event, payload in events if event == "rd_waiting_files_selection"]
    assert waiting[0]["files_total"] == 1
    assert waiting[0]["files"][0]["gb"] == 0.022
    assert not any(event == "rd_verify_pack_skip" for event, _payload in events)


def test_rd_verify_by_addmagnet_mixed_noise_pack_selects_everything(monkeypatch):
    motor = load_motor_module()
    calls = []
    events = []
    info_reads = 0

    wait_info = mixed_noise_pack_info()
    done_info = mixed_noise_pack_info(status="downloaded", links=["https://real-debrid.example/mixed"])

    def fake_rd_call(method, path, token, **kwargs):
        nonlocal info_reads
        calls.append((method, path, kwargs.get("data")))
        if method == "POST" and path == "/torrents/addMagnet":
            return {"id": "TIDMIXED"}
        if method == "GET" and path == "/torrents/info/TIDMIXED":
            info_reads += 1
            return wait_info if info_reads == 1 else done_info
        if method == "POST" and path == "/torrents/selectFiles/TIDMIXED":
            return {}
        raise AssertionError(f"unexpected RD call: {method} {path}")

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "record_rd_sent_magnet", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_find_existing_downloaded_by_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_call_with_retry", fake_rd_call)
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    result = motor.Result(
        title="Movie Title 2026",
        magnet="magnet:?xt=urn:btih:" + "c" * 40,
        hash="c" * 40,
        size_gb=5.6,
    )

    checked = motor.rd_verify_by_addmagnet(result, "token", idx=2, total=3)

    assert checked.rd_status == "RD_OK"
    assert checked.selected_file_ids == "all"
    assert ("POST", "/torrents/selectFiles/TIDMIXED", {"files": "all"}) in calls
    decision = [payload for event, payload in events if event == "rd_select_files_decision"][0]
    assert decision["selection_mode"] == "all"
    paths = {row["path"] for row in decision["file_rows"]}
    assert "/Movie.Title.2026.1080p.mkv" in paths
    assert "/Movie.Title.2026.sample.mkv" in paths
    assert "/Archives/Movie.Title.2026.part01.rar" in paths
    assert "/readme.txt" in paths
    assert not any(event == "rd_verify_pack_skip" for event, _payload in events)


def test_rd_torrent_id_to_downloads_selects_all_when_rd_waits_for_files(monkeypatch):
    motor = load_motor_module()
    calls = []
    events = []
    info_reads = 0
    wait_info = small_mp4_pack_info()
    done_info = small_mp4_pack_info(status="downloaded", links=["https://real-debrid.example/host-link"])

    def fake_rd_api(method, path, token, **kwargs):
        nonlocal info_reads
        calls.append((method, path, kwargs.get("data")))
        if method == "GET" and path == "/torrents/info/TIDDL":
            info_reads += 1
            return wait_info if info_reads <= 2 else done_info
        if method == "POST" and path == "/torrents/selectFiles/TIDDL":
            return {}
        if method == "POST" and path == "/unrestrict/link":
            return {"download": "https://real-debrid.example/download"}
        raise AssertionError(f"unexpected RD call: {method} {path}")

    monkeypatch.setattr(motor, "rd_api", fake_rd_api)
    monkeypatch.setattr(motor, "sleep_interruptible", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    downloads = motor.rd_torrent_id_to_downloads("TIDDL", "token", wanted_title="Torrente Presidente")

    assert downloads == ["https://real-debrid.example/download"]
    select_calls = [call for call in calls if call[1] == "/torrents/selectFiles/TIDDL"]
    assert select_calls == [("POST", "/torrents/selectFiles/TIDDL", {"files": "all"})]
    assert any(event == "rd_waiting_files_selection" and payload["files_total"] == 1 for event, payload in events)
    decision = [payload for event, payload in events if event == "rd_select_files_decision"][0]
    assert decision["files"] == "all"
    assert decision["selection_mode"] == "all"
    assert decision["file_rows"][0]["path"] == "/Torrente Presidente (DonTorrent).mp4"
    assert any(event == "rd_verify_select_files" and payload["requested_files"] == "all" for event, payload in events)


def test_rd_verify_by_addmagnet_records_blocked_before_file_selection(monkeypatch):
    motor = load_motor_module()
    events = []

    def fake_rd_call(method, path, token, **kwargs):
        if method == "POST" and path == "/torrents/addMagnet":
            raise motor.RDAPIError(
                method,
                path,
                451,
                '{"error":"infringing_file","error_code":35}',
                {"error": "infringing_file", "error_code": 35},
            )
        raise AssertionError(f"unexpected RD call: {method} {path}")

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "record_rd_sent_magnet", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_find_existing_downloaded_by_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "rd_call_with_retry", fake_rd_call)
    monkeypatch.setattr(motor, "diag", lambda event, **kwargs: events.append((event, kwargs)))

    result = motor.Result(
        title="www.UIndex.org - Pillion 2025 1080p WEB EN-RGB",
        magnet="magnet:?xt=urn:btih:" + "e" * 40,
        hash="e" * 40,
        size_gb=6.15,
    )

    checked = motor.rd_verify_by_addmagnet(result, "token", idx=6, total=9)

    assert checked.rd_status == "RD_FAIL"
    blocked = [payload for event, payload in events if event == "rd_candidate_addmagnet_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["stage"] == "addMagnet"
    assert blocked[0]["code"] == 451
    assert blocked[0]["error_code"] == 35
    assert blocked[0]["hash"] == "e" * 40
    assert blocked[0]["candidate_trace_id"].startswith("rd-006-")
    assert not any(event == "rd_waiting_files_selection" for event, _payload in events)
