import { lazy, Suspense, type Dispatch } from "react";
import { ImportPanel } from "./features/import/ImportPanel";
import { ReportView } from "./features/reports/ReportView";
import { ReplayReportView } from "./features/reports/ReplayReportView";
import type { Action, Section, Workflow } from "./workflow";
import type { Design } from "./App";

const Checkins = lazy(() => import("./features/checkins/Checkins").then((module) => ({ default: module.Checkins })));
const ScenarioComparison = lazy(() => import("./features/scenarios/ScenarioComparison").then((module) => ({ default: module.ScenarioComparison })));

export function SectionView({
  section,
  workflow,
  dispatch,
  design,
  apiBaseUrl,
}: {
  design: Design;
  section: Section;
  workflow: Workflow;
  dispatch: Dispatch<Action>;
  apiBaseUrl: string;
}) {
  if (section === "import") return <ImportPanel workflow={workflow} dispatch={dispatch} />;
  if (section === "replay") {
    if (workflow.kind === "replay-report") return <ReplayReportView job={workflow.job} />;
    if (workflow.kind === "replay-error") return <div className="notice error" role="alert"><h2>Offline replay unavailable</h2><p>{workflow.message}</p><button onClick={() => dispatch({ type: "begin-replay", operationId: crypto.randomUUID() })}>Retry saved replay</button></div>;
    return <div className="notice"><h2>Saved offline replay</h2><p>Load the saved report through the replay API. Replay never submits a live report request.</p><button onClick={() => dispatch({ type: "begin-replay", operationId: crypto.randomUUID() })}>Load saved replay</button></div>;
  }

  const subject = "subject" in workflow ? workflow.subject : null;
  if (section === "symptoms" || section === "sleep") {
    if (!subject) {
      return (
        <div className="notice">
          <h2>Choose a subject first</h2>
          <p>Import an Apple Health export or open an existing API subject before viewing saved check-ins or comparing schedules.</p>
          <a className="button" href="#import">Choose subject</a>
        </div>
      );
    }
    return (
      <Suspense fallback={<p role="status">Loading this API feature…</p>}>
        {section === "symptoms"
          ? <Checkins subjectId={subject.subjectId} apiBaseUrl={apiBaseUrl} asOf={"asOf" in workflow ? workflow.asOf || undefined : undefined} />
          : <ScenarioComparison subjectId={subject.subjectId} apiBaseUrl={apiBaseUrl} />}
      </Suspense>
    );
  }

  if (workflow.kind !== "report") {
    return (
      <div className="notice">
        <h2>No report yet</h2>
        <p>Import or open a subject, review coverage, and run the forecast and anomaly reports first.</p>
        <a className="button" href="#import">Go to import &amp; coverage</a>
      </div>
    );
  }
  return (
    <ReportView
      section={section}
      design={design}
      subject={workflow.subject}
      coverage={workflow.coverage}
      asOf={workflow.asOf}
      reports={workflow.reports}
    />
  );
}
