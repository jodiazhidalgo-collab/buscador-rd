from __future__ import annotations

import json


def _patch_motor_config(tmp_path, monkeypatch):
    from api.btdigg_rd import classification, routes

    motor_dir = tmp_path / "motor" / "btdigg"
    motor_dir.mkdir(parents=True)
    (motor_dir / "config.json").write_text(
        json.dumps(
            {
                "default_mode": 0,
                "default_pages": "1",
                "qbit_probe_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes, "BTDIGG_DIR", motor_dir)
    monkeypatch.setattr(classification, "BTDIGG_DIR", motor_dir)
    return motor_dir


def test_settings_get_post_contract(client, tmp_path, monkeypatch):
    motor_dir = _patch_motor_config(tmp_path, monkeypatch)

    get_response = client.get("/api/settings")
    assert get_response.status_code == 200
    get_payload = get_response.get_json()
    assert get_payload["ok"] is True
    fields = get_payload["settings"]["btdigg"]["fields"]
    assert any(field["key"] == "default_pages" for field in fields)

    bad_response = client.post("/api/settings", json={"module": "otro", "values": {}})
    assert bad_response.status_code == 400
    assert bad_response.get_json()["ok"] is False

    post_response = client.post(
        "/api/settings",
        json={"module": "btdigg", "values": {"default_pages": "2", "hide_non_working_results": True}},
    )
    assert post_response.status_code == 200
    post_payload = post_response.get_json()
    assert post_payload["ok"] is True
    assert "default_pages" in post_payload["changed"]
    assert post_payload["message"] == "Ajustes guardados"

    saved = json.loads((motor_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["default_pages"] == "2"
    assert saved["hide_non_working_results"] is True
    assert saved["verify_wait_attempts"] == 1


def test_qbit_toggle_contract(client, tmp_path, monkeypatch):
    motor_dir = _patch_motor_config(tmp_path, monkeypatch)

    get_response = client.get("/api/qbit-toggle")
    assert get_response.status_code == 200
    assert get_response.get_json() == {"ok": True, "enabled": True}

    post_response = client.post("/api/qbit-toggle", json={"enabled": False})
    assert post_response.status_code == 200
    assert post_response.get_json() == {"ok": True, "enabled": False, "changed": True}

    saved = json.loads((motor_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["qbit_probe_enabled"] is False


def test_tv_rules_contract(client, tmp_path, monkeypatch):
    motor_dir = _patch_motor_config(tmp_path, monkeypatch)

    get_response = client.get("/api/tv-rules")
    assert get_response.status_code == 200
    get_payload = get_response.get_json()
    assert get_payload["ok"] is True
    assert "rules" in get_payload
    assert "defaults" in get_payload

    new_rules = {"series_templates": ["SXXEXX"], "series_words": ["capitulo"]}
    post_response = client.post("/api/tv-rules", json={"rules": new_rules})
    assert post_response.status_code == 200
    post_payload = post_response.get_json()
    assert post_payload["ok"] is True
    assert post_payload["rules"] == new_rules
    assert post_payload["message"] == "Reglas guardadas"

    classify_response = client.post("/api/tv-rules/classify", json={"title": "Serie S01E02", "rules": new_rules})
    assert classify_response.status_code == 200
    classify_payload = classify_response.get_json()
    assert classify_payload["ok"] is True
    assert classify_payload["destination"] == "tv"
    assert classify_payload["matched_type"] == "template"

    saved = json.loads((motor_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["tv_series_templates"] == ["SXXEXX"]
    assert saved["tv_series_words"] == ["capitulo"]
