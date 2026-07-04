from __future__ import annotations


def rd_call_with_retry_impl(
    method,
    path,
    token,
    data=None,
    raw=None,
    content_type=None,
    op_name="",
    attempts=None,
    retry_context=None,
    base_sec=None,
    max_sec=None,
    retry_429_attempts=None,
    *,
    config,
    rd_api,
    rd_api_error_cls,
    rd_retry_sleep,
    diag,
    sleep_interruptible,
    is_rd_temp_error_msg,
    rd_path_group,
):
    max_attempts = max(1, int(attempts if attempts is not None else config.get("rd_temp_error_retries", 2) or 2))
    max_429_attempts = max_attempts
    if retry_429_attempts is not None:
        max_429_attempts = max(max_attempts, int(retry_429_attempts or max_attempts))
    op = str(op_name or path or "").strip()[:80]
    last_error = None
    exhausted_limit = max_attempts
    loop_limit = max(max_attempts, max_429_attempts)

    for attempt in range(1, loop_limit + 1):
        try:
            return rd_api(method, path, token, data=data, raw=raw, content_type=content_type)
        except rd_api_error_cls as e:
            last_error = e
            if e.is_infringing:
                if retry_context:
                    retry_context.bump("rd_error_terminal_count")
                diag(
                    "rd_call_terminal_error",
                    op=op,
                    method=str(method).upper(),
                    path=rd_path_group(path),
                    attempt=attempt,
                    code=e.status_code,
                    error_code=e.error_code,
                    error=e.error[:120],
                )
                raise
            if e.is_already_active:
                if retry_context:
                    retry_context.bump("rd_retry_33_count")
                raise
            if e.is_active_limit:
                if retry_context:
                    retry_context.bump("rd_retry_21_count")
                    if op == "delete":
                        retry_context.bump("delete_retries")
                if retry_context and getattr(retry_context, "slots", None):
                    try:
                        retry_context.slots.refresh(force=True)
                    except Exception as refresh_error:
                        diag("rd_retry_21_refresh_error", op=op, error=str(refresh_error)[:300])
                if attempt >= max_attempts:
                    break
                wait_sec = float(config.get("rd_retry_21_wait_sec", 1.5) or 1.5)
                diag(
                    "rd_call_retry_21",
                    op=op,
                    method=str(method).upper(),
                    path=rd_path_group(path),
                    attempt=attempt,
                    max_attempts=max_attempts,
                    wait_sec=wait_sec,
                    error=str(e)[:300],
                )
                sleep_interruptible(wait_sec, where="rd_retry_21")
                continue
            if e.is_429:
                if retry_context:
                    retry_context.bump("rd_retry_429_count")
                    if op == "delete":
                        retry_context.bump("delete_retries")
                exhausted_limit = max_429_attempts
                if attempt >= max_429_attempts:
                    break
                wait_sec = rd_retry_sleep(attempt, base_sec=base_sec, max_sec=max_sec)
                diag(
                    "rd_call_retry_429",
                    op=op,
                    method=str(method).upper(),
                    path=rd_path_group(path),
                    attempt=attempt,
                    max_attempts=max_429_attempts,
                    wait_sec=round(wait_sec, 3),
                    error=str(e)[:300],
                )
                continue
            if attempt > max_attempts:
                break
            if e.is_temp:
                if retry_context:
                    retry_context.bump("rd_retry_temp_count")
                    if op == "delete":
                        retry_context.bump("delete_retries")
                if attempt >= max_attempts:
                    break
                wait_sec = rd_retry_sleep(attempt, base_sec=base_sec, max_sec=max_sec)
                diag(
                    "rd_call_retry_temp",
                    op=op,
                    method=str(method).upper(),
                    path=rd_path_group(path),
                    attempt=attempt,
                    max_attempts=max_attempts,
                    wait_sec=round(wait_sec, 3),
                    error=str(e)[:300],
                )
                continue
            raise
        except Exception as e:
            last_error = e
            if not is_rd_temp_error_msg(e):
                raise
            if retry_context:
                retry_context.bump("rd_retry_temp_count")
                if op == "delete":
                    retry_context.bump("delete_retries")
            if attempt >= max_attempts:
                break
            wait_sec = rd_retry_sleep(attempt, base_sec=base_sec, max_sec=max_sec)
            diag(
                "rd_call_retry_exception",
                op=op,
                method=str(method).upper(),
                path=rd_path_group(path),
                attempt=attempt,
                max_attempts=max_attempts,
                wait_sec=round(wait_sec, 3),
                error=str(e)[:300],
            )

    diag(
        "rd_call_retry_exhausted",
        op=op,
        method=str(method).upper(),
        path=rd_path_group(path),
        attempts=exhausted_limit,
        error=str(last_error)[:400],
    )
    raise last_error
