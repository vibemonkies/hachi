# Symptoms

## Sub-features

Required bounded UTC event time, preset symptom/severity, unsaved preview, clear and navigation/reload reset.

## How to get to it (user POV)

Click Symptoms; no imported history is needed.

## Driving it with CUA

Clear the prefilled `Synthetic event time · UTC`, click `Preview synthetic entry`, and observe native required validation. Fill the time with `2026-10-09T12:00`, choose `Example headache` in `Synthetic symptom` and `Moderate` in `Example severity`, then submit. Require the selected event time, symptom, severity, and distinct actual creation time in the unsaved preview. Exercise `Clear preview`. Recreate, navigate away/back, then recreate/reload: both must discard the preview.

## Gotchas

Use synthetic inputs only. The datetime control is explicitly UTC despite native local formatting. This is component memory, not a saved health record.
