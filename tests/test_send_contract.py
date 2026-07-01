from __future__ import annotations


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
