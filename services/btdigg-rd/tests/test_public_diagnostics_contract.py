from __future__ import annotations

import json
import sqlite3


def _load_public_diagnostics(isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path):
    public_dir = tmp_path / "diagnostics_public"
    monkeypatch.setenv("BTDIGG_PUBLIC_DIAGNOSTICS_DIR", str(public_dir))
    reload_data_dir_modules("api.btdigg_rd.public_diagnostics")
    from api.btdigg_rd import public_diagnostics

    return public_diagnostics, public_dir


def test_public_diagnostics_exports_everything_but_secrets(
    isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
):
    public_diagnostics, public_dir = _load_public_diagnostics(
        isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
    )

    magnet = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=Matrix"
    (isolated_data_dir / "jobs" / "job1").mkdir(parents=True)
    (isolated_data_dir / "jobs" / "job1" / "shown.json").write_text(
        json.dumps(
            {
                "title": "Matrix",
                "magnet": magnet,
                "source_url": "https://btdig.com/search?q=matrix",
                "path": "Z:/media/Matrix.mkv",
                "password": "super-secret",
            }
        ),
        encoding="utf-8",
    )
    (isolated_data_dir / "diagnostics" / "btdigg" / "jobs" / "2026-07-08" / "job1").mkdir(parents=True)
    (isolated_data_dir / "diagnostics" / "btdigg" / "jobs" / "2026-07-08" / "job1" / "events.jsonl").write_text(
        json.dumps({"event": "rd_verify", "hash": "b" * 40, "authorization": "Bearer abc123"}) + "\n",
        encoding="utf-8",
    )
    (isolated_data_dir / "motor").mkdir(parents=True)
    (isolated_data_dir / "motor" / "config.json").write_text(
        json.dumps(
            {
                "tmdb_api_token": "eyJaaa.bbb.ccc",
                "btdigg_url_templates": ["https://btdig.com/search?q={query_quote}"],
                "write_last_links_txt": True,
            }
        ),
        encoding="utf-8",
    )
    (isolated_data_dir / "motor" / "rd_token.txt").write_text("rd-secret-token", encoding="utf-8")

    summary = public_diagnostics.export_public_diagnostics(trigger="pytest", current_run_id="job1")

    shown = json.loads((public_dir / "btdigg" / "jobs" / "job1" / "shown.json").read_text(encoding="utf-8"))
    assert shown["magnet"] == magnet
    assert shown["source_url"] == "https://btdig.com/search?q=matrix"
    assert shown["path"] == "Z:/media/Matrix.mkv"
    assert shown["password"] == public_diagnostics.REDACTED

    config = json.loads((public_dir / "btdigg" / "motor" / "config.json").read_text(encoding="utf-8"))
    assert config["tmdb_api_token"] == public_diagnostics.REDACTED
    assert config["btdigg_url_templates"] == ["https://btdig.com/search?q={query_quote}"]

    token_file = (public_dir / "btdigg" / "motor" / "rd_token.txt").read_text(encoding="utf-8")
    assert token_file == public_diagnostics.REDACTED_FILE

    events = (public_dir / "btdigg" / "diagnostics" / "btdigg" / "jobs" / "2026-07-08" / "job1" / "events.jsonl").read_text(encoding="utf-8")
    assert "Bearer abc123" not in events
    assert "rd_verify" in events
    assert "b" * 40 in events
    assert summary["redactions"] >= 3


def test_public_diagnostics_exports_sqlite_as_readable_jsonl(
    isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
):
    public_diagnostics, public_dir = _load_public_diagnostics(
        isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
    )

    db_path = isolated_data_dir / "title_resolver.sqlite3"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("create table cache (query text, resolved text, api_key text)")
        conn.execute("insert into cache values (?, ?, ?)", ("matrix", "Matrix", "secret-key"))

    summary = public_diagnostics.export_public_diagnostics(trigger="pytest")

    table_file = public_dir / "btdigg" / "title_resolver.sqlite3_export" / "tables" / "cache.jsonl"
    table_text = table_file.read_text(encoding="utf-8")
    assert "matrix" in table_text
    assert "Matrix" in table_text
    assert "secret-key" not in table_text
    assert public_diagnostics.REDACTED in table_text
    assert summary["sqlite_rows"] == 1


def test_public_diagnostics_extra_roots_are_included(
    isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
):
    extra_root = tmp_path / "cloudflared_logs"
    extra_root.mkdir()
    (extra_root / "cloudflared.log").write_text(
        "public url https://example.trycloudflare.com\nCLOUDFLARE_API_TOKEN=secret-token\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BTDIGG_PUBLIC_DIAGNOSTICS_EXTRA_ROOTS", f"{extra_root}=cloudflared/logs")
    public_diagnostics, public_dir = _load_public_diagnostics(
        isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
    )

    public_diagnostics.export_public_diagnostics(trigger="pytest")

    exported = (public_dir / "cloudflared_logs" / "cloudflared.log").read_text(encoding="utf-8")
    assert "https://example.trycloudflare.com" in exported
    assert "secret-token" not in exported
    assert "CLOUDFLARE_API_TOKEN=***REDACTED***" in exported


def test_public_diagnostics_cleans_mounted_output_contents(
    isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
):
    public_diagnostics, public_dir = _load_public_diagnostics(
        isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
    )
    public_dir.mkdir(parents=True)
    old_dir = public_dir / "old"
    old_dir.mkdir()
    (old_dir / "old.txt").write_text("old", encoding="utf-8")

    real_rmtree = public_diagnostics.shutil.rmtree

    def guarded_rmtree(path):
        assert path != public_dir
        return real_rmtree(path)

    monkeypatch.setattr(public_diagnostics.shutil, "rmtree", guarded_rmtree)
    public_diagnostics.export_public_diagnostics(trigger="pytest")

    assert public_dir.exists()
    assert not old_dir.exists()
    assert (public_dir / "manifest.json").exists()


def test_public_diagnostics_manifest_uses_mounted_project_root(
    isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
):
    mounted_root = tmp_path / "mounted_repo"
    (mounted_root / ".git").mkdir(parents=True)
    monkeypatch.setenv("BTDIGG_PROJECT_ROOT", str(mounted_root))
    public_diagnostics, public_dir = _load_public_diagnostics(
        isolated_data_dir, reload_data_dir_modules, monkeypatch, tmp_path
    )

    public_diagnostics.export_public_diagnostics(trigger="pytest")

    manifest = json.loads((public_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["repo"]["root"] == str(mounted_root)
