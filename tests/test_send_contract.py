from __future__ import annotations

import pytest


def test_api_rdt_send_missing_link_contract(client):
    response = client.post("/api/rdt/send", json={"module": "manual", "title": "Peli"})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "error" in payload
    assert "trace_id" in payload


def test_api_rdt_send_manual_magnet_fallback_to_qbit(client, monkeypatch):
    from api.btdigg_rd import send

    calls: dict[str, object] = {}
    magnet = "magnet:?xt=urn:btih:" + "a" * 40

    monkeypatch.setattr(send, "download_dest_from_title", lambda title, fallback="movies": "movies")
    monkeypatch.setattr(send, "rd_precheck_magnet", lambda link, title, trace_id="": {"ok": False, "reason": "sin token RD"})
    monkeypatch.setattr(send, "record_download", lambda *args, **kwargs: calls.setdefault("recorded", True))

    def fake_qbit_add_url(base, user, password, url, target, is_rdt=False, trace_id="", engine_label="qBittorrent"):
        calls["qbit"] = {
            "base": base,
            "url": url,
            "target": target,
            "is_rdt": is_rdt,
            "engine_label": engine_label,
        }
        return '{"added_torrent_ids":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}'

    monkeypatch.setattr(send, "qbit_add_url", fake_qbit_add_url)

    response = client.post(
        "/api/rdt/send",
        json={"module": "manual", "title": "Peli", "link": magnet},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["module"] == "manual"
    assert payload["title"] == "Peli"
    assert payload["engine"] == "qBittorrent"
    assert payload["reason"] == "sin token RD"
    assert calls["qbit"]["url"] == magnet
    assert calls["qbit"]["target"]["key"] == "movies"
    assert calls["qbit"]["is_rdt"] is False
    assert calls["recorded"] is True


def test_send_route_decision_contract():
    from api.btdigg_rd import send

    assert send.decide_btdigg_download_route({"qbt_status": "QBT_OK"})[0] == "QBIT_REUSABLE"
    assert (
        send.decide_btdigg_download_route(
            {"rd_status": "RD_OK", "rd_existing": True, "rd_links": 1}
        )[0]
        == "RD_REUSABLE"
    )
    assert (
        send.decide_btdigg_download_route(
            {"rd_status": "RD_OK", "rd_existing": False, "rd_links": 1}
        )[0]
        == "RD_VERIFIED_MAGNET"
    )
    assert send.decide_btdigg_download_route({})[0] == "BLOCKED_NO_LINK"


def test_send_extracted_helpers_keep_send_wrappers():
    from api.btdigg_rd import _send_contracts, _send_manual_flow, _send_routing, send

    assert send.build_btdigg_download_contract is _send_contracts.build_btdigg_download_contract
    assert send.decide_btdigg_download_route is _send_contracts.decide_btdigg_download_route
    assert send.trace_contract is _send_contracts.trace_contract
    assert send.handle_manual_magnet_flow is _send_manual_flow.handle_manual_magnet_flow
    assert send.handle_manual_torrent_url_flow is _send_manual_flow.handle_manual_torrent_url_flow
    assert send.dest is _send_routing.dest
    assert send.download_dest_from_title is _send_routing.download_dest_from_title


def test_send_contract_builder_preserves_public_fields():
    from api.btdigg_rd import send

    magnet = "magnet:?xt=urn:btih:" + "b" * 40
    item = {
        "index": 7,
        "title": "Fallback",
        "hash": "b" * 40,
        "raw": {
            "selected_file_name": "Pelicula 2026.mkv",
            "rd_status": "RD_OK",
            "rd_existing": "sí",
            "rd_links": "2",
            "rd_torrent_id": "rd-1",
            "selected_file_ids": "1,2",
            "qbt_status": "",
            "qbt_was_existing": "0",
        },
    }

    contract = send.build_btdigg_download_contract(item, magnet)

    assert contract["index"] == 7
    assert contract["title"] == "Pelicula 2026.mkv"
    assert contract["hash"] == "b" * 40
    assert contract["magnet"] == magnet
    assert contract["rd_existing"] is True
    assert contract["rd_links"] == 2
    assert contract["rd_torrent_id"] == "rd-1"
    assert contract["selected_file_ids"] == "1,2"
    assert send.decide_btdigg_download_route(contract)[0] == "RD_REUSABLE"


@pytest.mark.parametrize(
    ("contract_patch", "expected_route", "expected_handler"),
    [
        (
            {"rd_status": "RD_OK", "rd_existing": True, "rd_links": 1, "rd_torrent_id": "rd-1"},
            "RD_REUSABLE",
            "route_rd_reusable_native",
        ),
        (
            {"rd_status": "RD_OK", "rd_existing": False, "rd_links": 1},
            "RD_VERIFIED_MAGNET",
            "route_rd_verified_magnet_native",
        ),
        (
            {"qbt_status": "QBT_OK", "qbt_was_existing": True},
            "QBIT_REUSABLE",
            "route_qbit_reusable",
        ),
    ],
)
def test_api_rdt_send_btdigg_contract_route_dispatches(client, monkeypatch, contract_patch, expected_route, expected_handler):
    from api.btdigg_rd import send

    magnet = "magnet:?xt=urn:btih:" + "c" * 40
    item = {"index": 1, "title": "Servidor", "link": magnet, "hash": "c" * 40, "raw": {}}
    base_contract = {
        "index": 1,
        "title": "Servidor",
        "hash": "c" * 40,
        "link": magnet,
        "magnet": magnet,
        "torrent_url": "",
        "rd_status": "",
        "rd_existing": False,
        "rd_links": 0,
        "rd_torrent_id": "",
        "selected_file_name": "",
        "selected_file_ids": "",
        "qbt_status": "",
        "qbt_was_existing": False,
        "qbt_reason": "",
    }
    base_contract.update(contract_patch)
    calls: list[str] = []

    monkeypatch.setattr(send, "_validate_btdigg_download_payload", lambda payload, trace_id: (item, ""))
    monkeypatch.setattr(send, "build_btdigg_download_contract", lambda current_item, link, expected_hash="": dict(base_contract))
    monkeypatch.setattr(send, "resolve_btdigg_card_to_magnet", lambda link, title, expected_hash="": link)

    def fake_route(name):
        def _handler(*args, **kwargs):
            calls.append(name)
            return send.jsonify({"ok": True, "route": name})

        return _handler

    monkeypatch.setattr(send, "route_rd_reusable_native", fake_route("route_rd_reusable_native"))
    monkeypatch.setattr(send, "route_rd_verified_magnet_native", fake_route("route_rd_verified_magnet_native"))
    monkeypatch.setattr(send, "route_qbit_reusable", fake_route("route_qbit_reusable"))

    response = client.post("/api/rdt/send", json={"module": "btdigg", "index": 1, "title": "Clic", "link": magnet})

    assert send.decide_btdigg_download_route(base_contract)[0] == expected_route
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "route": expected_handler}
    assert calls == [expected_handler]


def test_api_rdt_send_btdigg_contract_blocks_unsafe(client, monkeypatch):
    from api.btdigg_rd import send

    item = {"index": 1, "title": "Servidor", "link": "sin-evidencia", "hash": "", "raw": {}}
    contract = {
        "index": 1,
        "title": "Servidor",
        "hash": "",
        "link": "sin-evidencia",
        "magnet": "",
        "torrent_url": "",
        "rd_status": "",
        "rd_existing": False,
        "rd_links": 0,
        "rd_torrent_id": "",
        "selected_file_name": "",
        "selected_file_ids": "",
        "qbt_status": "",
        "qbt_was_existing": False,
        "qbt_reason": "",
    }

    monkeypatch.setattr(send, "_validate_btdigg_download_payload", lambda payload, trace_id: (item, ""))
    monkeypatch.setattr(send, "build_btdigg_download_contract", lambda current_item, link, expected_hash="": dict(contract))
    monkeypatch.setattr(send, "resolve_btdigg_card_to_magnet", lambda link, title, expected_hash="": link)

    response = client.post("/api/rdt/send", json={"module": "btdigg", "index": 1, "title": "Clic", "link": "sin-evidencia"})

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["route"] == "BLOCKED_UNSAFE"
    assert "trace_id" in payload
