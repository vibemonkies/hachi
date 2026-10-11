# Navigation and layout

## Sub-features

Six hash sections, brand return, report links, browser back/forward, skip focus, responsive charts and tables.

## How to get to it (user POV)

Use Workspace sections or keyboard Tab from the top of the page. Browser navigation is part of the interface.

The three working compositions use `?design=task`, `?design=summary`, and `?design=analysis`. These query parameters choose presentation; section hashes and workflow behavior stay shared. A missing or unknown design selects task.

## Driving it with CUA

Click all six section links and confirm the corresponding hash, heading, and heading focus. Exercise brand and report-panel links. Use browser back/forward and require matching section content. Reload: hash remains but workflow clears. Activate Skip to content by keyboard and require main focus without changing the section hash. Inspect desktop and 390 by 844 screenshots, including coverage, forecast, symptoms, and sleep. Read DOM document clientWidth/scrollWidth: page content must not overflow; intentional chart/table regions may scroll internally. Confirm visible keyboard focus and synthetic/unavailable disclosures. Reset viewport overrides afterward.

## Gotchas

Links are unnumbered; scope them to Workspace sections. A horizontally scrolling navigation strip is intentional. Do not infer a saved workflow from a surviving URL hash. Record reduced-motion behavior separately if the harness cannot emulate it.
