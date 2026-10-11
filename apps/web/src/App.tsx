import { useEffect, useReducer, useRef, useState } from "react";
import { reducer, sections, type Section } from "./workflow";
import { getCoverage, getInitialCoverage, pollImport, submitImport } from "./features/import/api";
import { readSavedReplay, requestForecastAndAnomaly } from "./features/reports/api";
import { SectionView } from "./sections";
const apiBaseUrl = import.meta.env.VITE_HACHI_API_BASE_URL?.replace(/\/$/, "") ?? "";
export type Design = "task" | "summary" | "analysis";
const labels: Record<Section, string> = {
  import: "Import & coverage",
  overview: "Overview",
  forecast: "Forecast",
  anomaly: "Baseline deviation",
  symptoms: "Symptoms",
  sleep: "Sleep comparison",
  replay: "Offline replay",
};
function currentSection(): Section {
  const hash = window.location.hash.slice(1);
  return sections.includes(hash as Section) ? (hash as Section) : "import";
}
export default function App() {
  const requestedDesign = new URLSearchParams(window.location.search).get("design");
  const design: Design =
    requestedDesign === "summary" || requestedDesign === "analysis"
      ? requestedDesign
      : "task";
  const [workflow, dispatch] = useReducer(reducer, { kind: "empty" });
  const [section, setSection] = useState<Section>(currentSection);
  const heading = useRef<HTMLHeadingElement>(null);
  const previousKind = useRef(workflow.kind);
  const previousSection = useRef(section);
  const operationId = "operationId" in workflow ? workflow.operationId : null;
  useEffect(() => {
    const navigate = () => setSection(currentSection());
    window.addEventListener("hashchange", navigate);
    return () => window.removeEventListener("hashchange", navigate);
  }, []);
  useEffect(() => {
    if (previousKind.current !== workflow.kind && section === "import")
      heading.current?.focus();
    previousKind.current = workflow.kind;
  }, [workflow.kind]);
  useEffect(() => {
    if (previousSection.current !== section) heading.current?.focus();
    previousSection.current = section;
  }, [section]);
  useEffect(() => {
    if (!operationId) return;
    const controller = new AbortController();
    const { signal } = controller;

    if (workflow.kind === "uploading") {
      submitImport(
        workflow.submission.file,
        workflow.submission.subjectId,
        workflow.submission.timeZone,
        workflow.submission.dataMode,
        signal,
        apiBaseUrl,
      ).then(
        (status) => dispatch({ type: "import-created", operationId, status }),
        (error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError"))
            dispatch({ type: "import-request-failed", operationId, message: error instanceof Error ? error.message : "The import request failed." });
        },
      );
    } else if (workflow.kind === "importing") {
      pollImport(
        workflow.status.import_id,
        signal,
        (status) => dispatch({ type: "import-progress", operationId, status }),
        apiBaseUrl,
      ).then(
        (status) => dispatch({ type: "import-finished", operationId, coverageOperationId: crypto.randomUUID(), status }),
        (error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError"))
            dispatch({ type: "import-request-failed", operationId, message: error instanceof Error ? error.message : "The import could not be read." });
        },
      );
    } else if (workflow.kind === "coverage-loading") {
      const request = workflow.asOf === null
        ? getInitialCoverage(workflow.subject.subjectId, signal, apiBaseUrl)
        : getCoverage(workflow.subject.subjectId, workflow.asOf, signal, apiBaseUrl).then((coverage) => ({ coverage, asOf: workflow.asOf ?? "" }));
      request.then(
        ({ coverage, asOf }) => dispatch({ type: "coverage-finished", operationId, coverage, asOf }),
        (error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError"))
            dispatch({ type: "coverage-request-failed", operationId, message: error instanceof Error ? error.message : "Coverage could not be loaded." });
        },
      );
    } else if (workflow.kind === "reporting") {
      requestForecastAndAnomaly(workflow.subject.subjectId, workflow.asOf, signal, apiBaseUrl).then(
        (reports) => dispatch({ type: "reports-finished", operationId, reports }),
        (error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError"))
            dispatch({ type: "reports-finished", operationId, reports: {
              forecast: { kind: "request-error", message: error instanceof Error ? error.message : "The forecast request failed." },
              anomaly: { kind: "request-error", message: error instanceof Error ? error.message : "The anomaly request failed." },
            } });
        },
      );
    } else if (workflow.kind === "replay-loading") {
      readSavedReplay(apiBaseUrl, signal).then(
        (job) => dispatch({ type: "replay-finished", operationId, job }),
        (error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError"))
            dispatch({ type: "replay-failed", operationId, message: error instanceof Error ? error.message : "The saved replay could not be loaded." });
        },
      );
    }

    return () => controller.abort();
  }, [workflow.kind, operationId, dispatch]);
  const workflowPhase = {
    empty: "",
    uploading: "Sending the export to the local API.",
    importing: "Waiting for import validation.",
    "import-error": "Import failed.",
    "coverage-loading": "Loading coverage.",
    "coverage-error": "Coverage could not be loaded.",
    coverage: "History loaded. Review coverage.",
    reporting: "Forecast and anomaly reports are running.",
    report: "Reports are ready.",
    "replay-loading": "Loading the saved offline replay.",
    "replay-error": "The saved offline replay could not be loaded.",
    "replay-report": "Saved offline replay loaded.",
  }[workflow.kind];
  const phase = section === "symptoms" || section === "sleep" ? "" : workflowPhase;
  const dataMode = workflow.kind === "coverage" || workflow.kind === "report"
    ? workflow.coverage.data_mode
    : workflow.kind === "coverage-error" && workflow.coverage
      ? workflow.coverage.data_mode
        : workflow.kind === "coverage-loading" || workflow.kind === "coverage-error" || workflow.kind === "reporting"
          ? workflow.subject.imported?.data_mode ?? null
          : workflow.kind === "importing"
            ? workflow.status.data_mode
          : workflow.kind === "uploading" || workflow.kind === "import-error"
              ? workflow.submission.dataMode
              : null;
  return (
    <>
      <a
        className="skip"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <div className="workspace" data-design={design}>
        <aside className="sidebar">
          <a className="brand" href="#import" aria-label="Hachi import">
            <span className="brand-mark">h</span>hachi
          </a>
          <nav aria-label="Workspace sections">
            {sections.map((item) => (
              <a
                key={item}
                href={`#${item}`}
                aria-current={section === item ? "page" : undefined}
              >
                {labels[item]}
              </a>
            ))}
          </nav>
        </aside>
        <div className="main-column">
          <header className="topbar">
            <span>Wearable research prototype</span>
            {dataMode ? <span className={`mode-badge mode-${dataMode}`}>{dataMode} data</span> : <span className="mode-badge">No data loaded</span>}
          </header>
          <div className="synthetic-banner">Reports use the selected subject and UTC cutoff. Check source mode and provenance before interpreting results.</div>
          <main id="main" tabIndex={-1}>
            <h1 ref={heading} tabIndex={-1}>
              {labels[section]}
            </h1>
            <p
              className={["uploading", "importing", "coverage-loading", "reporting", "replay-loading"].includes(workflow.kind) ? "phase" : "sr-only"}
              role="status"
              aria-live="polite"
            >
              {phase}
            </p>
            <SectionView
              section={section}
              workflow={workflow}
              dispatch={dispatch}
              design={design}
              apiBaseUrl={apiBaseUrl}
            />
          </main>
        </div>
      </div>
    </>
  );
}
