import type { ReportJob } from "@hachi/contracts";
import { TaskResultPanel } from "./ReportView";

export function ReplayReportView({ job }: { job: ReportJob }) {
  const result = job.result;
  if (!result || !result.replay) {
    return <div className="notice error" role="alert"><h2>Replay provenance is missing</h2><p>The saved response was not rendered because it did not contain replay metadata.</p></div>;
  }
  if (result.task !== "anomaly" && result.task !== "physiology_forecast") {
    return <div className="notice"><h2>Replay loaded</h2><p>Task · {result.task.replaceAll("_", " ")}</p><p>This task type is preserved in the saved response but has no chart in this view.</p><p>Source mode · {result.data_mode}</p><p>Replay recorded · {result.replay.recorded_at_utc}</p><p>Source report · <code>{result.replay.source_report_id}</code></p></div>;
  }
  const isAnomaly = result.task === "anomaly";
  return (
    <>
      <p className="lead replay-intro">{isAnomaly ? "Explore the saved baseline deviation report." : "Explore the saved forecast, one signal at a time."} {result.data_mode === "synthetic" ? "This demo uses synthetic data, not your personal health measurements." : "This report is a saved replay, not a new model run."}</p>
      <div className="report-meta">
        <span className="replay-label">SAVED REPORT</span><p>{isAnomaly ? "Report cutoff" : "Forecast from"} <strong>{result.as_of.slice(0, 16).replace("T", " ")}</strong> UTC</p>
      </div>
      <TaskResultPanel title={isAnomaly ? "Baseline deviation" : "Forecast"} task={{ kind: "result", result }} expectedTask={isAnomaly ? "anomaly" : "physiology_forecast"} expanded={false} />
    </>
  );
}
