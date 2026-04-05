"""Evidence boundary for decision lineage, replay context, and audit artifacts."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Callable

from reportlab.lib import colors as rl_colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_compliance_pdf(report: dict[str, Any]) -> bytes:
    """Generate the immutable compliance artifact attached to an approved decision."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    getSampleStyleSheet()
    cyan = rl_colors.HexColor("#00D4FF")
    dark = rl_colors.HexColor("#0a0f1e")
    surface = rl_colors.HexColor("#0f1628")
    white = rl_colors.HexColor("#F0F4FF")
    muted = rl_colors.HexColor("#4A5578")

    title_style = ParagraphStyle("ATitle", fontName="Helvetica-Bold", fontSize=16, textColor=cyan, spaceAfter=4, alignment=TA_LEFT)
    sub_style = ParagraphStyle("ASub", fontName="Helvetica", fontSize=8, textColor=muted, spaceAfter=12, alignment=TA_LEFT)
    section_style = ParagraphStyle("ASec", fontName="Helvetica-Bold", fontSize=9, textColor=cyan, spaceBefore=10, spaceAfter=6)
    label_style = ParagraphStyle("ALbl", fontName="Helvetica", fontSize=8, textColor=muted)

    def two_col(left_label: str, left_val: str, right_label: str, right_val: str, value_color: Any = None) -> Table:
        col = value_color or white
        return Table(
            [[
                Paragraph(left_label, label_style),
                Paragraph(left_val, ParagraphStyle("AV1", fontName="Helvetica-Bold", fontSize=9, textColor=white)),
                Paragraph(right_label, label_style),
                Paragraph(right_val, ParagraphStyle("AV2", fontName="Helvetica-Bold", fontSize=9, textColor=col)),
            ]],
            colWidths=[1.5 * inch, 2.4 * inch, 1.5 * inch, 2.4 * inch],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]),
        )

    def one_row(label: str, value: str, value_color: Any = None) -> Table:
        col = value_color or white
        return Table(
            [[Paragraph(label, label_style), Paragraph(value, ParagraphStyle("AV3", fontName="Helvetica-Bold", fontSize=9, textColor=col))]],
            colWidths=[1.5 * inch, 6.3 * inch],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]),
        )

    story: list[Any] = []
    action = report.get("action", "-")
    symbol = report.get("symbol", "-")
    decision_id = report.get("decision_id", "-")
    notional = report.get("notional", 0)

    story.append(Paragraph("AUREON · COMPLIANCE TRADE REPORT", title_style))
    story.append(Paragraph("Decision lineage artifact generated at governed release.", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=cyan, spaceAfter=12))
    story.append(Paragraph("SECTION I — TRADE IDENTITY", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=muted, spaceAfter=6))

    action_color = "10B981" if action == "BUY" else "EF4444"
    story.append(two_col("ACTION", f'<font color="#{action_color}">{action}</font>', "SYMBOL", symbol))
    story.append(two_col("ASSET CLASS", (report.get("asset_class", "-") or "-").replace("_", " ").upper(), "QUANTITY", f'{report.get("shares", 0):,} shares'))
    story.append(two_col("EXECUTED PRICE", f'${report.get("exec_price", 0):,.2f}', "NOTIONAL", f'${notional:,.0f}'))
    story.append(two_col("SETTLEMENT", report.get("settlement", "T+1"), "AGENT", report.get("agent", "THIFUR_H")))
    story.append(one_row("EXECUTION TIME", report.get("exec_ts", "-")))
    story.append(one_row("DECISION ID", decision_id))
    story.append(one_row("AUTHORITY HASH", report.get("authority_hash", "-"), value_color=muted))
    story.append(Spacer(1, 8))

    story.append(Paragraph("SECTION II — GOVERNANCE BLOCK", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=muted, spaceAfter=6))
    story.append(two_col("DOCTRINE VERSION", report.get("doctrine_version", "-"), "TIER AUTHORITY", report.get("tier_authority", "Tier 1 — Human Authority")))
    story.append(one_row("APPROVED BY", report.get("approved_by", "br@ravelobizdev.com")))
    story.append(one_row("APPROVAL TIME", report.get("approval_ts", "-")))

    gate_data = [["GATE", "LAYER", "STATUS", "DETAIL"]]
    for gate in report.get("gate_results", []):
        status = gate.get("status", "-")
        color = "#10B981" if status == "PASS" else "#F59E0B" if status == "WARN" else "#EF4444"
        gate_data.append([gate.get("gate", "-"), gate.get("layer", "-"), f'<font color="{color}">{status}</font>', (gate.get("detail", "-") or "")[:60]])
    story.append(
        Table(
            gate_data,
            colWidths=[1.6 * inch, 1.1 * inch, 0.65 * inch, 4.45 * inch],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), surface),
                ("TEXTCOLOR", (0, 0), (-1, 0), cyan),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("TEXTCOLOR", (0, 1), (-1, -1), white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [dark, surface]),
                ("GRID", (0, 0), (-1, -1), 0.5, muted),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]),
        )
    )
    story.append(Spacer(1, 8))

    story.append(Paragraph("SECTION III — RISK STATE AT EXECUTION", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=muted, spaceAfter=6))
    story.append(two_col("DRAWDOWN AT EXEC", f'{report.get("drawdown_at_exec", 0):.2f}%', "PORTFOLIO VALUE", f'${report.get("portfolio_value_at_exec", 0):,.0f}'))
    story.append(two_col("CASH BEFORE TRADE", f'${report.get("cash_before", 0):,.0f}', "CASH AFTER TRADE", f'${report.get("cash_after", 0):,.0f}'))
    story.append(two_col("POSITION CONC. PRE", f'{report.get("position_conc_pre", 0):.1f}%', "POSITION CONC. POST", f'{report.get("position_conc_post", 0):.1f}%'))
    story.append(two_col("VAR IMPACT (EST.)", f'{report.get("var_impact", 0):+.2f}%', "POSITIONS HELD POST", f'{report.get("positions_post", 0)}'))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1, color=cyan, spaceAfter=6))
    story.append(
        Paragraph(
            f"Report ID: {report.get('report_id', '-')} · Generated: {report.get('generated_ts', '-')} · Aureon DSOR replay artifact",
            ParagraphStyle("AFooter", fontName="Helvetica", fontSize=6.5, textColor=muted, alignment=TA_CENTER),
        )
    )

    doc.build(story)
    return buf.getvalue()


