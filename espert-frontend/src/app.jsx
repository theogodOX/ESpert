import React, { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_URL || "";

/* -------------------------------------------------------------------------- */
/*                                    APP                                     */
/* -------------------------------------------------------------------------- */

export default function App() {
  const [step, setStep] = useState(1);

  const [selectedFile, setSelectedFile] = useState(null);
  const [preview, setPreview] = useState(null);

  const [analyzing, setAnalyzing] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [progress, setProgress] = useState(0);
  const [analysisStage, setAnalysisStage] = useState("");

  const [inspectionId, setInspectionId] = useState("");
  const [detectedFields, setDetectedFields] = useState([]);
  const [complianceChecks, setComplianceChecks] = useState([]);
  const [certificate, setCertificate] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    return () => {
      if (preview) {
        URL.revokeObjectURL(preview);
      }
    };
  }, [preview]);

  /* ---------------------------------------------------------------------- */
  /* FILE UPLOAD                                                            */
  /* ---------------------------------------------------------------------- */

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];

    if (!file) return;

    if (!file.type.startsWith("image/")) {
      setError("Please upload a valid packaging image (JPG, PNG, WebP).");
      return;
    }

    setSelectedFile(file);

    if (preview) {
      URL.revokeObjectURL(preview);
    }

    setPreview(URL.createObjectURL(file));

    setError("");
    setProgress(0);
    setCertificate(null);
    setInspectionId("");
    setDetectedFields([]);
    setComplianceChecks([]);
  };

  /* ---------------------------------------------------------------------- */
  /* FIELD EDITING                                                          */
  /* ---------------------------------------------------------------------- */

  const handleFieldChange = (key, newValue) => {
    setDetectedFields((prev) =>
      prev.map((field) =>
        field.key === key ? { ...field, value: newValue } : field
      )
    );
  };

  /* ---------------------------------------------------------------------- */
  /* REAL BACKEND ANALYSIS FLOW                                             */
  /* ---------------------------------------------------------------------- */

  const startAnalysis = async () => {
    if (!selectedFile) {
      setError("Please upload a packaging image before starting the inspection.");
      return;
    }

    setError("");
    setAnalyzing(true);
    setProgress(5);
    setAnalysisStage("Uploading packaging artwork...");

    // Smooth stage indicator while real backend executes concurrent inspection
    const stages = [
      { threshold: 12, text: "Initializing ESPERT inspection engine..." },
      { threshold: 25, text: "Running dual inspection (PaddleOCR & Groq Vision)..." },
      { threshold: 50, text: "Detecting text regions and visual statutory declarations..." },
      { threshold: 72, text: "Reconciling evidence and structuring declarations..." },
      { threshold: 88, text: "Running Legal Metrology compliance checks..." },
    ];

    let currentProgress = 5;
    const progressTimer = setInterval(() => {
      currentProgress = Math.min(
        currentProgress + (currentProgress < 30 ? 4 : currentProgress < 70 ? 2 : 1),
        92
      );
      setProgress(Math.round(currentProgress));
      const activeStage = stages.slice().reverse().find((s) => currentProgress >= s.threshold);
      if (activeStage) {
        setAnalysisStage(activeStage.text);
      }
    }, 800);

    try {
      const formData = new FormData();
      formData.append("image", selectedFile);

      const res = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        let errMsg = "Analysis failed. Please check server logs.";
        try {
          const errJson = await res.json();
          errMsg = errJson.detail || errMsg;
        } catch (_) {}
        throw new Error(errMsg);
      }

      const data = await res.json();

      clearInterval(progressTimer);
      setProgress(100);
      setAnalysisStage("Inspection complete. Preparing declaration review...");

      setInspectionId(data.reportId || "");
      setDetectedFields(data.fields || []);
      setComplianceChecks(data.checks || []);

      await new Promise((resolve) => setTimeout(resolve, 500));
      setAnalyzing(false);
      setStep(2);
    } catch (err) {
      clearInterval(progressTimer);
      setAnalyzing(false);
      setError(err.message || "Failed to analyze the packaging image.");
    }
  };

  /* ---------------------------------------------------------------------- */
  /* FINALIZE & GENERATE CERTIFICATE                                        */
  /* ---------------------------------------------------------------------- */

  const generateCertificate = async () => {
    if (!inspectionId) {
      setError("No active inspection found. Please re-analyze the image.");
      return;
    }

    try {
      setError("");
      setFinalizing(true);

      const officerValues = {};
      for (const field of detectedFields) {
        officerValues[field.key] = field.value;
      }

      const res = await fetch(`${API_BASE}/api/inspections/${inspectionId}/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: officerValues }),
      });

      if (!res.ok) {
        let errMsg = "Failed to finalize inspection.";
        try {
          const errJson = await res.json();
          errMsg = errJson.detail || errMsg;
        } catch (_) {}
        throw new Error(errMsg);
      }

      const finalizedReport = await res.json();
      setCertificate({
        ...finalizedReport,
        generatedAt: new Date().toLocaleString(),
      });
      setComplianceChecks(finalizedReport.checks || []);
      if (finalizedReport.fields) {
        setDetectedFields(finalizedReport.fields);
      }
      setFinalizing(false);
      setStep(3);
    } catch (err) {
      setFinalizing(false);
      setError(err.message || "Failed to finalize inspection.");
    }
  };

  /* ---------------------------------------------------------------------- */
  /* DOWNLOAD PDF CERTIFICATE                                               */
  /* ---------------------------------------------------------------------- */

  const downloadCertificatePdf = async () => {
    if (!certificate) {
      window.print();
      return;
    }

    try {
      setDownloadingPdf(true);
      const res = await fetch(`${API_BASE}/api/certificates/pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(certificate),
      });

      if (!res.ok) {
        setDownloadingPdf(false);
        window.print();
        return;
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${certificate.reportId || "ESPERT-CERTIFICATE"}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      setDownloadingPdf(false);
    } catch (_) {
      setDownloadingPdf(false);
      window.print();
    }
  };

  const steps = [
    {
      id: 1,
      label: "Upload Packaging",
    },
    {
      id: 2,
      label: "Automated Declaration Audit",
    },
    {
      id: 3,
      label: "Regulatory Certificate",
    },
  ];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">

      {/* HEADER */}

      <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur">

        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">

          <div className="flex items-center gap-4">

            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-xl font-bold text-white shadow-lg shadow-blue-200">
              E
            </div>

            <div>
              <h1 className="text-2xl font-bold tracking-wide text-slate-900">
                ESPERT
              </h1>

              <p className="text-sm text-slate-500">
                Legal Metrology Compliance & Verification Engine
              </p>
            </div>

          </div>

          <div className="hidden items-center gap-3 rounded-full border border-blue-100 bg-blue-50 px-5 py-2 text-sm font-medium text-blue-700 md:flex">

            <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-500" />

            Automated Inspection Active

          </div>

        </div>

      </header>

      <main className="mx-auto max-w-7xl px-6 py-10">

        {/* STEP INDICATOR */}

        <div className="mb-12 grid grid-cols-1 gap-4 md:grid-cols-3">

          {steps.map((item) => {
            const active = step === item.id;
            const completed = step > item.id;

            return (
              <div
                key={item.id}
                className={`flex items-center justify-center gap-3 rounded-xl border px-5 py-4 text-sm font-semibold transition-all duration-500 ${
                  active
                    ? "border-blue-500 bg-blue-600 text-white shadow-lg shadow-blue-100"
                    : completed
                    ? "border-blue-200 bg-blue-50 text-blue-700"
                    : "border-slate-200 bg-white text-slate-400"
                }`}
              >

                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full text-xs ${
                    active
                      ? "bg-white text-blue-600"
                      : completed
                      ? "bg-blue-600 text-white"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {completed ? "✓" : item.id}
                </span>

                {item.label}

              </div>
            );
          })}

        </div>

        {/* ================================================================ */}
        {/* STEP 1 - UPLOAD                                                  */}
        {/* ================================================================ */}

        {step === 1 && (
          <section className="animate-fadeIn grid gap-10 lg:grid-cols-2 lg:items-center">

            <div>

              <div className="mb-6 inline-flex items-center rounded-full bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700">
                Automated Packaging Inspection
              </div>

              <h2 className="max-w-xl text-4xl font-bold leading-tight text-slate-900 md:text-5xl">
                Upload a packaging image.
                <br />
                ESPERT detects the declarations.
              </h2>

              <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-600">
                The inspection engine extracts visible product declarations,
                organizes statutory information and evaluates the packaging
                against configured Legal Metrology requirements.
              </p>

              <div className="mt-8 grid gap-4 sm:grid-cols-3">

                <Feature
                  number="01"
                  title="Image Analysis"
                  description="Packaging artwork is processed."
                />

                <Feature
                  number="02"
                  title="OCR Extraction"
                  description="Visible declarations are detected."
                />

                <Feature
                  number="03"
                  title="Compliance"
                  description="Statutory checks are evaluated."
                />

              </div>

            </div>

            {/* UPLOAD CARD */}

            <div className="rounded-3xl border border-slate-200 bg-white p-7 shadow-xl shadow-slate-200/60">

              <h3 className="text-xl font-bold text-slate-900">
                Upload Packaging Image
              </h3>

              <p className="mt-2 text-sm text-slate-500">
                JPG, PNG and WebP packaging images are supported.
              </p>

              <label className="mt-6 flex min-h-[330px] cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-blue-200 bg-blue-50/40 p-6 transition hover:border-blue-400 hover:bg-blue-50">

                {preview ? (
                  <div className="w-full">

                    <img
                      src={preview}
                      alt="Uploaded packaging"
                      className="mx-auto max-h-[280px] rounded-xl object-contain shadow-lg"
                    />

                    <p className="mt-5 text-center text-sm font-medium text-slate-600">
                      {selectedFile?.name}
                    </p>

                    <p className="mt-1 text-center text-xs text-blue-600">
                      Image ready for automated inspection
                    </p>

                  </div>
                ) : (
                  <>
                    <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-blue-600 text-3xl text-white shadow-lg shadow-blue-200">
                      ↑
                    </div>

                    <h4 className="mt-6 text-lg font-bold text-slate-800">
                      Select Packaging Image
                    </h4>

                    <p className="mt-2 text-center text-sm text-slate-500">
                      Click to browse your product packaging image.
                    </p>
                  </>
                )}

                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  className="hidden"
                  onChange={handleFileChange}
                />

              </label>

              {error && (
                <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                  {error}
                </div>
              )}

              <button
                onClick={startAnalysis}
                className="mt-6 w-full rounded-xl bg-blue-600 px-6 py-4 font-semibold text-white shadow-lg shadow-blue-200 transition-all hover:-translate-y-0.5 hover:bg-blue-700"
              >
                Start Automated Inspection →
              </button>

            </div>

          </section>
        )}

        {/* ================================================================ */}
        {/* STEP 2 - AUTOMATED REVIEW                                       */}
        {/* ================================================================ */}

        {step === 2 && (
          <section className="animate-fadeIn rounded-3xl border border-slate-200 bg-white p-7 shadow-xl shadow-slate-100 md:p-10">

            <div className="border-b border-slate-200 pb-7">

              <div className="flex flex-col justify-between gap-5 md:flex-row md:items-start">

                <div>

                  <div className="mb-3 inline-flex rounded-full bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700">
                    Automated Extraction Complete
                  </div>

                  <h2 className="text-3xl font-bold text-slate-900">
                    Detected Product Declarations
                  </h2>

                  <p className="mt-3 max-w-3xl leading-relaxed text-slate-500">
                    ESPERT automatically extracted the following declarations
                    from the uploaded packaging image.
                  </p>

                </div>

                <div className="rounded-2xl border border-emerald-100 bg-emerald-50 px-5 py-4">

                  <p className="text-xs font-semibold uppercase tracking-wider text-emerald-600">
                    Inspection Result
                  </p>

                  <p className="mt-1 font-bold text-emerald-700">
                    Extraction Successful
                  </p>

                </div>

              </div>

            </div>

            {/* DETECTED FIELDS */}

            <div className="mt-8 grid gap-6 md:grid-cols-2">

              {detectedFields.map((field) => (
                <DetectedField
                  key={field.key}
                  label={field.label}
                  value={field.value}
                  editable={field.editable}
                  onChange={(val) => handleFieldChange(field.key, val)}
                />
              ))}

            </div>

            {/* ACTION */}

            <div className="mt-10 flex flex-col gap-4 border-t border-slate-200 pt-8 sm:flex-row">

              <button
                onClick={() => setStep(1)}
                className="rounded-xl border border-slate-300 bg-white px-7 py-4 font-semibold text-slate-600 transition hover:bg-slate-50"
              >
                ← Upload Another Image
              </button>

              <button
                onClick={generateCertificate}
                disabled={finalizing}
                className="flex-1 rounded-xl bg-blue-600 px-7 py-4 font-semibold text-white shadow-lg shadow-blue-200 transition hover:-translate-y-0.5 hover:bg-blue-700 disabled:opacity-75"
              >
                {finalizing ? "Finalizing Inspection..." : "Generate Compliance Certificate →"}
              </button>

            </div>

          </section>
        )}

        {/* ================================================================ */}
        {/* STEP 3 - CERTIFICATE                                             */}
        {/* ================================================================ */}

        {step === 3 && certificate && (
          <div className="animate-fadeIn grid gap-8 lg:grid-cols-[1.5fr_1fr]">

            {/* CERTIFICATE */}

            <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl shadow-slate-100">

              <div className="border-b-4 border-blue-600 p-10">

                <div className="flex items-start justify-between gap-5">

                  <div>

                    <p className="text-sm font-bold uppercase tracking-[0.2em] text-blue-600">
                      ESPERT Regulatory Verification System
                    </p>

                    <h2 className="mt-4 text-4xl font-bold text-slate-900">
                      Compliance Inspection Certificate
                    </h2>

                    <p className="mt-4 text-slate-500">
                      Automated Legal Metrology Packaging Review
                    </p>

                  </div>

                  <div
                    className={`rounded-2xl px-5 py-4 text-center text-white ${
                      certificate.status === "COMPLIANT"
                        ? "bg-emerald-600"
                        : certificate.status === "NON_COMPLIANT"
                        ? "bg-red-600"
                        : "bg-amber-600"
                    }`}
                  >

                    <p className="text-xs uppercase tracking-wider text-white/80">
                      Status
                    </p>

                    <p className="mt-1 font-bold">
                      {certificate.status || "COMPLIANT"}
                    </p>

                  </div>

                </div>

              </div>

              <div className="space-y-8 p-10">

                <div className="grid gap-6 sm:grid-cols-2">

                  <CertificateItem
                    label="Report ID"
                    value={certificate.reportId}
                  />

                  <CertificateItem
                    label="Generated On"
                    value={certificate.generatedAt}
                  />

                  <CertificateItem
                    label="Compliance Score"
                    value={`${certificate.score ?? 100}%`}
                  />

                  <CertificateItem
                    label="Inspection Result"
                    value={certificate.verdict || "Automated Review Complete"}
                  />

                </div>

                <div>

                  <h3 className="border-b border-slate-200 pb-3 text-lg font-bold text-slate-900">
                    Compliance Evaluation Summary
                  </h3>

                  <div className="mt-5 space-y-3">

                    {complianceChecks.map((check) => (
                      <div
                        key={check.rule || check.id}
                        className="flex items-center justify-between rounded-xl border border-slate-100 bg-slate-50 px-5 py-4"
                      >

                        <div>

                          <p className="font-semibold text-slate-800">
                            {check.field}
                          </p>

                          <p className="mt-1 text-sm text-slate-500">
                            {check.rule} · {check.message}
                          </p>

                        </div>

                        <span
                          className={`rounded-full px-3 py-1 text-xs font-bold ${
                            check.status === "PASS"
                              ? "bg-emerald-100 text-emerald-700"
                              : check.status === "FAIL"
                              ? "bg-red-100 text-red-700"
                              : "bg-amber-100 text-amber-700"
                          }`}
                        >
                          {check.status}
                        </span>

                      </div>
                    ))}

                  </div>

                </div>

                <div className="rounded-2xl border border-blue-100 bg-blue-50 p-6">

                  <p className="font-semibold text-blue-900">
                    Automated Inspection Notice
                  </p>

                  <p className="mt-2 text-sm leading-relaxed text-blue-700">
                    This report summarizes declarations automatically detected
                    from the submitted packaging artwork and evaluated through
                    the ESPERT compliance workflow.
                  </p>

                </div>

              </div>

            </section>

            {/* SIDEBAR */}

            <aside className="h-fit rounded-3xl border border-slate-200 bg-white p-8 shadow-lg shadow-slate-100">

              <p className="text-sm font-bold uppercase tracking-wider text-slate-400">
                Inspection Summary
              </p>

              <div className="mt-6 flex h-40 items-center justify-center">

                <div className="flex h-32 w-32 items-center justify-center rounded-full border-[10px] border-blue-100">

                  <div className="text-center">

                    <p className="text-4xl font-bold text-blue-600">
                      {certificate.score ?? 100}
                    </p>

                    <p className="text-sm text-slate-500">
                      SCORE
                    </p>

                  </div>

                </div>

              </div>

              <div className="mt-8 space-y-4">

                <SummaryRow
                  label="Rules Evaluated"
                  value={complianceChecks.length}
                />

                <SummaryRow
                  label="Declarations Detected"
                  value={detectedFields.filter((f) => f.value).length}
                />

                <SummaryRow
                  label="Passed Checks"
                  value={certificate.passed ?? complianceChecks.filter((c) => c.status === "PASS").length}
                />

                <SummaryRow
                  label="Critical Violations"
                  value={certificate.violations ?? complianceChecks.filter((c) => c.status === "FAIL").length}
                />

              </div>

              <button
                onClick={downloadCertificatePdf}
                disabled={downloadingPdf}
                className="mt-8 w-full rounded-xl bg-blue-600 px-5 py-4 font-semibold text-white shadow-lg shadow-blue-200 transition hover:bg-blue-700 disabled:opacity-75"
              >
                {downloadingPdf ? "Generating Official PDF..." : "Download / Print Certificate"}
              </button>

              <button
                onClick={() => {
                  setStep(1);
                  setSelectedFile(null);
                  setPreview(null);
                  setProgress(0);
                  setError("");
                  setCertificate(null);
                  setInspectionId("");
                  setDetectedFields([]);
                  setComplianceChecks([]);
                }}
                className="mt-4 w-full rounded-xl border border-slate-300 bg-white px-5 py-4 font-semibold text-slate-600 transition hover:bg-slate-50"
              >
                Start New Inspection
              </button>

            </aside>

          </div>
        )}

      </main>

      {/* ANALYSIS OVERLAY */}

      {analyzing && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/40 p-6 backdrop-blur-md">

          <div className="w-full max-w-2xl animate-scaleIn rounded-3xl bg-white p-10 shadow-2xl">

            <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-2xl bg-blue-600 text-3xl font-bold text-white shadow-xl shadow-blue-200">
              E
            </div>

            <h2 className="mt-8 text-center text-3xl font-bold text-slate-900">
              Automated Inspection in Progress
            </h2>

            <p className="mt-3 text-center text-slate-500">
              ESPERT is analyzing declarations visible on the submitted
              packaging image.
            </p>

            <div className="mt-10">

              <div className="mb-3 flex justify-between gap-5 text-sm font-medium">

                <span className="text-slate-500">
                  {analysisStage}
                </span>

                <span className="text-blue-600">
                  {progress}%
                </span>

              </div>

              <div className="h-3 overflow-hidden rounded-full bg-slate-100">

                <div
                  className="h-full rounded-full bg-blue-600 transition-all duration-700 ease-out"
                  style={{
                    width: `${progress}%`,
                  }}
                />

              </div>

            </div>

            <div className="mt-10 space-y-4">

              <AnalysisRow
                active={progress >= 18}
                label="Inspection engine initialized"
              />

              <AnalysisRow
                active={progress >= 32}
                label="Packaging text regions detected"
              />

              <AnalysisRow
                active={progress >= 48}
                label="OCR declaration extraction completed"
              />

              <AnalysisRow
                active={progress >= 78}
                label="Statutory declarations classified"
              />

              <AnalysisRow
                active={progress >= 100}
                label="Compliance inspection completed"
              />

            </div>

          </div>

        </div>
      )}

      {/* FOOTER */}

      <footer className="mt-20 border-t border-slate-200 bg-white">

        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-6 py-7 text-sm text-slate-500 md:flex-row md:items-center md:justify-between">

          <p>
            © 2026 ESPERT Compliance Engine
          </p>

          <p>
            Legal Metrology • Packaged Commodities • FSSAI Verification
          </p>

        </div>

      </footer>

      <style>{`
        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(12px);
          }

          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes scaleIn {
          from {
            opacity: 0;
            transform: scale(0.96);
          }

          to {
            opacity: 1;
            transform: scale(1);
          }
        }

        .animate-fadeIn {
          animation: fadeIn 0.5s ease-out;
        }

        .animate-scaleIn {
          animation: scaleIn 0.35s ease-out;
        }

        @media print {
          header,
          footer,
          button {
            display: none !important;
          }

          body {
            background: white !important;
          }
        }
      `}</style>

    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*                              COMPONENTS                                    */
