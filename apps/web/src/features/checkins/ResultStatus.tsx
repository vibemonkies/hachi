import type { ReportResult } from "../../../../../contracts/typescript/index";

export function ResultStatus({ result }: { result: ReportResult }) {
  return (
    <div className="report-meta">
      {result.replay && (
        <p>
          <strong>Replay of a saved result</strong> · recorded{" "}
          {result.replay.recorded_at_utc} · source report{" "}
          {result.replay.source_report_id}.
        </p>
      )}
      <p>
        Data mode · {result.data_mode}. Cutoff · {result.as_of}. Generated ·{" "}
        {result.generated_at_utc}.
      </p>
      {result.warnings.map((warning) => (
        <p key={warning.code}>{warning.message}</p>
      ))}
    </div>
  );
}
