from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import importlib.util
import json
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOTOR_FILE = PROJECT_ROOT / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_sequence_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _events(events_file: Path) -> list[dict]:
    return [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_blackbox_api_writes_linear_sequence_under_threads(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules("api.btdigg_rd.blackbox")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")
    trace_id = "seq-api-contract"

    def write_event(index: int) -> None:
        blackbox.job_event(trace_id, "SEQ_API_EVENT", index=index)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_event, range(40)))

    folder = blackbox.trace_folder("job", trace_id)
    rows = _events(folder / "events.jsonl")
    seqs = [row["seq"] for row in rows]

    assert seqs == list(range(1, len(rows) + 1))
    assert [row["event_id"] for row in rows] == [f"E{i:06d}" for i in seqs]
    assert (folder / "events.seq").read_text(encoding="utf-8").strip() == str(len(rows))


def test_blackbox_api_and_motor_share_linear_sequence(isolated_data_dir, reload_data_dir_modules, monkeypatch):
    reload_data_dir_modules("api.btdigg_rd.blackbox")
    blackbox = importlib.import_module("api.btdigg_rd.blackbox")
    motor = load_motor_module()
    trace_id = "seq-api-motor-contract"

    blackbox.start_job(trace_id, "search", {"query": "Pelicula"})
    folder = blackbox.trace_folder("job", trace_id)
    events_file = folder / "events.jsonl"
    monkeypatch.setenv("BTDIGG_BLACKBOX_EVENTS", str(events_file))
    monkeypatch.setenv("BTDIGG_BLACKBOX_KIND", "job")
    monkeypatch.setenv("BTDIGG_BLACKBOX_TRACE_ID", trace_id)
    monkeypatch.setenv("BTDIGG_BLACKBOX_JOB_ID", trace_id)

    def write_event(index: int) -> None:
        if index % 2:
            blackbox.job_event(trace_id, "SEQ_API_EVENT", index=index)
        else:
            motor._blackbox_diag("seq_motor_event", {"index": index})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_event, range(40)))

    rows = _events(events_file)
    seqs = [row["seq"] for row in rows]

    assert seqs == list(range(1, len(rows) + 1))
    assert len(seqs) == 42
    assert len(set(seqs)) == len(seqs)
    assert (folder / "events.seq").read_text(encoding="utf-8").strip() == str(len(rows))
