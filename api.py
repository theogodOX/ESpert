import shutil
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from backend import ProductAnalysisBackend
from reporting.pdf import render_certificate

app = FastAPI(title="ESPERT API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
backend_engine = None
active_inspections = {}
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

def get_backend_engine():
    global backend_engine
    if backend_engine is None:
        backend_engine = ProductAnalysisBackend()
    return backend_engine


def format_report(compliance, report_id):
    status_map = {"PASS": "COMPLIANT", "FAIL": "NON_COMPLIANT", "REVIEW_REQUIRED": "NEEDS_REVIEW"}
    checks, defects = [], []
    for index, check in enumerate(compliance.checks, 1):
        check_val = ", ".join(str(v) for v in check.value) if isinstance(check.value, list) else (str(check.value) if check.value is not None else "Not Found")
        checks.append({"id": index, "field": check.title, "rule": check.rule_id, "val": check_val, "status": check.status, "message": check.message, "section": check.statutory_section})
        if check.status == "FAIL":
            defects.append({"id": f"v{index}", "title": f"Failed: {check.title}", "field": check.title, "rule": check.rule_id, "severity": "HIGH", "detected": check.message, "recommendation": "Review packaging declarations to ensure compliance.", "section": check.statutory_section or "Section 36(1)"})
    total = compliance.passed + compliance.failed + compliance.review_required + compliance.not_found
    return {"reportId": report_id, "score": round(100 * compliance.passed / total) if total else 0,
            "status": status_map.get(compliance.overall_status, "NEEDS_REVIEW"), "passed": compliance.passed,
            "warnings": compliance.review_required + compliance.not_found, "violations": compliance.failed,
            "checks": checks, "defects": defects,
            "fields": [{"key": item.key, "label": item.label, "value": ", ".join(str(v) for v in item.value) if isinstance(item.value, list) else (item.value or ""), "required": item.required, "editable": item.editable} for item in compliance.field_status],
            "verdict": f"Analysis complete. Found {compliance.failed} violations."}


@app.post("/api/analyze")
def analyze_image(image: UploadFile = File(...)):
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Upload a JPEG, PNG, or WebP image.")
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="espert_", suffix=ALLOWED_TYPES[image.content_type], delete=False) as handle:
            path = handle.name
            shutil.copyfileobj(image.file, handle)
        result = get_backend_engine().analyze_product(image_path=path, label_type="food")
        inspection_id = f"ESPERT-INS-{uuid.uuid4().hex[:10].upper()}"
        payload = format_report(result.compliance, inspection_id)
        active_inspections[inspection_id] = asdict(result.product_data)
        return payload
    except Exception as exc:
        raise HTTPException(500, f"Analysis failed: {exc}") from exc
    finally:
        if path:
            Path(path).unlink(missing_ok=True)
        image.file.close()


@app.post("/api/inspections/{inspection_id}/finalize")
def finalize(inspection_id: str, payload: dict):
    original = active_inspections.get(inspection_id)
    if original is None:
        raise HTTPException(404, "Inspection not found. Re-analyze the image before finalizing.")
    values = payload.get("fields")
    if not isinstance(values, dict):
        raise HTTPException(422, "fields must be an object keyed by declaration name.")
    try:
        product, compliance = get_backend_engine().finalize_product(original, values)
        report = format_report(compliance, f"ESPERT-RPT-{uuid.uuid4().hex[:10].upper()}")
        active_inspections[inspection_id] = asdict(product)
        return report
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/certificates/pdf")
def certificate_pdf(report: dict):
    if not str(report.get("reportId", "")).startswith("ESPERT-RPT-") or not report.get("checks"):
        raise HTTPException(422, "A finalized report is required to generate a certificate.")
    return Response(render_certificate(report), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{report["reportId"]}.pdf"'})
