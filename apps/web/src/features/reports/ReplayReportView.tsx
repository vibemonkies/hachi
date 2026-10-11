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
      <div className="report-meta">
        <p>Offline replay · recorded <strong>{result.replay.recorded_at_utc}</strong></p>
        <p>Source report · <code>{result.replay.source_report_id}</code></p>
        <p>Source mode · <strong>{result.data_mode}</strong></p>
        <p>Subject · <code>{result.subject_id}</code> · cutoff {result.as_of}</p>
      </div>
      <TaskResultPanel title={isAnomaly ? "Baseline deviation" : "Forecast"} task={{ kind: "result", result }} expectedTask={isAnomaly ? "anomaly" : "physiology_forecast"} expanded />
    </>
  );
}
