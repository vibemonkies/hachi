// Read-only, local DOM/API comparison. Return aggregate evidence only.
// Evaluate after driving the actual app controls; never snapshot a private page.
(async () => {
  try {
    const response = await fetch('/replay/report', { cache: 'no-store' });
    if (!response.ok) return { ok: false, gate: 'saved-source-unavailable' };
    const job = await response.json();
    const result = job.result;
    if (job.state !== 'completed' || result?.status !== 'ok' ||
        result.task !== 'physiology_forecast' || !result.replay)
      return { ok: false, gate: 'forecast-source-required' };
    const body = document.body.innerText;
    const replayView = !!document.querySelector('.report-meta')?.innerText.includes('Offline replay');
    const series = result.forecast.series;
    if (!series.every(s => s.interval_calibration === 'none' && s.nominal_coverage === null &&
        s.points.every(p => p.lower === null && p.upper === null)))
      return { ok: false, gate: 'point-only-comparator-required' };
    const figures = [...document.querySelectorAll('figure.api-plot')];
    let points = 0, endpoints = 0, numericMismatch = 0, timeMismatch = 0, geometryMismatch = 0;
    let unitsMatch = true, pointOnlyHonest = true, tablesVisible = true;
    for (const expected of series) {
      const label = expected.metric === 'heart_rate' ? 'Heart rate forecast' : `${expected.metric.replaceAll('_', ' ')} forecast`;
      const figure = figures.find(f => f.querySelector('figcaption h2')?.textContent.toLowerCase().includes(label.toLowerCase()));
      if (!figure) return { ok: false, gate: 'forecast-figure-missing' };
      const rows = [...figure.querySelectorAll('tbody tr')];
      const circles = [...figure.querySelectorAll('circle.dot')];
      if (rows.length !== expected.points.length || circles.length !== expected.points.length)
        return { ok: false, gate: 'point-count-differs' };
      unitsMatch &&= figure.querySelector('figcaption')?.textContent.includes(expected.unit) === true;
      tablesVisible &&= figure.querySelector('details')?.open === true;
      const pointOnly = expected.interval_calibration === 'none' && expected.nominal_coverage === null &&
        expected.points.every(p => p.lower === null && p.upper === null);
      pointOnlyHonest &&= !pointOnly || (figure.querySelectorAll('.interval, polygon').length === 0 &&
        figure.textContent.includes('Point estimates only.') && figure.textContent.includes('No interval bounds or coverage claim'));
      const values = expected.points.map(p => p.median);
      const min = Math.min(...values), max = Math.max(...values);
      const range = max === min ? Math.max(1, Math.abs(max) * 0.05) : (max - min) * 0.12;
      const low = min - range, high = max + range;
      for (let i = 0; i < rows.length; i++) {
        const cells = [...rows[i].cells].map(c => c.textContent.trim());
        const p = expected.points[i];
        const offset = expected.points.some(v => v.local_date) ? 1 : 0;
        endpoints += 2; points++;
        timeMismatch += Number(cells[0] !== p.interval_start_utc) + Number(cells[1] !== p.interval_end_utc);
        numericMismatch += Number(Number(cells[2 + offset]) !== p.median);
        numericMismatch += Number(p.lower === null ? cells[3 + offset] !== 'Not available' : Number(cells[3 + offset]) !== p.lower);
        numericMismatch += Number(p.upper === null ? cells[4 + offset] !== 'Not available' : Number(cells[4 + offset]) !== p.upper);
        // The app marks interval starts, unlike the standalone viewer's midpoints.
        const x = 58 + (Date.parse(p.interval_start_utc) - Date.parse(result.as_of)) * 560 / 86400000;
        const y = 220 - (p.median - low) / (high - low) * 170;
        geometryMismatch += Number(Math.abs(Number(circles[i].getAttribute('cx')) - x) > 1e-8);
        geometryMismatch += Number(Math.abs(Number(circles[i].getAttribute('cy')) - y) > 1e-8);
      }
    }
    const identity = [...document.querySelectorAll('.result-identity')].map(e => e.textContent).join(' ');
    const provenance = result.provenance;
    const artifactVisible = identity.includes(provenance.artifact.artifact_id) && identity.includes(provenance.artifact.artifact_sha256);
    const snapshotVisible = identity.includes(provenance.dataset_snapshot.dataset_id) && identity.includes(provenance.dataset_snapshot.dataset_version);
    const codeVisible = identity.includes(result.git_sha);
    const cutoffVisible = document.querySelector('.report-meta')?.textContent.includes(result.as_of) === true;
    const sourceModeVisible = identity.includes(`${result.data_mode} data`);
    const qualityVisible = provenance.feature_coverage.every(f => identity.includes(`${Math.round(f.coverage * 100)}%`));
    const replayVisible = !replayView || (body.includes(result.replay.recorded_at_utc) && body.includes(result.replay.source_report_id));
    let apiMatchesSaved = null;
    if (!replayView) {
      const liveResponse = await fetch(`/v1/reports/${encodeURIComponent(job.report_id)}`, { cache: 'no-store' });
      if (!liveResponse.ok) return { ok: false, gate: 'live-source-unavailable' };
      const live = await liveResponse.json();
      const projected = structuredClone(result); projected.replay = null;
      apiMatchesSaved = JSON.stringify(live.result) === JSON.stringify(projected);
    }
    const windows = series.flatMap(s => s.points.map(p => [Date.parse(p.interval_start_utc), Date.parse(p.interval_end_utc)]))
      .sort((a, b) => a[0] - b[0]);
    let cursor = Date.parse(result.as_of), gaps = 0;
    for (const [start, end] of windows) { if (start > cursor) gaps++; cursor = Math.max(cursor, end); }
    if (cursor < Date.parse(result.as_of) + 86400000) gaps++;
    const evidence = { view: replayView ? 'app-replay' : 'app-live', points_compared: points,
      endpoints_compared: endpoints, numeric_mismatches: numericMismatch, time_mismatches: timeMismatch,
      geometry_mismatches: geometryMismatch, units_match: unitsMatch, point_only_honest: pointOnlyHonest,
      exact_tables_open: tablesVisible, artifact_visible: artifactVisible, snapshot_visible: snapshotVisible,
      code_visible: codeVisible, cutoff_visible: cutoffVisible, original_mode_visible: sourceModeVisible,
      quality_visible: qualityVisible, replay_provenance_visible: replayVisible, target_gap_windows: gaps,
      live_result_equals_saved: apiMatchesSaved };
    return { ok: points > 0 && !numericMismatch && !timeMismatch && !geometryMismatch &&
      unitsMatch && pointOnlyHonest && tablesVisible && artifactVisible && snapshotVisible && codeVisible &&
      cutoffVisible && sourceModeVisible && qualityVisible && replayVisible && apiMatchesSaved !== false, ...evidence };
  } catch {
    return { ok: false, gate: 'private-comparison-failed' };
  }
})()
