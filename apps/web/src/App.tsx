import { useEffect, useReducer, useRef, useState } from "react";
import { reducer, sections, type Section } from "./workflow";
import { importFixture, reportFixture } from "./fixtures";
import { SectionView } from "./sections";
export type Design = "task" | "summary" | "analysis";
const labels: Record<Section, string> = {
  import: "Import & coverage",
  overview: "Overview",
  forecast: "Forecast",
  anomaly: "Baseline deviation",
  symptoms: "Symptoms",
  sleep: "Sleep comparison",
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
    if (workflow.kind !== "importing" && workflow.kind !== "reporting") return;
    const timer = window.setTimeout(() => {
      if (workflow.kind === "importing")
        dispatch({
          type: "imported",
          result: importFixture(workflow.scenario),
        });
      else if (workflow.history.scenario === "report-error")
        dispatch({ type: "report-failed" });
      else
        dispatch({
          type: "reported",
          report: reportFixture(workflow.history, workflow.cutoff),
        });
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [workflow]);
  const workflowPhase = {
    empty: "",
    importing: "Loading synthetic history.",
    "no-observations": "No observations found.",
    "import-error": "Import failed.",
    coverage: "History loaded. Review coverage.",
    cutoff: "Coverage acknowledged. Select a supported UTC cutoff.",
    reporting: "Preparing synthetic report.",
    "report-error": "Report failed.",
    report: "Synthetic report ready.",
  }[workflow.kind];
  const phase = section === "symptoms" || section === "sleep" ? "" : workflowPhase;
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
            <span className="badge">SYNTHETIC DATA ONLY</span>
          </header>
          <div className="synthetic-banner">
            No model runs or personal data.
          </div>
          <main id="main" tabIndex={-1}>
            <h1 ref={heading} tabIndex={-1}>
              {labels[section]}
            </h1>
            <p
              className={workflow.kind === "importing" || workflow.kind === "reporting" ? "phase" : "sr-only"}
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
            />
          </main>
        </div>
      </div>
    </>
  );
}
