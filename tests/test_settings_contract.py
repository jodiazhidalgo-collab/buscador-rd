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
                "tmdb_api_token": "keep-me",
                "verify_wait_attempts": 1,
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
    assert len(fields) == 29
    assert all(field.get("value") is not None for field in fields)
    assert all("default" in field for field in fields)
    assert any(field["key"] == "default_pages" for field in fields)
    labels_by_key = {field["key"]: field["label"] for field in fields}
    assert labels_by_key["default_pages"] == "Páginas BTDigg"
    assert labels_by_key["min_size_gb"] == "Tamaño mínimo GB"

    bad_response = client.post("/api/settings", json={"module": "otro", "values": {}})
    assert bad_response.status_code == 400
    bad_payload = bad_response.get_json()
    assert bad_payload["ok"] is False
    assert bad_payload["error"] == "módulo no válido"

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
    assert saved["tmdb_api_token"] == "keep-me"
    assert saved["qbit_probe_enabled"] is True


def test_settings_trimmed_config_returns_effective_values_and_defaults(client, tmp_path, monkeypatch):
    motor_dir = _patch_motor_config(tmp_path, monkeypatch)
    (motor_dir / "config.json").write_text(
        json.dumps({"tmdb_api_token": "secret", "qbit_probe_enabled": False, "verify_wait_attempts": 1}),
        encoding="utf-8",
    )

    response = client.get("/api/settings")

    assert response.status_code == 200
    fields = response.get_json()["settings"]["btdigg"]["fields"]
    by_key = {field["key"]: field for field in fields}
    assert len(fields) == 29
    assert all(field["value"] is not None for field in fields)
    assert all("default" in field for field in fields)
    assert by_key["default_pages"]["value"] == "1-3"
    assert by_key["default_pages"]["default"] == "1-3"
    assert by_key["max_results_to_show"]["value"] == 80
    assert by_key["verify_wait_sec"]["value"] == 0.25


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
    assert get_payload["rules"]["series_templates"]
    assert get_payload["rules"]["series_words"]

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


def test_runtime_config_repair_persists_backup_tv_rules(tmp_path):
    from api.btdigg_rd._runtime_config_service import repair_runtime_config_if_missing

    config_path = tmp_path / "config.json"
    backup_path = tmp_path / "backup-config.json"
    config_path.write_text(
        json.dumps({"tmdb_api_token": "secret", "qbit_probe_enabled": True, "verify_wait_attempts": 1}),
        encoding="utf-8",
    )
    backup_path.write_text(
        json.dumps(
            {
                "default_pages": "9",
                "tv_series_templates": ["CUSTOMXX"],
                "tv_series_words": ["customword"],
            }
        ),
        encoding="utf-8",
    )

    repaired = repair_runtime_config_if_missing(config_path, backup_candidate_path=backup_path)
    persisted = json.loads(config_path.read_text(encoding="utf-8"))

    assert repaired["default_pages"] == "9"
    assert repaired["qbit_probe_enabled"] is True
    assert repaired["verify_wait_attempts"] == 1
    assert repaired["tmdb_api_token"] == "secret"
    assert persisted["tv_series_templates"] == ["CUSTOMXX"]
    assert persisted["tv_series_words"] == ["customword"]
