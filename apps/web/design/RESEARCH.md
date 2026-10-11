# Hachi interface research and design comparison

## Objective and constraints

Hachi's intended user imports wearable history, checks usable signals, freezes an as-of time, and inspects future estimates and historical deviations. The current issue #4 surface is a synthetic browser prototype. It cannot support personal conclusions, medical decisions, or scientific accuracy claims. The design must distinguish these facts without making the user read a methodology essay before every action.

The user requested a coherence review, a research-led redesign, and working versions of every researched design direction with screenshots in the PR. We compare task-focused service, health summary, and analytical report compositions. These adapt patterns, not institutional brands or complete design-system implementations.

## Research and implications

| Primary source | What it establishes | Consequence for Hachi |
| --- | --- | --- |
| [NHS writing guidance](https://service-manual.nhs.uk/content/how-we-write) | Factual, neutral, unambiguous language; direct headings; concise content. | Replace slogans with task and metric names. Remove prose that describes obvious controls. |
| [NHS health literacy](https://service-manual.nhs.uk/content/health-literacy) | Health information and numbers can be difficult to use. Readability tools cannot establish usability. | Explain consequential concepts such as deviation, UTC, and unsaved entries beside their values. Do not claim user validation from this review. |
| [DWP hint text](https://design-system.dwp.gov.uk/guidance/hint-text) | Add help only for a clear need after improving the question. | Keep cutoff invalidation and data-handling consequences; remove generic instructions to choose, view, or compare. |
| [GOV.UK text inputs](https://design-system.service.gov.uk/components/text-input/) | Visible, short, direct labels above inputs. | Preserve real labels and native controls; no placeholder-only labels. |
| [Apple Health data views](https://support.apple.com/guide/iphone/view-your-health-data-iphe3d379c32/26/ios/26) | Summary highlights lead to category details and sources. | A health-summary version groups available tasks into concise cards and exposes detail on demand. No fabricated insight scores. |
| [Google Health vitals](https://support.google.com/googlehealth/answer/14236917?hl=en-GB) | Personal ranges depend on historical data; missing readings have collection requirements. | Keep baseline window, missingness, and signal coverage visible. Do not import another product's baseline rules. |
| [ONS uncertainty guidance](https://service-manual.ons.gov.uk/data-visualisation/guidance/showing-uncertainty-in-charts) | Show uncertainty when it changes interpretation; explain ranges plainly. | Keep illustrative bounds identifiable and explicitly uncalibrated. Never borrow a probability or coverage claim from an example. |
| [ONS chart principles](https://service-manual.ons.gov.uk/data-visualisation/guidance/principles) | Guidance is for communicating information rather than open-ended exploration. | Analytical version gives the metric, time window, chart, and equivalent table priority. |
| [W3C complex images](https://www.w3.org/WAI/tutorials/images/complex/) | Charts need short identification and a detailed text equivalent. | Retain accessible chart names and exact-value tables, including gaps. |
| [NHS typography](https://service-manual.nhs.uk/design-system/styles/typography) | Consistent heading structure, readable text, and overflow checks. | Task version emphasizes readable forms and clear boundaries rather than decorative cards. |

These sources establish useful patterns and constraints. They do not prove which composition Hachi users prefer. A regulatory drug-advertising source was screened out because its scope does not match this prototype. No clinical or diagnostic guidance is implemented.

## Hackathon target

The user narrowed the goal to competitive hackathon application design. Our design target is immediate comprehension, a short uninterrupted working demonstration, prominent readable results, and credible presentation of technical evidence. This is a design judgment, not a promise of winning. [Devpost's judging guidance](https://info.devpost.com/blog/understanding-hackathon-submission-and-judging-criteria) identifies implementation, ease of use, demonstration, impact, idea, and design as common criteria. No event-specific rubric was found in this repository.

The three versions must look deliberately composed on a projected desktop and a phone. They must change layout, grouping, density, and visual hierarchy rather than merely recolor buttons. The shared content keeps the demo honest while the different compositions let the user choose the strongest presentation. This task does not expand into production healthcare workflow or clinical validation.

## Current behavior and coherence findings

App owns Workflow, hash navigation, focus, announcements, and one cancellable timer. SectionView consumes the discriminated state and renders forms or reports. Plot consumes Panel, either unavailable with a reason or illustrative with nullable observations. The current types already express the domain; a redesign needs no new workflow abstraction.

The existing conveyed message is an invitation to explore a research demo. The intended response is more concrete: load history, review missingness, choose a cutoff, inspect the relevant result. The repeated slogans and large introductions interrupt that path. Repeated provenance obscures the essential limits instead of strengthening them.

Keep synthetic status, unavailable reasons, missing values, the six-bin horizon limitation, uncalibrated bounds, anomaly's distinction from illness probability, sleep assumptions, and unsaved symptom consequences. Put secondary methodological requirements behind named disclosures. Do not hide the qualification needed to interpret a chart.

## Execution checklist

- [x] `how` over the affected subsystem.
- [x] `architect` for parallel design exploration.
- [x] Write the throughput checkpoint as four todo items.
- [x] Delegate code-writing to a subagent.
- [x] Verify on the matching surface. See [observations and gallery](VERIFICATION.md).
- [x] Keep small, ordered commits on the exact verification-PR base. Stack the design follow-up.
- [x] Use an explicit skeptical design-review pass before shipping. It caught and corrected the unsupported claim that reports analyze imported observations.
- [x] Run Opening a PR. [Design PR #32](https://github.com/vibemonkies/hachi/pull/32) is ready and stacked on verification PR #31, with all three screenshot comparisons embedded.

Throughput checkpoint follows.

- Blocking first steps. Read product requirements, current UI/state owners, and primary research before selecting composition.
- Independent workstreams. Read-only structural candidates run independently; one implementation owner writes app source.
- Shared mutable state. A separate worktree and branch protect PR #30 and the original coordinator's evidence. Separate browser port and tab protect their running instance.
- Smallest safe decomposition. One worker owns the shared markup and three scoped visual treatments so behavior and disclosures cannot drift across copies.

## Verification standard

Exercise each version through real import, coverage acknowledgment, cutoff, and report controls. Capture identical forecast and import states at desktop and phone sizes. Inspect all six sections, failure/unavailable states, keyboard focus and page overflow. Retain commands and observations beside screenshots. No tests are created or modified. User usability and clinical validity remain outside the evidence collected here.

## Structural comparison and synthesis

Two independent sketches were compared before implementation. Candidate A put a single large result close to the top in a compact task workspace. Candidate B proposed more distinct summary cards and an analytical report with both supported outputs. An independent reviewer selected A as the shared implementation base. We agree because the import-to-result path remains direct and does not require a dashboard abstraction.

The synthesis adopts B's literal copy and its analytical overview, plus A's source-and-coverage column on analytical detail pages. The task version prioritizes clear sequential forms. The summary version prioritizes linked output cards. The analysis version prioritizes chart, source context, and values. A giant dashboard that mixes all controls and results was rejected because it weakens the short demonstration path. Separate copied apps were rejected because fixture behavior and qualifications would drift.

The code keeps Workflow, Panel, and fixtures unchanged. A small Design union selects presentation at the URL boundary. App owns the selection and shell; SectionView owns task composition; Plot retains numerical rendering and exact-value equivalents. Visual variants cannot generate new data or change report eligibility. The next maintainer inherits one behavior implementation and three inspectable compositions.

The judge's scores describe sketches, not measured usability. The main shared risk is that visual polish makes hand-authored outputs look authoritative. Essential labels remain adjacent to results. The alternative risk is an analytical version too dense for a short demo; all versions must be inspected on desktop and phone before publication.

## Principles applied

| Bean Mode principle | Concrete choice |
| --- | --- |
| Redesign from first principles | Start from import, coverage, cutoff, and a readable result rather than inherit the decorative dashboard. |
| Subtract before you add | Remove slogans, repeated introductions, numbered navigation, and duplicate provenance. |
| Experience first | Compare real working compositions through the complete demonstration path on desktop and phone. |
| Model the domain | Preserve Workflow and Panel; presentation cannot create model results or change eligibility. |
| Prove it works | Drive public controls, inspect exact values, and commit actual screenshots and limitations. |
| Sequence verifiable units | Order implementation, copy correction, and research/evidence commits on the verification PR's exact base. |
| Separate before serializing shared state | Isolate the checkout, preview port, browser tab, and implementation ownership. |
