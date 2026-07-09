from __future__ import annotations


def test_qbit_no_seed_history_keeps_only_qbt_no_peers(isolated_data_dir, reload_data_dir_modules):
    reload_data_dir_modules()
    from api.btdigg_rd import history

    magnet = "magnet:?xt=urn:btih:" + "a" * 40
    history.record_qbit_no_seed_search(
        {"query": "Whistle", "pages": "1-2", "mode": "0", "min_gb": "0"},
        [
            {
                "title": "Sin semillas",
                "hash": "a" * 40,
                "magnet": magnet,
                "size_gb": 1.5,
                "qbt_status": "QBT_NO_PEERS",
                "qbt_reason": "Sin vida clara en qBittorrent",
                "qbt_seeds": 0,
                "qbt_peers": 3,
            },
            {
                "title": "Vivo",
                "hash": "b" * 40,
                "magnet": "magnet:?xt=urn:btih:" + "b" * 40,
                "qbt_status": "QBT_VIVO",
                "qbt_seeds": 1,
                "qbt_peers": 3,
            },
            {
                "title": "Con semillas",
                "hash": "c" * 40,
                "magnet": "magnet:?xt=urn:btih:" + "c" * 40,
                "qbt_status": "QBT_NO_PEERS",
                "qbt_seeds": 1,
                "qbt_peers": 0,
            },
        ],
    )

    loaded = history.load_qbit_no_seed_history()
    search = loaded["days"][0]["searches"][0]
    rows = search["results"]

    assert search["query"] == "Whistle"
    assert search["result_count"] == 1
    assert rows[0]["title"] == "Sin semillas"
    assert rows[0]["source"] == "qBit"
    assert rows[0]["status"] == "Sin semillas qB"
    assert rows[0]["seeds"] == 0
    assert rows[0]["peers"] == 3
    assert rows[0]["link"] == magnet


def test_force_qbit_from_no_seed_history_dispatches_forced_route(client, monkeypatch):
    from api.btdigg_rd import history, send

    magnet = "magnet:?xt=urn:btih:" + "d" * 40
    history.record_qbit_no_seed_search(
        {"query": "Whistle", "pages": "1-1"},
        [
            {
                "title": "Manual sin semillas",
                "hash": "d" * 40,
                "magnet": magnet,
                "size_gb": 0.7,
                "qbt_status": "QBT_NO_PEERS",
                "qbt_reason": "Sin vida clara en qBittorrent",
                "qbt_seeds": 0,
                "qbt_peers": 0,
            }
        ],
    )
    search = history.load_qbit_no_seed_history()["days"][0]["searches"][0]
    calls: list[str] = []

    monkeypatch.setattr(send, "resolve_btdigg_card_to_magnet", lambda link, title, expected_hash="": link)

    def fake_forced(contract, link, target, title, module, started, trace_id):
        calls.append(contract["qbt_status"])
        return send.jsonify({"ok": True, "route": "QBIT_FORCED", "title": title})

    monkeypatch.setattr(send, "route_qbit_forced", fake_forced)

    response = client.post(
        "/api/rdt/send",
        json={
            "module": "btdigg",
            "title": "Manual sin semillas",
            "link": magnet,
            "hash": "d" * 40,
            "from_history": True,
            "history_kind": "qbit_no_seeds",
            "history_id": search["id"],
            "history_result": 1,
            "force_qbit": True,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["route"] == "QBIT_FORCED"
    assert calls == ["QBT_NO_PEERS"]
