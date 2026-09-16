"""Tiny inline-SVG charts. No script, no fonts, no network: the dashboard
must render as a file on disk and inside a sandboxed artifact alike."""
from __future__ import annotations

import html

PALETTE = ["#4f6df5", "#f5a24f", "#3fbf8f", "#e35d6a", "#8f6ff0", "#2fb7d9", "#d9a02f", "#7a8aa0"]


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def hbars(rows: list[tuple[str, int, int | None]], *, width: int = 520, row_h: int = 22, label_w: int = 150,
          fmt=lambda v: str(v)) -> str:
    """Horizontal bars: (label, value, previous_value). previous draws as a
    thin marker so this month reads against last month."""
    if not rows:
        return '<p class="muted">nothing yet</p>'
    peak = max(max(v, p or 0) for _, v, p in rows) or 1
    bar_w = width - label_w - 90
    out = [f'<svg viewBox="0 0 {width} {row_h * len(rows)}" width="100%" role="img">']
    for i, (label, value, prev) in enumerate(rows):
        y = i * row_h
        w = max(1, int(bar_w * value / peak))
        out.append(f'<text x="{label_w - 8}" y="{y + 15}" text-anchor="end" class="lbl">{_esc(label)[:22]}</text>')
        out.append(f'<rect x="{label_w}" y="{y + 4}" width="{w}" height="{row_h - 8}" rx="3" fill="{PALETTE[i % len(PALETTE)]}"/>')
        if prev:
            px = label_w + int(bar_w * prev / peak)
            out.append(f'<rect x="{px - 1}" y="{y + 2}" width="2" height="{row_h - 4}" fill="currentColor" opacity="0.5"/>')
        out.append(f'<text x="{label_w + w + 6}" y="{y + 15}" class="val">{_esc(fmt(value))}</text>')
    out.append("</svg>")
    return "".join(out)


def grouped_bars(months: list[dict], *, width: int = 560, height: int = 180, fmt=lambda v: str(v)) -> str:
    """Income vs spending per month, with net as a label."""
    if not months:
        return '<p class="muted">nothing yet</p>'
    peak = max(max(m["income_cents"], m["expense_cents"]) for m in months) or 1
    n = len(months)
    pad_l, pad_b, pad_t = 8, 28, 16
    slot = (width - pad_l * 2) / n
    bw = max(6, int(slot * 0.32))
    plot_h = height - pad_b - pad_t
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">']
    for i, m in enumerate(months):
        x0 = pad_l + i * slot + slot * 0.15
        for j, (key, color) in enumerate((("income_cents", PALETTE[2]), ("expense_cents", PALETTE[3]))):
            h = int(plot_h * m[key] / peak)
            out.append(f'<rect x="{x0 + j * (bw + 3):.1f}" y="{pad_t + plot_h - h}" width="{bw}" height="{h}" rx="2" fill="{color}"/>')
        out.append(f'<text x="{pad_l + i * slot + slot / 2:.1f}" y="{height - 12}" text-anchor="middle" class="lbl">{_esc(m["month"][2:])}</text>')
        out.append(f'<text x="{pad_l + i * slot + slot / 2:.1f}" y="{height - 1}" text-anchor="middle" class="val small">{_esc(fmt(m["net_cents"]))}</text>')
    out.append(f'<rect x="{width - 150}" y="2" width="10" height="10" fill="{PALETTE[2]}"/><text x="{width - 136}" y="11" class="lbl">income</text>')
    out.append(f'<rect x="{width - 80}" y="2" width="10" height="10" fill="{PALETTE[3]}"/><text x="{width - 66}" y="11" class="lbl">spending</text>')
    out.append("</svg>")
    return "".join(out)


def sparkline(values: list[int], *, width: int = 120, height: int = 28) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / (len(values) - 1)
    pts = " ".join(f"{i * step:.1f},{height - 2 - (v - lo) / span * (height - 4):.1f}" for i, v in enumerate(values))
    color = PALETTE[2] if values[-1] >= values[0] else PALETTE[3]
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{pts}"/></svg>')


def progress(pct: float, *, color: str | None = None) -> str:
    pct = max(0.0, min(100.0, pct))
    return (f'<div class="bar"><div class="fill" style="width:{pct:.1f}%;background:{color or PALETTE[0]}"></div></div>')
