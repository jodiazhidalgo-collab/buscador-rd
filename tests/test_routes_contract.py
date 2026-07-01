from __future__ import annotations


def test_public_routes_stay_registered(app):
    methods_by_rule: dict[str, set[str]] = {}
    for rule in app.url_map.iter_rules():
        methods_by_rule.setdefault(rule.rule, set()).update(rule.methods or set())

    expected = {
        "/api/job": {"POST"},
        "/api/rdt/send": {"POST"},
        "/api/settings": {"GET", "POST"},
        "/api/qbit-toggle": {"GET", "POST"},
        "/api/tv-rules": {"GET", "POST"},
        "/api/title-resolver/resolve": {"POST"},
        "/api/results/btdigg": {"GET"},
        "/api/history/btdigg": {"GET"},
    }

    for route, methods in expected.items():
        assert route in methods_by_rule
        assert methods <= methods_by_rule[route]


def test_key_routes_keep_endpoint_names(app):
    endpoints_by_rule = {
        rule.rule: rule.endpoint
        for rule in app.url_map.iter_rules()
        if rule.rule
        in {
            "/api/job",
            "/api/rdt/send",
            "/api/results/btdigg",
            "/api/history/btdigg",
            "/api/title-resolver/resolve",
        }
    }

    assert endpoints_by_rule["/api/job"] == "btdigg_rd.api_job"
    assert endpoints_by_rule["/api/rdt/send"] == "btdigg_rd.api_rdt_send"
    assert endpoints_by_rule["/api/results/btdigg"] == "btdigg_rd.api_results_btdigg"
    assert endpoints_by_rule["/api/history/btdigg"] == "btdigg_rd.api_history_btdigg"
    assert endpoints_by_rule["/api/title-resolver/resolve"] == "btdigg_rd.api_title_resolver_resolve"
