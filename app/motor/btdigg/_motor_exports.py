from __future__ import annotations

import json


def export_results_impl(
    results,
    shown=None,
    write_all_json=True,
    *,
    config,
    export_dir,
    cancel_checkpoint,
    diag,
    log,
    is_qbt_working_status,
    is_working_status,
    last_qbit_extras=None,
    last_rd_temp_errors=None,
):
    """Write debug/export artifacts while keeping runtime paths owned by the caller."""
    if not config.get("write_exports", True):
        return
    cancel_checkpoint("export_results.before_write")
    try:
        export_dir.mkdir(exist_ok=True)
        all_json = export_dir / "ULTIMOS_RESULTADOS.json"
        top_txt = export_dir / "ULTIMO_TOP.txt"
        if write_all_json:
            rows = []
            for i, r in enumerate(results, 1):
                rows.append(
                    {
                        "n": i,
                        "title": r.title,
                        "hash": r.hash,
                        "size_gb": round(float(r.size_gb or 0), 3),
                        "score": r.score,
                        "rd_status": r.rd_status,
                        "rd_files": r.rd_files,
                        "rd_largest_gb": round(float(r.rd_largest_gb or 0), 3),
                        "rd_torrent_id": r.rd_torrent_id,
                        "rd_existing": bool(getattr(r, "rd_existing", False)),
                        "rd_links": r.rd_links,
                        "selected_file_ids": r.selected_file_ids,
                        "selected_file_name": r.selected_file_name,
                        "selected_file_size_gb": round(float(r.selected_file_size_gb or 0), 3),
                        "is_pack": r.is_pack,
                        "pack_note": r.pack_note,
                        "qbt_status": r.qbt_status,
                        "qbt_reason": r.qbt_reason,
                        "qbt_seeds": r.qbt_seeds,
                        "qbt_peers": r.qbt_peers,
                        "qbt_progress": round(float(r.qbt_progress or 0), 4),
                        "qbt_speed_bps": r.qbt_speed_bps,
                        "qbt_size_gb": round(float(r.qbt_size_gb or 0), 3),
                        "qbt_was_existing": r.qbt_was_existing,
                        "tracker_name": r.tracker_name,
                        "tracker_seeders": r.tracker_seeders,
                        "tracker_leechers": r.tracker_leechers,
                        "tracker_category": r.tracker_category,
                        "source_url": r.source_url,
                        "btdigg_file_name": r.btdigg_file_name,
                        "btdigg_file_size_gb": round(float(r.btdigg_file_size_gb or 0), 3),
                        "same_file_match": r.same_file_match,
                        "same_file_reason": r.same_file_reason,
                        "raw_context": (getattr(r, "raw_context", "") or "")[:4000],
                        "reason": r.reason,
                        "magnet": r.magnet,
                        "torrent_url": r.torrent_url,
                    }
                )
            all_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

        qbit_txt = export_dir / "ULTIMO_QBIT_VIVOS.txt"
        qbit_rows = last_qbit_extras or [
            r for r in results if is_qbt_working_status(r.qbt_status) and not is_working_status(r.rd_status)
        ]
        qlines = ["RD Turbo Pro - lista extra qBittorrent vivos", "=" * 80]
        for qidx, r in enumerate(qbit_rows, 1):
            qsize = r.qbt_size_gb or r.size_gb or r.rd_largest_gb
            size_s = f"{qsize:.1f} GB" if qsize else "? GB"
            qlines.append(f"[Q{qidx:02d}] QBT:{r.qbt_status:10} SIZE:{size_s:>9} HASH:{r.hash}")
            qlines.append(f"      TORRENT: {r.title}")
            if r.btdigg_file_name:
                qlines.append(f"      ARCHIVO BTDIGG: {r.btdigg_file_name} ({(r.btdigg_file_size_gb or 0):.1f} GB)")
            if r.selected_file_name:
                qlines.append(f"      ARCHIVO RD: {r.selected_file_name} ({(r.selected_file_size_gb or 0):.1f} GB)")
            qlines.append(f"      MOTIVO: {r.qbt_reason[:350]}")
            qlines.append(f"      MAGNET: {r.magnet}")
            qlines.append("")
        qbit_txt.write_text("\n".join(qlines), encoding="utf-8")

        rd_temp_txt = export_dir / "ULTIMO_RD_TEMPORAL.txt"
        temp_rows = last_rd_temp_errors or [r for r in results if r.rd_status == "RD_ERROR_TEMPORAL"]
        tlines = ["RD Turbo Pro - pendientes por error temporal Real-Debrid", "=" * 80]
        tlines.append("No son resultados limpios ni confirmados. No se dan por muertos.")
        tlines.append("")
        for tidx, r in enumerate(temp_rows, 1):
            tsize = r.size_gb or r.rd_largest_gb
            size_s = f"{tsize:.1f} GB" if tsize else "? GB"
            tlines.append(f"[T{tidx:02d}] RD:{r.rd_status:17} SIZE:{size_s:>9} HASH:{r.hash}")
            tlines.append(f"      TORRENT: {r.title}")
            if r.btdigg_file_name:
                tlines.append(f"      ARCHIVO BTDIGG: {r.btdigg_file_name} ({(r.btdigg_file_size_gb or 0):.1f} GB)")
            tlines.append(f"      MOTIVO: {r.reason[:350]}")
            tlines.append(f"      MAGNET: {r.magnet}")
            tlines.append("")
        rd_temp_txt.write_text("\n".join(tlines), encoding="utf-8")

        use = shown if shown is not None else results[: int(config.get("max_results_to_show", 30))]
        lines = []
        lines.append("RD Turbo Pro - \u00faltimo TOP")
        lines.append("=" * 80)
        for idx, r in enumerate(use, 1):
            rd = r.rd_status
            size = f"{r.size_gb:.1f} GB" if r.size_gb else (f"{r.rd_largest_gb:.1f} GB" if r.rd_largest_gb else "? GB")
            lines.append(f"[{idx:02d}] RD:{rd:12} SCORE:{r.score:4d} SIZE:{size:>9} HASH:{r.hash}")
            lines.append(f"     {r.title}")
            if r.btdigg_file_name:
                lines.append(f"     ARCHIVO BTDIGG: {r.btdigg_file_name} ({(r.btdigg_file_size_gb or 0):.1f} GB)")
            if r.selected_file_name:
                lines.append(f"     ARCHIVO: {r.selected_file_name} ({(r.selected_file_size_gb or r.size_gb or 0):.1f} GB)")
            if r.qbt_status:
                lines.append(f"     QBIT: {r.qbt_status} | seeds={r.qbt_seeds} peers={r.qbt_peers} | {r.qbt_reason[:220]}")
            if r.tracker_name or r.tracker_seeders or r.tracker_leechers:
                lines.append(f"     TRACKER: {r.tracker_name or '-'} | seeds={r.tracker_seeders} leechers={r.tracker_leechers} | {r.tracker_category or '-'}")
            if r.reason:
                lines.append(f"     MOTIVO: {r.reason[:300]}")
            lines.append("")
        top_txt.write_text("\n".join(lines), encoding="utf-8")
        diag("export_results", all_json=str(all_json), all_json_written=bool(write_all_json), top_txt=str(top_txt), total=len(results), shown=len(use))
    except Exception as e:
        log(f"export_results error: {e}")
