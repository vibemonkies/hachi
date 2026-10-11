(async () => {
  const response = await fetch('/replay/report', {cache:'no-store'});
  if (!response.ok) return {ok:false,error:'REPLAY_TRANSPORT_FAILED'};
  const job = await response.json();
  const result = job.result;
  if (result?.status !== 'ok' || result.task !== 'physiology_forecast' || !result.replay)
    return {ok:false,error:'EXPECTED_REPLAY_FORECAST'};
  const sections = [...document.querySelectorAll('main section')];
  let compared = 0, mismatch = 0, geometryMismatch = 0;
  result.forecast.series.forEach((series,index) => {
    const section = sections[index];
    if (!section) {mismatch += series.points.length; return;}
    const circles = [...section.querySelectorAll('circle[data-median]')];
    const cells = [...section.querySelectorAll('td[data-value="median"]')];
    if (circles.length !== series.points.length || cells.length !== series.points.length) mismatch++;
    const lo = Math.min(...series.points.map(p => p.lower ?? p.median));
    const hi = Math.max(...series.points.map(p => p.upper ?? p.median));
    const xy = (i,value) => [(30+i*540/Math.max(1,series.points.length-1)).toFixed(4),
                             (170-(value-lo)*140/(hi-lo || 1)).toFixed(4)];
    const expectedLine = series.points.map((p,i) => xy(i,p.median).join(',')).join(' ');
    if (section.querySelector('polyline')?.getAttribute('points') !== expectedLine) geometryMismatch++;
    series.points.forEach((point,i) => {
      compared++;
      if (Number(circles[i]?.getAttribute('data-median')) !== point.median ||
          Number(cells[i]?.textContent) !== point.median) mismatch++;
      const [x,y] = xy(i,point.median);
      if (circles[i]?.getAttribute('cx') !== x || circles[i]?.getAttribute('cy') !== y) geometryMismatch++;
    });
  });
  const text = document.body.innerText;
  const pointOnly = result.forecast.series.every(s => s.interval_calibration === 'none');
  const provenanceVisible = [
    result.data_mode, result.git_sha, result.provenance.artifact.artifact_id,
    result.provenance.artifact.artifact_sha256, result.provenance.dataset_snapshot.snapshot_sha256
  ].every(value => text.includes(value));
  const qualityVisible = result.provenance.feature_coverage.every(c => text.includes(c.metric + ': ' + c.coverage));
  const identifiersOmitted = !text.includes(result.subject_id) && !text.includes(result.report_id);
  const timestampsVisible = [result.replay.recorded_at_utc, result.generated_at_utc]
    .every(t => text.includes(t.replace(/Z$/, '+00:00')));
  const unitsVisible = result.forecast.series.every((s,i) =>
    sections[i]?.querySelector('h2')?.textContent === s.metric + ' · ' + s.unit);
  const pointOnlyBoundsVisible = !pointOnly || sections.every(s =>
    [...s.querySelectorAll('tbody tr')].every(r => r.children[2].textContent === '—' &&
                                                r.children[3].textContent === '—'));
  const noBand = document.querySelectorAll('[data-interval-band]').length === 0;
  const localOnly = performance.getEntriesByType('resource').every(e => new URL(e.name).origin === location.origin);
  return {ok: compared > 0 && mismatch === 0 && geometryMismatch === 0 &&
              provenanceVisible && qualityVisible && identifiersOmitted && timestampsVisible &&
              (!pointOnly || noBand) && unitsVisible && pointOnlyBoundsVisible && localOnly,
          pointsCompared:compared, numericMismatch:mismatch, geometryMismatch, originalDataMode:result.data_mode,
          replayMetadataPresent:!!result.replay, provenanceVisible, qualityVisible, identifiersOmitted,
          timestampsVisible, unitsVisible, pointOnlyBoundsVisible, pointOnly, noIntervalBand:noBand, onlyLocalResources:localOnly};
})()
