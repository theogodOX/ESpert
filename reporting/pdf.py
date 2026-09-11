"""Dependency-free PDF certificate renderer for the ESPERT MVP."""
from datetime import datetime

def _escape(value):
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def _line_wrap(text, width=92):
    text = str(text or "-")
    return [text[index:index + width] for index in range(0, len(text), width)] or ["-"]

def render_certificate(report):
    lines = [("ESPERT - Automated Compliance Assessment", 16), (f"Report ID: {report['reportId']}", 10), (f"Generated: {datetime.now().astimezone().strftime('%d %b %Y, %H:%M %Z')}", 10), (f"Overall status: {report['status']}    Compliance score: {report['score']}%", 12), ("", 10), ("Verified declarations", 12)]
    lines += [(f"{field['label']}: {field.get('value') or '-'}", 10) for field in report.get("fields", [])]
    lines += [("", 10), ("Rule-level findings", 12)]
    for check in report.get("checks", []):
        lines += [(wrapped, 9) for wrapped in _line_wrap(f"[{check['status']}] {check['rule']} - {check['field']}: {check['message']}")]
    if report.get("defects"):
        lines += [("", 10), ("Defects / violations", 12)]
        for defect in report["defects"]:
            lines += [(wrapped, 9) for wrapped in _line_wrap(f"{defect['rule']} ({defect['section']}): {defect['detected']}")]
    lines += [("", 10), ("Disclaimer: This automated compliance assessment is an aid only. Final regulatory", 8), ("decisions remain subject to competent authority review.", 8)]
    pages, page = [], []
    for line in lines:
        page.append(line)
        if len(page) == 48: pages.append(page); page = []
    if page: pages.append(page)
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for page in pages:
        commands = ["BT", "/F1 16 Tf", "50 790 Td"]
        for text, size in page: commands += [f"/F1 {size} Tf", f"({_escape(text)}) Tj", "0 -15 Td"]
        stream = "\n".join(commands + ["ET"])
        page_ids.append(len(objects) + 1)
        objects += [f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objects) + 2} 0 R >>", f"<< /Length {len(stream.encode('latin-1', 'replace'))} >>\nstream\n{stream}\nendstream"]
    objects[1] = "<< /Type /Pages /Kids [" + " ".join(f"{item} 0 R" for item in page_ids) + f"] /Count {len(page_ids)} >>"
    output, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for index, obj in enumerate(objects, 1): offsets.append(len(output)); output.extend(f"{index} 0 obj\n{obj}\nendobj\n".encode("latin-1", "replace"))
    start = len(output); output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()); output.extend("".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:]).encode()); output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(output)
