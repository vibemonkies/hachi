# Reports

## Sub-features

Cutoff gating and invalidation; overview; forecast values and intervals; anomaly gaps; unavailable illness/recovery; report retry.

## How to get to it (user POV)

Load history and acknowledge coverage in Import & coverage. Choose a supported Explicit UTC cutoff and request a report. Open overview or use Overview, Forecast, and Anomaly monitor links. Use the report's cutoff action to return to import.

## Driving it with CUA

Before selecting a cutoff, require disabled `Request synthetic report`. Select the latest fixture and request; wait for `Synthetic report ready.`. Open Forecast, expand `View exact values and missing observations`, and compare the six values 64,67,75,73,68,63 bpm with the chart. Anomaly must identify its synthetic score and earlier baseline without claiming illness probability. Overview must expose unavailable onset/recovery. Change to the earlier cutoff: the old report must disappear immediately. Request again; forecast values must be 62,64,72,70,66,61 bpm. Repeat with Sparse history: forecast unavailable and anomaly table Missing at 2026-10-07T07:00:00Z with a chart gap. Models unavailable must not invent model output. Report failure must expose retry and fail again at the same cutoff.

## Gotchas

Six selected hourly bins illustrate a 24-hour horizon; this is not 24 observations. Intervals are uncalibrated. Baseline metadata labels the final illustrative point, not a computed baseline for every plotted point.
