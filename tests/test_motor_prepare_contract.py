from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path


MOTOR_FILE = Path(__file__).resolve().parents[1] / "app" / "motor" / "btdigg" / "rd_turbo_pro.py"


def load_motor_module():
    module_name = f"rd_turbo_pro_prepare_contract_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MOTOR_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result(motor, title, score=0, size_gb=2.0):
    return motor.Result(
        title=title,
        magnet=f"magnet:?xt=urn:btih:{title[:1].lower() * 40}",
        hash=title[:1].lower() * 40,
        size_gb=size_gb,
    )


def test_mode_zero_score_is_flat_except_bad_words():
    motor = load_motor_module()

    clean = motor.score_result(motor.Result(title="Pelicula 2160p REMUX WEB-DL", size_gb=80), mode=0)
    trash = motor.score_result(motor.Result(title="Pelicula telecine 2160p REMUX", size_gb=80), mode=0)
    quality = motor.score_result(motor.Result(title="Pelicula 2160p REMUX WEB-DL", size_gb=80), mode=1)

    assert clean.score == 0
    assert clean.reason == "sin marcas relevantes"
    assert trash.score == -70
    assert "-telecine" in trash.reason
    assert quality.score > 0


def test_mode_zero_does_not_add_quality_rescue_query():
    motor = load_motor_module()
    original_config = dict(motor.CONFIG)
    try:
        motor.CONFIG["quality_mode_extra_btdigg_enabled"] = True
        motor.CONFIG["quality_mode_extra_btdigg_terms"] = ["2160p"]

        assert motor._quality_mode_extra_btdigg_queries("Venganza 2008", mode=0) == []
        assert motor._quality_mode_extra_btdigg_queries("Venganza 2008", mode=1) == ["Venganza 2008 2160p"]
    finally:
        motor.CONFIG.clear()
        motor.CONFIG.update(original_config)


def test_prepare_results_mode_zero_does_not_use_size_as_tie_breaker(monkeypatch):
    motor = load_motor_module()
    calls = {"rd_order": [], "shown": []}
    small = result(motor, "small-neutral", size_gb=1.0)
    huge = result(motor, "huge-neutral", size_gb=80.0)
    trash = result(motor, "trash-cam", size_gb=100.0)
    scores = {"small-neutral": 0, "huge-neutral": 0, "trash-cam": -70}

    def fake_score(r, mode):
        r.score = scores[r.title]
        return r

    def fake_rd_check(rows, token):
        calls["rd_order"] = [r.title for r in rows]
        for r in rows:
            r.rd_status = "NO_CACHE"
        return rows

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "score_result", fake_score)
    monkeypatch.setattr(motor, "_query_relevance_bucket", lambda r: "primary")
    monkeypatch.setattr(motor, "_apply_current_min_size_filter", lambda rows, stage: (list(rows), []))
    monkeypatch.setattr(motor, "rd_check_availability", fake_rd_check)
    monkeypatch.setattr(motor, "qbt_probe_candidates", lambda rows: rows)
    monkeypatch.setattr(motor, "export_results", lambda all_rows, shown: calls.__setitem__("shown", [r.title for r in shown]))
    motor.CONFIG["strict_query_prefilter"] = True
    motor.CONFIG["rd_rescue_enabled"] = False
    motor.CONFIG["hide_non_working_results"] = False

    shown = motor.prepare_results([small, huge, trash], mode=0, token="")

    assert calls["rd_order"] == ["small-neutral", "huge-neutral", "trash-cam"]
    assert [r.title for r in shown] == ["small-neutral", "huge-neutral", "trash-cam"]
    assert calls["shown"] == ["small-neutral", "huge-neutral", "trash-cam"]


def test_prepare_results_scores_filters_sorts_qbit_extras_and_exports(monkeypatch):
    motor = load_motor_module()
    scores = {"best": 90, "good": 50, "bad": -600}
    calls = {"rd_order": [], "export": None, "size_stages": []}
    items = [result(motor, "good"), result(motor, "bad"), result(motor, "best")]

    def fake_score(r, mode):
        r.score = scores[r.title]
        return r

    def fake_size_filter(rows, stage):
        calls["size_stages"].append(stage)
        return list(rows), []

    def fake_rd_check(rows, token):
        calls["rd_order"] = [r.title for r in rows]
        for r in rows:
            r.rd_status = "RD_OK" if r.title == "best" else "NO_CACHE"
        return rows

    def fake_qbt(rows):
        for r in rows:
            if r.title == "good":
                r.qbt_status = "QBT_VIVO"
                r.qbt_reason = "qbit vivo"
        return rows

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "score_result", fake_score)
    monkeypatch.setattr(motor, "_query_relevance_bucket", lambda r: "primary")
    monkeypatch.setattr(motor, "_apply_current_min_size_filter", fake_size_filter)
    monkeypatch.setattr(motor, "rd_check_availability", fake_rd_check)
    monkeypatch.setattr(motor, "qbt_probe_candidates", fake_qbt)
    monkeypatch.setattr(motor, "export_results", lambda all_rows, shown: calls.__setitem__("export", ([r.title for r in all_rows], [r.title for r in shown])))
    motor.CONFIG["strict_query_prefilter"] = True
    motor.CONFIG["hide_non_working_results"] = True
    motor.CONFIG["rd_rescue_enabled"] = False

    shown = motor.prepare_results(items, mode=1, token="token")

    assert calls["rd_order"] == ["best", "good"]
    assert "bad" not in calls["rd_order"]
    assert calls["size_stages"] == ["before_rd", "after_rd"]
    assert [r.title for r in shown] == ["best", "good"]
    assert [r.title for r in motor.LAST_QBIT_EXTRAS] == ["good"]
    assert calls["export"][1] == ["best", "good"]


