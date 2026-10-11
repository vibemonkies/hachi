# Import and coverage

## Sub-features

Complete, empty, sparse, access failure, import failure, unavailable models, and report failure fixtures; pending cancellation; reset; coverage acknowledgment.

## How to get to it (user POV)

Open the app, click the Hachi brand or Import & coverage. Empty report panels also link back here.

## Driving it with CUA

Select each visible option in `Demonstration scenario` and click `Load synthetic history`. Observe pending status and disabled duplicate load immediately. Cancel one pending load and confirm empty state remains after completion would have occurred. Load Complete history: expect 342/360 hourly bins, 14/15 resting-HR windows, 13/15 sleep windows. The cutoff must be absent until `I have reviewed the coverage` is clicked. Empty observations must show no substitute numbers; Sparse history must show 144/360 hourly bins. Access failure and Import failure must show their respective error and retry control. Retry should intentionally fail again. Reset must clear coverage and pending work. Carry Models unavailable and Report failure into the report feature.

## Gotchas

The delay is one second. Import-wide counts are not cutoff-specific. No files are uploaded. Failure fixtures intentionally repeat until a different scenario is loaded.
