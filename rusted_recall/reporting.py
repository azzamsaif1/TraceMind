"""Recall report generation and export (directive section 11 "complete recall").

Exports the final report as JSON, CSV, and a polished self-contained HTML
document. PDF export is available when reportlab is installed.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape

# Documented formula for "manual effort avoided" — clearly an estimate.
MINUTES_PER_MANUAL_REPAIR = 45


@dataclass
class RecallReport:
    recall_event_id: str
    workspace_name: str
    source_of_truth: str
    reason: str
    total_assets_scanned: int = 0
    directly_affected: int = 0
    probably_affected: int = 0
    needs_review: int = 0
    safe: int = 0
    repair_requested: int = 0
    repair_succeeded: int = 0
    repair_failed: int = 0
    repair_requires_review: int = 0
    elapsed_seconds: float = 0.0
    provider_operations: int = 0
    b2_objects_created: int = 0
    review_decisions: list[dict] = field(default_factory=list)
    audit_timeline: list[dict] = field(default_factory=list)
    integrity_hashes: dict[str, str] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def estimated_manual_minutes_avoided(self) -> int:
        # Documented estimate: succeeded repairs × per-repair manual effort.
        return self.repair_succeeded * MINUTES_PER_MANUAL_REPAIR

    def as_dict(self) -> dict:
        d = {
            "recall_event_id": self.recall_event_id,
            "workspace_name": self.workspace_name,
            "source_of_truth": self.source_of_truth,
            "reason": self.reason,
            "generated_at": self.generated_at,
            "totals": {
                "total_assets_scanned": self.total_assets_scanned,
                "directly_affected": self.directly_affected,
                "probably_affected": self.probably_affected,
                "needs_review": self.needs_review,
                "safe": self.safe,
                "repair_requested": self.repair_requested,
                "repair_succeeded": self.repair_succeeded,
                "repair_failed": self.repair_failed,
                "repair_requires_review": self.repair_requires_review,
            },
            "operations": {
                "elapsed_seconds": round(self.elapsed_seconds, 3),
                "provider_operations": self.provider_operations,
                "b2_objects_created": self.b2_objects_created,
            },
            "estimated_manual_minutes_avoided": self.estimated_manual_minutes_avoided,
            "estimate_formula": f"repair_succeeded x {MINUTES_PER_MANUAL_REPAIR} minutes (estimate)",
            "review_decisions": self.review_decisions,
            "audit_timeline": self.audit_timeline,
            "integrity_hashes": self.integrity_hashes,
        }
        return d


def to_json(report: RecallReport) -> str:
    return json.dumps(report.as_dict(), indent=2)


def to_csv(report: RecallReport) -> str:
    d = report.as_dict()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["metric", "value"])
    for key, value in d["totals"].items():
        writer.writerow([key, value])
    for key, value in d["operations"].items():
        writer.writerow([key, value])
    writer.writerow(["estimated_manual_minutes_avoided", d["estimated_manual_minutes_avoided"]])
    return buf.getvalue()


def to_html(report: RecallReport) -> str:
    d = report.as_dict()
    totals = d["totals"]
    ops = d["operations"]

    def rows(mapping: dict) -> str:
        return "".join(
            f"<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>"
            for k, v in mapping.items()
        )

    timeline = "".join(
        f"<li><span class='ts'>{escape(str(e.get('at', '')))}</span> "
        f"<strong>{escape(str(e.get('event', '')))}</strong> "
        f"{escape(str(e.get('detail', '')))}</li>"
        for e in d["audit_timeline"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Rusted Recall — Report {escape(report.recall_event_id)}</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; }}
 h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
 table {{ border-collapse: collapse; margin: 0.5rem 0; }}
 td, th {{ border: 1px solid #ddd; padding: 6px 12px; text-align: left; }}
 .meta td:first-child {{ font-weight: 600; }}
 ul {{ line-height: 1.6; }} .ts {{ color: #666; font-variant-numeric: tabular-nums; }}
 .note {{ color: #666; font-size: 0.9rem; }}
</style></head><body>
<h1>Rusted Recall — Final Recall Report</h1>
<table class="meta">
 <tr><td>Recall event</td><td>{escape(report.recall_event_id)}</td></tr>
 <tr><td>Workspace</td><td>{escape(report.workspace_name)}</td></tr>
 <tr><td>Source of truth</td><td>{escape(report.source_of_truth)}</td></tr>
 <tr><td>Reason</td><td>{escape(report.reason)}</td></tr>
 <tr><td>Generated</td><td>{escape(report.generated_at)}</td></tr>
</table>
<h2>Impact totals</h2><table>{rows(totals)}</table>
<h2>Operations</h2><table>{rows(ops)}</table>
<h2>Estimated manual effort avoided</h2>
<p>{d['estimated_manual_minutes_avoided']} minutes
<span class="note">({escape(d['estimate_formula'])})</span></p>
<h2>Audit timeline</h2><ul>{timeline or '<li>No events recorded.</li>'}</ul>
</body></html>"""


def to_pdf(report: RecallReport) -> bytes:
    """Render a simple PDF. Requires reportlab; raises if unavailable."""
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("PDF export requires reportlab") from exc

    d = report.as_dict()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    y = height - 72
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, y, "Rusted Recall — Final Recall Report")
    y -= 28
    c.setFont("Helvetica", 10)
    for label, value in [
        ("Recall event", report.recall_event_id),
        ("Workspace", report.workspace_name),
        ("Source of truth", report.source_of_truth),
        ("Reason", report.reason),
        ("Generated", report.generated_at),
    ]:
        c.drawString(72, y, f"{label}: {value}")
        y -= 16
    y -= 8
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, y, "Impact totals")
    y -= 18
    c.setFont("Helvetica", 10)
    for k, v in d["totals"].items():
        c.drawString(84, y, f"{k}: {v}")
        y -= 14
    c.showPage()
    c.save()
    return buf.getvalue()