/* -------------------------------------------------------------------------- */

function Feature({ number, title, description }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">

      <span className="text-sm font-bold text-blue-600">
        {number}
      </span>

      <h4 className="mt-3 font-bold text-slate-800">
        {title}
      </h4>

      <p className="mt-2 text-sm leading-relaxed text-slate-500">
        {description}
      </p>

    </div>
  );
}

function DetectedField({ label, value, editable, onChange }) {
  const displayVal = Array.isArray(value) ? value.join(", ") : (value ?? "");
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 transition-all hover:-translate-y-0.5 hover:border-blue-200 hover:bg-white hover:shadow-md">

      <div className="flex items-center justify-between gap-3">

        <p className="text-sm font-bold uppercase tracking-wide text-slate-600">
          {label}
        </p>

        <span
          className={`rounded-md border px-3 py-1 text-xs font-bold ${
            editable
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : displayVal
              ? "border-blue-100 bg-blue-50 text-blue-600"
              : "border-slate-200 bg-slate-100 text-slate-500"
          }`}
        >
          {editable ? "EDITABLE" : displayVal ? "DETECTED" : "NOT DETECTED"}
        </span>

      </div>

      <div className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-800">
        {editable ? (
          <input
            type="text"
            value={displayVal}
            onChange={(e) => onChange?.(e.target.value)}
            placeholder="Enter declaration value..."
            className="w-full bg-transparent text-sm font-medium text-slate-800 outline-none placeholder:text-slate-400"
          />
        ) : (
          displayVal || <span className="italic text-slate-400">Not detected</span>
        )}
      </div>

    </div>
  );
}

function AnalysisRow({ active, label }) {
  return (
    <div className="flex items-center gap-4">

      <div
        className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
          active
            ? "bg-blue-600 text-white"
            : "bg-slate-100 text-slate-400"
        }`}
      >
        {active ? "✓" : "○"}
      </div>

      <p
        className={`text-sm font-medium ${
          active
            ? "text-slate-800"
            : "text-slate-400"
        }`}
      >
        {label}
      </p>

    </div>
  );
}

function CertificateItem({ label, value }) {
  const displayVal = Array.isArray(value) ? value.join(", ") : (value ?? "—");
  return (
    <div>

      <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
        {label}
      </p>

      <p className="mt-2 break-words font-semibold text-slate-800">
        {displayVal}
      </p>

    </div>
  );
}

function SummaryRow({ label, value }) {
  const displayVal = Array.isArray(value) ? value.join(", ") : value;
  return (
    <div className="flex items-center justify-between border-b border-slate-100 pb-4">

      <span className="text-sm text-slate-500">
        {label}
      </span>

      <span className="font-bold text-slate-800">
        {displayVal}
      </span>

    </div>
  );
}