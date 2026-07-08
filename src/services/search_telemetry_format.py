"""Human-readable telemetry summaries for UI and Agent API."""

from __future__ import annotations

from typing import Any

from src.services.search_telemetry_store import (
    TIER_ORDER,
    get_telemetry_summary,
    is_telemetry_enabled,
)

def format_telemetry_panel(*, language: str = "zh", texts: dict[str, Any] | None = None) -> str:
    if not is_telemetry_enabled():
        labels = texts or {}
        if language == "en":
            return str(labels.get("search_telemetry_disabled", "Screenshot search telemetry is disabled."))
        return str(labels.get("search_telemetry_disabled", "截图搜索遥测已关闭。"))

    summary = get_telemetry_summary()
    crop = summary.get("crop_locate") or {}
    playback = summary.get("playback_bias") or {}
    tiers = summary.get("confidence_tiers") or {}
    labels = texts or {}
    total_tiers = sum(int(v or 0) for v in tiers.values())
    na = "—"

    def pct_rate(value: float | int | None) -> str:
        if value is None:
            return na
        return f"{float(value) * 100.0:.1f}%"

    def pct_share(count: int) -> str:
        if total_tiers <= 0:
            return na
        return f"{int(count) * 100.0 / float(total_tiers):.1f}%"

    def sec_value(value: float | None) -> str:
        if value is None:
            return na
        return f"{float(value):.1f}s"

    if language == "en":
        lines = [
            str(labels.get("search_telemetry_panel_anchor_retention", "Anchor retention")),
            pct_rate(crop.get("retention_rate")),
            "",
            str(labels.get("search_telemetry_panel_playback_mean", "Playback mean abs delta")),
            sec_value(playback.get("mean_abs_delta_sec") if int(playback.get("samples", 0) or 0) > 0 else None),
            "",
            str(labels.get("search_telemetry_panel_playback_within_1s", "Playback within 1s")),
            pct_rate(playback.get("within_1s_rate") if int(playback.get("samples", 0) or 0) > 0 else None),
        ]
        playback_note = str(labels.get("search_telemetry_panel_playback_note", "") or "").strip()
        if playback_note:
            lines.extend(["", playback_note])
        if int(playback.get("samples", 0) or 0) < 30:
            low_sample = str(labels.get("search_telemetry_panel_low_sample_note", "") or "").strip()
            if low_sample:
                lines.extend(["", low_sample])
        if int(playback.get("samples", 0) or 0) >= 5:
            lines.extend(
                [
                    "",
                    str(labels.get("search_telemetry_panel_playback_percentiles", "Playback abs delta percentiles")),
                    f"p50 = {sec_value(playback.get('p50_abs_delta_sec'))}",
                    f"p90 = {sec_value(playback.get('p90_abs_delta_sec'))}",
                    f"p95 = {sec_value(playback.get('p95_abs_delta_sec'))}",
                ]
            )
        lines.extend(["", str(labels.get("search_telemetry_panel_confidence", "Confidence"))])
        for tier_key in TIER_ORDER:
            count = int(tiers.get(tier_key, 0) or 0)
            if total_tiers <= 0 and count <= 0:
                continue
            tier_label = str(labels.get(tier_key, tier_key))
            lines.append(f"{tier_label:<10} {pct_share(count)}")
        lines.extend(
            [
                "",
                str(
                    labels.get(
                        "search_telemetry_panel_samples",
                        "Samples: locate={locate} playback={playback} confidence={confidence}",
                    ).format(
                        locate=int(crop.get("total", 0) or 0),
                        playback=int(playback.get("samples", 0) or 0),
                        confidence=total_tiers,
                    )
                ),
            ]
        )
        return "\n".join(lines)

    lines = [
        str(labels.get("search_telemetry_panel_anchor_retention", "Anchor 保留率")),
        pct_rate(crop.get("retention_rate")),
        "",
        str(labels.get("search_telemetry_panel_playback_mean", "播放平均绝对偏差")),
        sec_value(playback.get("mean_abs_delta_sec") if int(playback.get("samples", 0) or 0) > 0 else None),
        "",
        str(labels.get("search_telemetry_panel_playback_within_1s", "播放 ±1s 内")),
        pct_rate(playback.get("within_1s_rate") if int(playback.get("samples", 0) or 0) > 0 else None),
    ]
    playback_note = str(labels.get("search_telemetry_panel_playback_note", "") or "").strip()
    if playback_note:
        lines.extend(["", playback_note])
    if int(playback.get("samples", 0) or 0) < 30:
        low_sample = str(labels.get("search_telemetry_panel_low_sample_note", "") or "").strip()
        if low_sample:
            lines.extend(["", low_sample])
    if int(playback.get("samples", 0) or 0) >= 5:
        lines.extend(
            [
                "",
                str(labels.get("search_telemetry_panel_playback_percentiles", "播放绝对偏差分位")),
                f"p50 = {sec_value(playback.get('p50_abs_delta_sec'))}",
                f"p90 = {sec_value(playback.get('p90_abs_delta_sec'))}",
                f"p95 = {sec_value(playback.get('p95_abs_delta_sec'))}",
            ]
        )
    lines.extend(["", str(labels.get("search_telemetry_panel_confidence", "置信度分布"))])
    for tier_key in TIER_ORDER:
        count = int(tiers.get(tier_key, 0) or 0)
        if total_tiers <= 0 and count <= 0:
            continue
        tier_label = str(labels.get(tier_key, tier_key))
        lines.append(f"{tier_label:<6} {pct_share(count)}")
    lines.extend(
        [
            "",
            str(
                labels.get(
                    "search_telemetry_panel_samples",
                    "样本：定位={locate} 播放={playback} 置信度={confidence}",
                ).format(
                    locate=int(crop.get("total", 0) or 0),
                    playback=int(playback.get("samples", 0) or 0),
                    confidence=total_tiers,
                )
            ),
        ]
    )
    return "\n".join(lines)