def test_prepare_results_applies_size_filter_before_and_after_rd(monkeypatch):
    motor = load_motor_module()
    keep = result(motor, "keep")
    small_before = result(motor, "small-before")
    small_after = result(motor, "small-after")
    small_after.rd_torrent_id = "tid-small"
    rows = [keep, small_before, small_after]
    calls = {"rd_seen": [], "deleted": [], "export_all": []}

    def fake_score(r, mode):
        r.score = {"keep": 80, "small-before": 70, "small-after": 60}[r.title]
        return r

    def fake_size_filter(items, stage):
        if stage == "before_rd":
            return [r for r in items if r.title != "small-before"], [r for r in items if r.title == "small-before"]
        if stage == "after_rd":
            return [r for r in items if r.title != "small-after"], [r for r in items if r.title == "small-after"]
        return list(items), []

    def fake_rd_check(items, token):
        calls["rd_seen"] = [r.title for r in items]
        for r in items:
            r.rd_status = "RD_OK"
        return items

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "score_result", fake_score)
    monkeypatch.setattr(motor, "_query_relevance_bucket", lambda r: "primary")
    monkeypatch.setattr(motor, "_apply_current_min_size_filter", fake_size_filter)
    monkeypatch.setattr(motor, "rd_check_availability", fake_rd_check)
    monkeypatch.setattr(motor, "rd_delete_torrent", lambda tid, token, why: calls["deleted"].append((tid, why)))
    monkeypatch.setattr(motor, "qbt_probe_candidates", lambda items: items)
    monkeypatch.setattr(motor, "export_results", lambda all_rows, shown: calls.__setitem__("export_all", [r.title for r in all_rows]))
    motor.CONFIG["strict_query_prefilter"] = True
    motor.CONFIG["rd_rescue_enabled"] = False
    motor.CONFIG["cleanup_failed_verifications"] = True
    motor.CONFIG["hide_non_working_results"] = True

    shown = motor.prepare_results(rows, mode=1, token="token")

    assert calls["rd_seen"] == ["keep", "small-after"]
    assert calls["deleted"] == [("tid-small", "descartado_por_tamano")]
    assert [r.title for r in shown] == ["keep"]
    assert calls["export_all"] == ["keep", "small-before", "small-after"]


def test_prepare_results_rescues_query_candidates_when_no_rd_ok(monkeypatch):
    motor = load_motor_module()
    primary = result(motor, "primary")
    rescue = result(motor, "rescue")
    discard = result(motor, "discard")
    rd_batches = []

    def fake_score(r, mode):
        r.score = {"primary": 90, "rescue": 80, "discard": 70}[r.title]
        return r

    def fake_bucket(r):
        return {"primary": "primary", "rescue": "rescue", "discard": "discard"}[r.title]

    def fake_rd_check(items, token):
        rd_batches.append([r.title for r in items])
        for r in items:
            r.rd_status = "RD_OK" if r.title == "rescue" else "NO_CACHE"
        return items

    monkeypatch.setattr(motor, "cancel_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "diag", lambda *args, **kwargs: None)
    monkeypatch.setattr(motor, "score_result", fake_score)
    monkeypatch.setattr(motor, "_query_relevance_bucket", fake_bucket)
    monkeypatch.setattr(motor, "_apply_current_min_size_filter", lambda rows, stage: (list(rows), []))
    monkeypatch.setattr(motor, "rd_check_availability", fake_rd_check)
    monkeypatch.setattr(motor, "qbt_probe_candidates", lambda items: items)
    monkeypatch.setattr(motor, "export_results", lambda *args, **kwargs: None)
    motor.CONFIG["strict_query_prefilter"] = True
    motor.CONFIG["strict_query_prefilter_keep_discarded_in_exports"] = True
    motor.CONFIG["rd_rescue_enabled"] = True
    motor.CONFIG["rd_rescue_only_if_no_rd_ok"] = True
    motor.CONFIG["rd_rescue_max_candidates"] = 5
    motor.CONFIG["hide_non_working_results"] = True

    shown = motor.prepare_results([discard, rescue, primary], mode=1, token="token")

    assert rd_batches == [["primary"], ["rescue"]]
    assert [r.title for r in shown] == ["rescue"]
    assert discard.rd_status == "SIN_COMPROBAR"
