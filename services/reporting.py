from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from datetime import datetime


def _start_doc(filename, title):
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4
    c.setTitle(title)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, height - 20 * mm, title)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, height - 26 * mm, f"Generated at: {datetime.utcnow().isoformat()} UTC")
    return c, width, height


def generate_compliance_report(filename, project_id, design_id, compliance, summary):
    """
    Very simple tabular compliance report as PDF (FR-37/27 backend).
    """
    c, width, height = _start_doc(
        filename, f"Nirmaan.AI - Compliance Report (Project {project_id}, Design {design_id})"
    )

    y = height - 40 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, f"Overall status: {summary.get('overall_status') if summary else 'N/A'}")
    y -= 8 * mm

    if summary:
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, f"Hard failed: {summary['hard_failed']}, "
                                 f"Soft failed: {summary['soft_failed']}, "
                                 f"Advisory failed: {summary['advisory_failed']}")
        y -= 10 * mm

    # Table header
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Code")
    c.drawString(60 * mm, y, "Category")
    c.drawString(95 * mm, y, "Type")
    c.drawString(120 * mm, y, "Status")
    y -= 6 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 4 * mm

    c.setFont("Helvetica", 8)
    for r in compliance or []:
        if y < 20 * mm:
            c.showPage()
            c, width, height = _start_doc(filename, "Nirmaan.AI - Compliance Report (cont.)")
            y = height - 40 * mm
            c.setFont("Helvetica", 8)

        code = r.get('rule_code', '')
        category = r.get('category', '')
        r_type = r.get('rule_type', '')
        status = "PASS" if r.get('passed') else "FAIL"

        c.drawString(20 * mm, y, str(code)[:20])
        c.drawString(60 * mm, y, str(category)[:20])
        c.drawString(95 * mm, y, str(r_type)[:12])
        c.drawString(120 * mm, y, status)
        y -= 5 * mm

    c.showPage()
    c.save()
    return filename


def generate_cost_report(filename, project_id, items, total_amount):
    """
    Simple BOQ / cost summary as PDF (FR-37 backend).
    """
    c, width, height = _start_doc(
        filename, f"Nirmaan.AI - Cost Report (Project {project_id})"
    )

    y = height - 40 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, f"Total amount: {total_amount:,.2f}")
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Category")
    c.drawString(55 * mm, y, "Item")
    c.drawString(105 * mm, y, "Qty")
    c.drawString(130 * mm, y, "Rate")
    c.drawString(155 * mm, y, "Amount")
    y -= 6 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 4 * mm

    c.setFont("Helvetica", 8)
    for i in items or []:
        if y < 20 * mm:
            c.showPage()
            c, width, height = _start_doc(filename, "Nirmaan.AI - Cost Report (cont.)")
            y = height - 40 * mm
            c.setFont("Helvetica", 8)

        c.drawString(20 * mm, y, str(i.get('category', ''))[:20])
        c.drawString(55 * mm, y, f"{i.get('item_code', '')}: {i.get('description', '')[:30]}")
        c.drawRightString(120 * mm, y, f"{i.get('quantity', 0):.2f}")
        c.drawRightString(145 * mm, y, f"{i.get('rate', 0):.2f}")
        c.drawRightString(190 * mm, y, f"{i.get('amount', 0):.2f}")
        y -= 5 * mm

    c.showPage()
    c.save()
    return filename

