import { useId } from "react";
import type { Panel } from "./workflow";
export function Plot({
  panel,
  title,
  unit,
  description,
  domain,
}: {
  panel: Panel;
  title: string;
  unit: string;
  description: string;
  domain?: readonly [number, number];
}) {
  const id = useId();
  if (panel.kind === "unavailable")
    return (
      <div className="notice">
        <h3>Unavailable</h3>
        <p>{panel.reason}</p>
      </div>
    );
  const values = panel.points.flatMap((point) =>
    point.value === null
      ? []
      : [point.lower ?? point.value, point.upper ?? point.value],
  );
  const min = domain?.[0] ?? Math.floor(Math.min(...values) - 1);
  const max = domain?.[1] ?? Math.ceil(Math.max(...values) + 1);
  const x = (index: number) => 58 + index * 112;
  const y = (value: number) => 235 - ((value - min) / (max - min)) * 190;
  const path = panel.points
    .map((point, index) =>
      point.value === null
        ? ""
        : `${index === 0 || panel.points[index - 1].value === null ? "M" : "L"}${x(index)},${y(point.value)}`,
    )
    .join(" ");
  return (
    <figure className="plot">
      <figcaption>
        <h3>{title}</h3>
        <p>{description}</p>
      </figcaption>
      <div
        className="chart-scroll"
        tabIndex={0}
        role="region"
        aria-label={`${title} chart, scroll horizontally on narrow screens`}
      >
        <svg
          viewBox="0 0 680 290"
          role="img"
          aria-labelledby={`${id}-title ${id}-desc`}
        >
          <title id={`${id}-title`}>{title}. Synthetic illustration.</title>
          <desc id={`${id}-desc`}>
            {description} Exact UTC timestamps and values follow in the table.
            Gaps mean missing observations.
          </desc>
          {[min, (min + max) / 2, max].map((value) => (
            <g key={value}>
              <line
                x1="58"
                x2="640"
                y1={y(value)}
                y2={y(value)}
                className="grid-line"
              />
              <text x="8" y={y(value) + 4}>
                {value.toFixed(1)}
              </text>
            </g>
          ))}
          <text x="8" y="20">
            {unit}
          </text>
          {panel.points.map((point, index) => (
            <g key={point.utc}>
              {point.value !== null &&
                point.lower !== undefined &&
                point.upper !== undefined && (
                  <line
                    x1={x(index)}
                    x2={x(index)}
                    y1={y(point.lower)}
                    y2={y(point.upper)}
                    className="interval"
                  />
                )}
              <text x={x(index)} y="270" textAnchor="middle">
                {point.utc.slice(5, 10)} {point.utc.slice(11, 16)}
              </text>
            </g>
          ))}
          <path d={path} className="series" />
          {panel.points.map(
            (point, index) =>
              point.value !== null && (
                <circle
                  key={point.utc}
                  cx={x(index)}
                  cy={y(point.value)}
                  r="4"
                  className="dot"
                />
              ),
          )}
        </svg>
      </div>
      <p className="caption">
        Synthetic hand-authored fixture. No trained artifact or measured
        accuracy. All times UTC.
      </p>
      <details>
        <summary>View exact values and missing observations</summary>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label={`${title} values`}
        >
          <table>
            <caption>
              {title} · synthetic values in {unit}
            </caption>
            <thead>
              <tr>
                <th>Timestamp UTC</th>
                <th>Value ({unit})</th>
                <th>Illustrative bounds ({unit})</th>
              </tr>
            </thead>
            <tbody>
              {panel.points.map((point) => (
                <tr key={point.utc}>
                  <td>{point.utc}</td>
                  <td>{point.value ?? "Missing"}</td>
                  <td>
                    {point.lower === undefined
                      ? "Not applicable"
                      : `${point.lower} to ${point.upper}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
