# Issue #17 Apple forecast handoff

This note preserves the live #17 handoff from WindyTrout. The handoff describes expected behavior if PR #107 merges and its artifact is served. It does not establish that the API currently serves this artifact or returns these values.

Source: [Issue #17 comment 6110080578](https://github.com/vibemonkies/hachi/issues/17#issuecomment-6110080578), posted 2026-10-11 14:31:26 UTC.

## Exact handoff

> @CoffeeCoder1015 — WindyTrout (#16). Here's what an **Apple Health subject** will see for forecasts once [PR #107](https://github.com/vibemonkies/hachi/pull/107) merges and its artifact is served. It merges after owner acks and review; I'll confirm here when it does.
>
> **Typical 5-minute Apple Watch heart rate now gets a forecast.** Until now it was always `unavailable` / `INSUFFICIENT_HISTORY`.
> - **`status: "ok"`, one `heart_rate` series of hourly points, point-only:** `interval_calibration: "none"` with null `lower`/`upper`, the same point-only form as the #9 baselines. Draw a line, not a band.
> - **Model:** `causal-hourly-tree-v1-bfb44f2d31cac525`, an **interim** CPU model, not #12's selection. #12 selected a GPU-only Chronos model, and personal data never goes to the GPU.
> - **Always a `DEVICE_SHIFT` warning.** Its message reads: "The model was evaluated on pmdata, not on this subject's data source. apple_health input is admitted as an unvalidated transfer: Interim, not a #12 selection: causal tree frozen on the #102 Apple-minute density variant (protocol 3629a9b8). Validated for 5-minute cadence on PMData only (#97 report); not validated on Apple devices." Please show it prominently; it's the honest caveat.
>
> **Edge cases the UI should expect**
> - **`as_of` not on the hour:** targets start at the next hour, so the tree abstains on the 24th target and returns 23 points plus `SPARSE_HISTORY` ("abstained for 1 of 24 target hours; only the contiguous forecast is shown"). An on-the-hour `as_of` gives 24.
> - **Hours with too little wear:** after thinning to one sample per 5-minute slot, an hour needs ≥ 6 samples (≥ 6 of 60 minutes sampled). Too few usable hours in the 48 h lookback gives `unavailable` / `INSUFFICIENT_HISTORY`, as before.
> - **Unchanged:** Apple subjects never get GPU models (Chronos). The coverage endpoint shows `physiology_forecast` as supported when this artifact is served.
>
> Measured over HTTP with a synthetic year (122,640 records): import 7.4 s, report 0.62 s.

## Status and remaining gates

At this note's last live check, PR #107 was open at `b672a808392ad1b6e34abeef419043ae4ef41f39`, with no submitted review decision or reviews. Its CI check had succeeded. The artifact is prospective until the PR merges and the API serves it.

The handoff names an interim CPU artifact, not #12's selected Chronos model. Personal data must not go to a GPU. The `DEVICE_SHIFT` warning must remain visible as an unvalidated PMData-to-Apple transfer, including the artifact and protocol context in the API message.

The web renderer's public types support point-only forecasts with null bounds, point values, and `interval_calibration: "none"`. The renderer should draw the median series without a band or interval coverage claim. For off-hour cutoffs it should preserve all 23 returned points and show `SPARSE_HISTORY`. For insufficient wear it should show `INSUFFICIENT_HISTORY`, not substitute a chart.

No successful API response for PR #107, Apple import, coverage, forecast, or chart was observed in this local work. The local replay request returned 502 because no service listened on `127.0.0.1:8717`. A real approved import-to-report walkthrough and comparison against API values remain acceptance gates. Do not infer these gates are complete from this handoff or the web build.

## Scenario simulator source handoff

PR #101 merged at `85a8c80658e7066dc2a1e9d06ebc4489bf597f21` from reviewed head `0622db3e2d971dfc5549db0741c70f7c07bd2f9b`. Its conditional simulator source is delivered. The API-owner handoff below requests Justin/WindyTrout to compose it through the API seam. No served scenario response was observed in this local work.

Source: [PR #101 comment 6110151856](https://github.com/vibemonkies/hachi/pull/101#issuecomment-6110151856).

> @justin06lee / WindyTrout, the conditional simulator source needed for [#16](https://github.com/vibemonkies/hachi/issues/16) is delivered in merged [PR #101](https://github.com/vibemonkies/hachi/pull/101), merge `85a8c80658e7066dc2a1e9d06ebc4489bf597f21` from reviewed head `0622db3e2d971dfc5549db0741c70f7c07bd2f9b`.
>
> I compared all seven merged scenario/config files with that head and found no differences. Exact-head Ubuntu CI passed, and Ezzy approved the conditional simulator. `scenario_from_request`, pure `model.simulate`, and `build_result` use the existing request/result contracts. The merged README and TOML configs supply the reproducible CLI and assumptions. This satisfies the source prerequisite you identified in your [#16 checkpoint](https://github.com/vibemonkies/hachi/issues/16#issuecomment-6109672920).
>
> Please integrate the simulator through your owned API seam and link its source/artifact/response handoff for [#17](https://github.com/vibemonkies/hachi/issues/17) and [#18](https://github.com/vibemonkies/hachi/issues/18). Preserve simulation mode, the illustrative dimensionless scale, explicit assumptions, and unavailable measured validation. This is a scoped integration unblock. Full #15, #16, #18 and #20 acceptance is not delivered by the simulator merge. No new tests, access, consent, merge or scientific-evaluation authority is granted.

The source merge does not prove that the API serves the simulator. API composition and a successful scenario request/response remain open. The simulation must retain its simulation mode, dimensionless illustrative scale, assumptions, and unavailable measured validation. The source delivery does not establish full #15, #16, #18, or #20 acceptance.
