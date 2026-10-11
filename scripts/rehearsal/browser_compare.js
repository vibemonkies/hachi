(async () => {
  const response = await fetch('/replay/report', {cache:'no-store'});
  if (!response.ok) return {ok:false,error:'REPLAY_TRANSPORT_FAILED'};
  const job = await response.json();
  const result = job.result;
  if (result?.status !== 'ok' || result.task !== 'physiology_forecast' || !result.replay)
    return {ok:false,error:'EXPECTED_REPLAY_FORECAST'};
  const sections = [...document.querySelectorAll('section[data-metric]')];
  const allPoints = result.forecast.series.flatMap(s => s.points);
  const cutoff = Date.parse(result.as_of);
  const requestedEnd = job.request.resolution === 'hour' ? cutoff + job.request.horizon_hours*3600000 : cutoff;
  const scaleEnd = Math.max(requestedEnd, ...allPoints.map(p => Date.parse(p.interval_end_utc)));
  const scaleDuration = scaleEnd - cutoff;
  const visibleTime = (node, expected) => {
    const canonical = expected.replace(/Z$/, '+00:00');
    return node?.getAttribute('datetime') === canonical && node.textContent === canonical;
  };
  const cutoffVisible = visibleTime(document.querySelector('[data-report-cutoff]'), result.as_of);
  let compared = 0, mismatch = 0, geometryMismatch = 0, intervalTimeMismatch = 0;
  result.forecast.series.forEach((series,index) => {
    const section = sections[index];
    if (!section) {mismatch += series.points.length; return;}
    const circles = [...section.querySelectorAll('circle[data-median]')];
    const rows = [...section.querySelectorAll('tbody tr')];
    if (circles.length !== series.points.length || rows.length !== series.points.length) mismatch++;
    const lo = Math.min(...series.points.map(p => p.lower ?? p.median));
    const hi = Math.max(...series.points.map(p => p.upper ?? p.median));
    const xy = (point,value) => {
      const midpoint = (Date.parse(point.interval_start_utc) + Date.parse(point.interval_end_utc)) / 2;
      return [(30 + (midpoint-cutoff)*540/scaleDuration).toFixed(4),
              (170-(value-lo)*140/(hi-lo || 1)).toFixed(4)];
    };
    const expectedLine = series.points.map(p => xy(p,p.median).join(',')).join(' ');
    if (section.querySelector('polyline')?.getAttribute('points') !== expectedLine) geometryMismatch++;
    series.points.forEach((point,i) => {
      compared++;
      const row = rows[i];
      if (Number(circles[i]?.getAttribute('data-median')) !== point.median ||
          Number(row?.querySelector('[data-value="median"]')?.textContent) !== point.median) mismatch++;
      for (const [value,column] of [[point.lower,3],[point.upper,4]]) {
        const shown = row?.children[column]?.textContent;
        if (value === null ? shown !== '—' : Number(shown) !== value) mismatch++;
      }
      if (!visibleTime(row?.querySelector('[data-interval-start]'), point.interval_start_utc)) intervalTimeMismatch++;
      if (!visibleTime(row?.querySelector('[data-interval-end]'), point.interval_end_utc)) intervalTimeMismatch++;
      const [x,y] = xy(point,point.median);
      if (circles[i]?.getAttribute('cx') !== x || circles[i]?.getAttribute('cy') !== y) geometryMismatch++;
    });
  });
  const sorted = allPoints.map(p => [Date.parse(p.interval_start_utc), Date.parse(p.interval_end_utc)])
                          .sort((a,b) => a[0]-b[0]);
  let end = cutoff, targetGapWindows = 0;
  for (const [start,stop] of sorted) {
    if (start > end) targetGapWindows++;
    end = Math.max(end,stop);
  }
  if (end < scaleEnd) targetGapWindows++;
  const text = document.body.innerText;
  const pointOnly = result.forecast.series.every(s => s.interval_calibration === 'none');
  const provenanceVisible = [result.data_mode,result.git_sha,result.provenance.artifact.artifact_id,
    result.provenance.artifact.artifact_sha256,result.provenance.dataset_snapshot.snapshot_sha256]
    .every(value => text.includes(value));
  const qualityVisible = result.provenance.feature_coverage.every(c => text.includes(c.metric + ': ' + c.coverage));
  const identifiersOmitted = !text.includes(result.subject_id) && !text.includes(result.report_id);
  const timestampsVisible = [result.replay.recorded_at_utc,result.generated_at_utc]
    .every(t => text.includes(t.replace(/Z$/, '+00:00')));
  const unavailable = [...document.querySelectorAll('[data-unavailable-metric]')];
  const unavailableMetricsVisible = unavailable.length === result.forecast.unavailable_metrics.length &&
    result.forecast.unavailable_metrics.every((m,i) => unavailable[i]?.textContent === m.metric + ': ' + m.reason_code);
  const unitsVisible = result.forecast.series.every((s,i) =>
    sections[i]?.querySelector('h2')?.textContent === s.metric + ' · ' + s.unit);
  const noBand = document.querySelectorAll('[data-interval-band]').length === 0;
  const localOnly = performance.getEntriesByType('resource').every(e => new URL(e.name).origin === location.origin);
  return {ok: compared > 0 && mismatch === 0 && geometryMismatch === 0 && intervalTimeMismatch === 0 &&
              cutoffVisible && sections.length === result.forecast.series.length && unavailableMetricsVisible &&
              provenanceVisible && qualityVisible && identifiersOmitted && timestampsVisible &&
              (!pointOnly || noBand) && unitsVisible && localOnly,
          pointsCompared:compared,numericMismatch:mismatch,geometryMismatch,intervalTimesCompared:compared*2,
          intervalTimeMismatch,cutoffVisible,elapsedUtcCommonScale:true,targetGapWindows,
          originalDataMode:result.data_mode,replayMetadataPresent:!!result.replay,provenanceVisible,qualityVisible,
          identifiersOmitted,timestampsVisible,unitsVisible,unavailableMetricsVisible,pointOnly,
          noIntervalBand:noBand,onlyLocalResources:localOnly};
})()
