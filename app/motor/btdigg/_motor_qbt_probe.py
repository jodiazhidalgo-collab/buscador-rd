from __future__ import annotations


def qbt_probe_one_impl(
    opener,
    r,
    idx=0,
    total=0,
    *,
    config,
    magnet_hash,
    qbt_info_by_hash,
    qbt_eval_info,
    qbt_request,
    qbt_delete_hash,
    result_display_name,
    safe_int,
    diag,
    cancel_checkpoint,
    sleep_interruptible,
    user_cancelled_cls,
    non_cancelable_cleanup,
    time_module,
    print_func=print,
):
    cancel_checkpoint("qbt_probe.before")
    h = (r.hash or magnet_hash(r.magnet) or "").lower()
    if not h or not r.magnet:
        r.qbt_status = "QBT_SIN_HASH"
        r.qbt_reason = "Sin hash/magnet para probar en qBittorrent"
        return r

    existing = qbt_info_by_hash(opener, h)
    added_by_us = False
    name = result_display_name(r)[:80]
    if existing:
        r.qbt_was_existing = True
        status, reason = qbt_eval_info(existing)
        r.qbt_status = status
        r.qbt_reason = "Ya estaba en qBittorrent. " + reason
        r.qbt_seeds = max(0, safe_int(existing.get("num_seeds"), 0))
        r.qbt_peers = max(0, safe_int(existing.get("num_leechs"), 0))
        r.qbt_progress = float(existing.get("progress") or 0)
        r.qbt_speed_bps = safe_int(existing.get("dlspeed"), 0)
        r.qbt_size_gb = (safe_int(existing.get("size"), 0) / (1024**3)) if existing.get("size") else 0.0
        diag("qbt_probe_existing", n=idx, total=total, hash=h, status=status, reason=reason[:300])
        return r

    try:
        data = {
            "urls": r.magnet,
            "paused": "false",
            "autoTMM": "false",
            "savepath": str(config.get("qbit_probe_save_path", "/data/downloads/torrents/incomplete/rd_turbo_probe")),
        }
        cat = str(config.get("qbit_probe_category", "") or "")
        if cat:
            data["category"] = cat
        qbt_request(opener, "POST", "/api/v2/torrents/add", data, timeout=20)
        added_by_us = True
        diag("qbt_probe_add", n=idx, total=total, hash=h, title=r.title[:160])
        cancel_checkpoint("qbt_probe.after_add")
    except Exception as e:
        r.qbt_status = "QBT_ADD_ERROR"
        r.qbt_reason = str(e)[:500]
        diag("qbt_probe_add_error", n=idx, total=total, hash=h, error=str(e)[:500])
        print_func(f"  qBit error {idx}/{total}: QBT_ADD_ERROR - {name}", flush=True)
        return r

    deadline = time_module.time() + float(config.get("qbit_probe_wait_sec", 25) or 25)
    poll = float(config.get("qbit_probe_poll_sec", 3) or 3)
    last_info = None
    last_status, last_reason = "QBT_NO_INFO", "Sin info todav\u00eda"
    try:
        while time_module.time() < deadline:
            sleep_interruptible(poll, where="qbt_probe.poll")
            info = qbt_info_by_hash(opener, h)
            if not info:
                continue
            last_info = info
            last_status, last_reason = qbt_eval_info(info)
            diag(
                "qbt_probe_poll",
                n=idx,
                total=total,
                hash=h,
                status=last_status,
                state=str(info.get("state") or ""),
                progress=round(float(info.get("progress") or 0), 4),
                dlspeed=safe_int(info.get("dlspeed"), 0),
                seeds=max(0, safe_int(info.get("num_seeds"), 0)),
                peers=max(0, safe_int(info.get("num_leechs"), 0)),
                size_gb=round((safe_int(info.get("size"), 0) / (1024**3)), 3),
            )
            if last_status in ("QBT_OK", "QBT_VIVO"):
                break
    except user_cancelled_cls:
        if added_by_us and config.get("qbit_delete_probe_after", True):
            with non_cancelable_cleanup():
                qbt_delete_hash(opener, h, "cancel_probe")
        raise

    if last_info:
        r.qbt_seeds = max(0, safe_int(last_info.get("num_seeds"), 0))
        r.qbt_peers = max(0, safe_int(last_info.get("num_leechs"), 0))
        r.qbt_progress = float(last_info.get("progress") or 0)
        r.qbt_speed_bps = safe_int(last_info.get("dlspeed"), 0)
        r.qbt_size_gb = (safe_int(last_info.get("size"), 0) / (1024**3)) if last_info.get("size") else 0.0
    r.qbt_status = last_status
    r.qbt_reason = last_reason
    diag("qbt_probe_result", n=idx, total=total, hash=h, status=r.qbt_status, reason=r.qbt_reason[:300], title=r.title[:160])
    if added_by_us and config.get("qbit_delete_probe_after", True):
        qbt_delete_hash(opener, h, "fin_probe")
    return r
