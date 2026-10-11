import { useEffect, useReducer, useRef, useState } from "react";
import { reducer, sections, type Section } from "./workflow";
import { importFixture, reportFixture } from "./fixtures";
import { SectionView } from "./sections";
function currentSection(): Section {
  const hash = window.location.hash.slice(1);
  return sections.includes(hash as Section) ? (hash as Section) : "import";
}
export default function App() {
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
    empty: "Ready to load a synthetic history.",
    importing: "Loading synthetic history.",
    "no-observations": "No observations found.",
    "import-error": "Import failed.",
    coverage: "History loaded. Review coverage.",
    cutoff: "Coverage acknowledged. Select a supported UTC cutoff.",
    reporting: "Preparing synthetic report.",
    "report-error": "Report failed.",
    report: "Synthetic report ready.",
  }[workflow.kind];
  const phase =
    section === "symptoms"
      ? "Symptom entries are synthetic previews held locally and not saved or sent."
      : section === "sleep"
        ? "Schedule comparisons use static synthetic illustrations."
        : workflowPhase;
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
      <div className="workspace">
        <aside className="sidebar">
          <a className="brand" href="#import" aria-label="Hachi import">
            <span className="brand-mark">h</span>hachi
            <span className="brand-dot">.</span>
          </a>
          <p className="workspace-label">RESEARCH WORKSPACE</p>
          <nav aria-label="Workspace sections">
            {sections.map((item, index) => (
              <a
                key={item}
                href={`#${item}`}
                aria-current={section === item ? "page" : undefined}
              >
                <span className="nav-number">0{index + 1}</span>
                {item === "import"
                  ? "Import & coverage"
                  : item === "anomaly"
                    ? "Anomaly monitor"
                    : item === "sleep"
                      ? "Sleep comparison"
                      : item[0].toUpperCase() + item.slice(1)}
              </a>
            ))}
          </nav>
          <div className="sidebar-note">
            <span className="status-dot" />
            Local demonstration
            <p>
              Explore the workflow.
              <br />
              Understand the evidence.
            </p>
          </div>
        </aside>
        <div className="main-column">
          <header className="topbar">
            <span>Hachi / Research prototype</span>
            <span className="badge">SYNTHETIC DATA ONLY</span>
          </header>
          <div className="synthetic-banner">
            Every observation and output is synthetic. No personal data,
            diagnosis, or validated prediction.
          </div>
          <main id="main" tabIndex={-1}>
            <div className="eyebrow">WEARABLE SIGNALS, WITH CONTEXT</div>
            <h1 ref={heading} tabIndex={-1}>
              {section === "import"
                ? "Start with the evidence."
                : section === "overview"
                  ? "Your research snapshot."
                  : section === "forecast"
                    ? "The next 24 hours."
                    : section === "anomaly"
                      ? "Change, in context."
                      : section === "symptoms"
                        ? "Give symptoms a timeline."
                        : "Compare a different night."}
            </h1>
            <p className="phase" role="status" aria-live="polite">
              {phase}
            </p>
            <SectionView
              section={section}
              workflow={workflow}
              dispatch={dispatch}
            />
          </main>
          <footer>
            HACHI RESEARCH / FIXTURE EDITION{" "}
            <span>Evidence before interpretation.</span>
          </footer>
        </div>
      </div>
    </>
  );
}
