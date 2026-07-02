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