def build_trade_report(
    *,
    decision: dict[str, Any],
    exec_price: float,
    authority_hash: str,
    gate_results: list[dict[str, Any]],
    portfolio_before: dict[str, Any],
    doctrine_version: str,
    instrument_ref: dict[str, dict[str, Any]],
    entity_lei: str,
    macro_snapshot_fn: Callable[[], dict[str, Any]],
    ofr_snapshot_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Build the execution-linked evidence package for replay and audit."""
    now_utc = datetime.now(timezone.utc)
    exec_ts = now_utc.isoformat()
    report_id = f"CTR-{decision['id'][-8:]}"
    is_crypto = decision["symbol"] in {"BTC", "ETH", "SOL"}
    settlement = "T+0" if is_crypto else "T+1"
    macro_snapshot = macro_snapshot_fn()
    ofr_snapshot = ofr_snapshot_fn(macro_snapshot)

    notional = decision["shares"] * exec_price
    action_sign = -1 if decision["action"] == "BUY" else 1
    cash_after = portfolio_before["cash"] + (action_sign * notional)
    pv = portfolio_before["portfolio_value"]
    n_positions_pre = portfolio_before["n_positions"]
    n_positions_post = n_positions_pre + 1 if decision["action"] == "BUY" else max(0, n_positions_pre - 1)
    conc_pre = (notional / pv * 100) if pv > 0 else 0
    var_impact = (-(notional / pv * 0.08 * 100) if decision["action"] == "BUY" else (notional / pv * 0.05 * 100)) if pv > 0 else 0

    sym = decision["symbol"]
    ref = instrument_ref.get(sym, {})
    report = {
        "report_id": report_id,
        "decision_id": decision["id"],
        "generated_ts": exec_ts,
        "exec_ts": exec_ts,
        "approval_ts": exec_ts,
        "action": decision["action"],
        "symbol": sym,
        "isin": ref.get("isin"),
        "cusip": ref.get("cusip"),
        "fix_type": ref.get("fix_type"),
        "fix_product": ref.get("fix_product"),
        "mic": ref.get("mic"),
        "currency": ref.get("currency", "USD"),
        "asset_class": decision["asset_class"],
        "shares": decision["shares"],
        "exec_price": round(exec_price, 2),
        "notional": round(notional, 2),
        "settlement": settlement,
        "agent": "THIFUR_H",
        "authority_hash": authority_hash,
        "entity_lei": entity_lei,
        "doctrine_version": doctrine_version,
        "tier_authority": "Tier 1 — Human Authority",
        "approved_by": "br@ravelobizdev.com",
        "gate_results": gate_results,
        "frameworks_active": ["MiFID II Art.17/RTS6", "SR 11-7", "Basel III", "DORA Art.28", "Dodd-Frank 4a(1)"],
        "drawdown_at_exec": portfolio_before["drawdown"],
        "portfolio_value_at_exec": pv,
        "cash_before": portfolio_before["cash"],
        "cash_after": round(cash_after, 2),
        "position_conc_pre": round(conc_pre, 2),
        "position_conc_post": round(conc_pre, 2),
        "var_impact": round(var_impact, 4),
        "positions_post": n_positions_post,
        "macro_regime_at_exec": macro_snapshot.get("macro_regime"),
        "ofr_fsi_at_exec": ofr_snapshot.get("fsi_value"),
        "ofr_band_at_exec": ofr_snapshot.get("fsi_band"),
        "systemic_overlay_source": ofr_snapshot.get("source"),
    }
    try:
        report["pdf_bytes"] = generate_compliance_pdf(report)
    except Exception as exc:
        print(f"[AUREON] PDF generation failed: {exc}")
        report["pdf_bytes"] = None
    return report
