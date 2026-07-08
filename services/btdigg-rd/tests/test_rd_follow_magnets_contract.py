from __future__ import annotations

import importlib
import importlib.util
import json
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOTOR_FILE = PROJECT_ROOT / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_magnets_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_motor_records_sent_rd_magnet_in_sidecar(monkeypatch, tmp_path):
    motor = load_motor_module()
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("BTDIGG_BLACKBOX_EVENTS", str(events_file))
    result = motor.Result(
        title="Pelicula de prueba",
        magnet="magnet:?xt=urn:btih:" + ("a" * 40),
        hash="a" * 40,
        size_gb=12.5,
    )

    motor.record_rd_sent_magnet(result, idx=2, total=7)

    sidecar = tmp_path / "rd_magnets_live.jsonl"
    rows = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["event"] == "rd_magnet_sent"
    assert rows[0]["title"] == "Pelicula de prueba"
    assert rows[0]["magnet"].startswith("magnet:?xt=urn:btih:")
    assert not events_file.exists()


def test_rd_follow_exposes_magnets_separate_from_process_lines(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules("api.btdigg_rd.rd_follow")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")
    rd_follow = importlib.import_module("api.btdigg_rd.rd_follow")
    job_id = "job-magnets"

    blackbox.start_job(job_id, "search", {"query": "Pelicula"})
    folder = blackbox.trace_folder("job", job_id)
    (folder / "rd_magnets_live.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "event": "rd_magnet_sent",
                "n": 1,
                "total": 3,
                "title": "Pelicula 2160p",
                "hash": "b" * 40,
                "magnet": "magnet:?xt=urn:btih:" + ("b" * 40),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    follow = rd_follow.build_rd_follow(job_id)

    assert follow["magnets"][0]["title"] == "Pelicula 2160p"
    assert follow["magnets"][0]["magnet"].startswith("magnet:?xt=urn:btih:")
    assert all("magnet:?xt=" not in str(line.get("text", "")) for line in follow["lines"])


def test_rd_follow_can_omit_magnets_for_exports(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules("api.btdigg_rd.rd_follow")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")
    rd_follow = importlib.import_module("api.btdigg_rd.rd_follow")
    job_id = "job-no-export-magnets"

    blackbox.start_job(job_id, "search", {"query": "Pelicula"})
    folder = blackbox.trace_folder("job", job_id)
    (folder / "rd_magnets_live.jsonl").write_text(
        json.dumps({"title": "Privado", "magnet": "magnet:?xt=urn:btih:" + ("c" * 40)}) + "\n",
        encoding="utf-8",
    )

    follow = rd_follow.build_rd_follow(job_id, include_magnets=False)

    assert follow["magnets"] == []


def test_rd_follow_explains_file_selection_without_marking_fail_as_ok(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules("api.btdigg_rd.rd_follow")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")
    rd_follow = importlib.import_module("api.btdigg_rd.rd_follow")
    job_id = "job-rd-selection"

    blackbox.start_job(job_id, "search", {"query": "Pillion"})
    blackbox.job_event(
        job_id,
        "rd_waiting_files_selection",
        n=1,
        total=2,
        title="Pillion 2025 1080p WEB EN-RGB",
        files_total=3,
        video_files=1,
        files_omitted=0,
        files=[
            {
                "id": "1",
                "path": "/Pillion 2025 1080p WEB EN-RGB.mkv",
                "gb": 6.15,
                "kind": "video",
                "video": True,
            }
        ],
    )
    blackbox.job_event(
        job_id,
        "rd_select_files_decision",
        n=1,
        total=2,
        title="Pillion 2025 1080p WEB EN-RGB",
        files="1",
        file_name="/Pillion 2025 1080p WEB EN-RGB.mkv",
        file_size_gb=6.15,
    )
    blackbox.job_event(job_id, "rd_verify_queue_done_item", done=1, total=2, status="RD_FAIL")

    follow = rd_follow.build_rd_follow(job_id)
    texts = [line["text"] for line in follow["lines"]]

    assert any("pide elegir archivo" in text for text in texts)
    assert any("archivo elegido" in text for text in texts)
    fail_lines = [text for text in texts if "RD: 1/2" in text]
    assert fail_lines == ["RD: 1/2 aviso | RD_FAIL."]
    assert "OK" not in fail_lines[0]
    assert follow["summary"]["file_selection"]["waiting_files_selection"] == 1
    assert follow["summary"]["file_selection"]["select_files_decision"] == 1


def test_rd_follow_links_blocked_addmagnet_to_candidate(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules("api.btdigg_rd.rd_follow")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")
    rd_follow = importlib.import_module("api.btdigg_rd.rd_follow")
    job_id = "job-rd-blocked"

    blackbox.start_job(job_id, "search", {"query": "Pillion"})
    blackbox.job_event(
        job_id,
        "rd_candidate_addmagnet_blocked",
        candidate_trace_id="rd-006-e9e8e653d1ab",
        n=6,
        total=9,
        title="www.UIndex.org - Pillion 2025 1080p WEB EN-RGB",
        hash="e9e8e653d1abb30bb7d95dcfeea41304dbd661be",
        stage="addMagnet",
        code=451,
        error_code=35,
        error="infringing_file",
    )

    follow = rd_follow.build_rd_follow(job_id)
    texts = [line["text"] for line in follow["lines"]]

    assert any("bloqueó el magnet antes de elegir archivo" in text for text in texts)
    assert follow["summary"]["file_selection"]["blocked_before_selection"] == 1
