def build_precheck_dialog_payload(precheck, texts):
    rows = []
    blocked_items = list(precheck.get("blocked_links", []))
    risky_items = list(precheck.get("risky_links", []))

    reason_map = {
        "invalid_url": texts["network_precheck_reason_invalid_url"],
        "unsupported_page_type": texts["network_precheck_reason_unsupported_page"],
        "site_may_require_cookie_or_video_page": texts["network_precheck_reason_risky_site"],
    }

    for item in blocked_items:
        rows.append(
            [
                len(rows) + 1,
                texts["network_precheck_status_blocked"],
                reason_map.get(str(item.get("reason", "")), str(item.get("reason", ""))),
                item.get("link", ""),
            ]
        )

    for item in risky_items:
        rows.append(
            [
                len(rows) + 1,
                texts["network_precheck_status_risky"],
                reason_map.get(str(item.get("reason", "")), str(item.get("reason", ""))),
                item.get("link", ""),
            ]
        )

    subtitle = texts["network_precheck_dialog_subtitle"].format(
        accepted=int(precheck.get("accepted_count", 0)),
        blocked=int(precheck.get("blocked_count", 0)),
        risky=int(precheck.get("risky_count", 0)),
    )
    return {
        "title": texts["network_precheck_dialog_title"],
        "subtitle": subtitle,
        "headers": texts["network_precheck_dialog_headers"],
        "rows": rows,
    }