def format_telemetry_summary(*, language: str = "zh") -> str:
    summary = get_telemetry_summary()
    crop = summary.get("crop_locate") or {}
    playback = summary.get("playback_bias") or {}
    tiers = summary.get("confidence_tiers") or {}
    total_tiers = max(1, sum(int(v or 0) for v in tiers.values()))

    if language == "en":
        lines = [
            f"Search telemetry ({summary.get('updated_at') or '-'})",
            (
                "Crop locate anchor retention: "
                f"{crop.get('anchor_kept', 0)}/{crop.get('total', 0)} "
                f"({int(round(float(crop.get('retention_rate', 0.0)) * 100))}%)"
            ),
            "Confidence tiers:",
        ]
        for tier_key, count in sorted(tiers.items(), key=lambda item: (-int(item[1] or 0), item[0])):
            pct = int(round(int(count or 0) * 100 / total_tiers))
            lines.append(f"  {tier_key}: {count} ({pct}%)")
        lines.extend(
            [
                (
                    "Playback bias: "
                    f"samples={playback.get('samples', 0)} "
                    f"mean_abs_delta={float(playback.get('mean_abs_delta_sec', 0.0)):.2f}s "
                    f"within_1s={int(round(float(playback.get('within_1s_rate', 0.0)) * 100))}%"
                ),
            ]
        )
        return "\n".join(lines)

    lines = [
        f"搜索遥测 ({summary.get('updated_at') or '-'})",
        (
            "截图定位 anchor 保留: "
            f"{crop.get('anchor_kept', 0)}/{crop.get('total', 0)} "
            f"({int(round(float(crop.get('retention_rate', 0.0)) * 100))}%)"
        ),
        "置信度分布:",
    ]
    for tier_key, count in sorted(tiers.items(), key=lambda item: (-int(item[1] or 0), item[0])):
        pct = int(round(int(count or 0) * 100 / total_tiers))
        lines.append(f"  {tier_key}: {count} ({pct}%)")
    lines.append(
        (
            "播放偏差: "
            f"样本={playback.get('samples', 0)} "
            f"平均绝对偏差={float(playback.get('mean_abs_delta_sec', 0.0)):.2f}s "
            f"±1s内={int(round(float(playback.get('within_1s_rate', 0.0)) * 100))}%"
        )
    )
    return "\n".join(lines)
