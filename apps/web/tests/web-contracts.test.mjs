import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import react from "@vitejs/plugin-react";
import { build, loadConfigFromFile } from "vite";

const webRoot = fileURLToPath(new URL("../", import.meta.url));
const entry = fileURLToPath(new URL("./web-contracts-entry.ts", import.meta.url));
const outputRoot = await mkdtemp(`${tmpdir()}/hachi-web-contracts-`);
const outputDir = `${outputRoot}/build`;
const originalFetch = globalThis.fetch;
let modules;

const fixture = async (path) => JSON.parse(
  await readFile(new URL(`../../../${path}`, import.meta.url), "utf8"),
);

const response = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json" },
});

async function withFetch(handler, operation) {
  globalThis.fetch = handler;
  try {
    return await operation();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

before(async () => {
  await build({
    root: webRoot,
    configFile: false,
    plugins: [react()],
    ssr: { noExternal: true },
    logLevel: "silent",
    build: {
      ssr: entry,
      outDir: outputDir,
      emptyOutDir: true,
    },
  });
  modules = await import(pathToFileURL(`${outputDir}/web-contracts-entry.js`));
});

after(async () => {
  globalThis.fetch = originalFetch;
  await rm(outputRoot, { recursive: true, force: true });
});

test("public contract fixtures are accepted without mutation", { concurrency: false }, async () => {
  const importStatus = await fixture("contracts/fixtures/ImportStatus/running.json");
  const coverage = await fixture("contracts/fixtures/Coverage/typical.json");
  const reportJob = await fixture("contracts/fixtures/ReportJob/completed.json");
  const reportResult = await fixture("contracts/fixtures/ReportResult/ok-physiology-forecast-hourly.json");

  for (const [kind, document] of [
    ["ImportStatus", importStatus],
    ["Coverage", coverage],
    ["ReportJob", reportJob],
    ["ReportResult", reportResult],
  ]) {
    const before = JSON.stringify(document);
    assert.equal(modules.parseContractDocument(kind, document), document);
    assert.equal(JSON.stringify(document), before);
  }
});

test("import, coverage, and report clients reject malformed nested documents", { concurrency: false }, async () => {
  const importStatus = await fixture("contracts/fixtures/ImportStatus/running.json");
  const badImport = structuredClone(importStatus);
  badImport.counts.records_seen = -1;
  const coverage = await fixture("contracts/fixtures/Coverage/typical.json");
  const badCoverage = structuredClone(coverage);
  badCoverage.metrics[0].coverage = 2;
  const reportJob = await fixture("contracts/fixtures/ReportJob/completed.json");
  const badReport = structuredClone(reportJob);
  badReport.result.forecast.series[0].points[0].median = "not-a-number";

  assert.throws(() => modules.parseContractDocument("ImportStatus", badImport));
  assert.throws(() => modules.parseContractDocument("Coverage", badCoverage));
  assert.throws(() => modules.parseContractDocument("ReportJob", badReport));

  await assert.rejects(
    withFetch(async () => response(badImport), async () => modules.submitImport(
      new File(["<xml />"], "export.xml"),
      "synthetic-001",
      "America/Los_Angeles",
      "synthetic",
      new AbortController().signal,
      "http://api.example.test",
    )),
    /invalid import status/,
  );
  await assert.rejects(
    withFetch(async () => response(badCoverage), async () => modules.getCoverage(
      "synthetic-001",
      null,
      new AbortController().signal,
      "http://api.example.test",
    )),
    /invalid coverage data/,
  );
  const pair = await withFetch(async () => response(badReport), async () => modules.requestForecastAndAnomaly(
    "synthetic-001",
    "2026-10-10T07:00:00Z",
    new AbortController().signal,
    "http://api.example.test",
  ));
  assert.equal(pair.forecast.kind, "request-error");
  assert.match(pair.forecast.message, /invalid report job/);
  assert.equal(pair.anomaly.kind, "request-error");
  assert.match(pair.anomaly.message, /invalid report job/);
});

test("Vite keeps live API and saved replay on separate proxy targets", { concurrency: false }, async () => {
  const loaded = await loadConfigFromFile(
    { command: "serve", mode: "test" },
    fileURLToPath(new URL("../vite.config.ts", import.meta.url)),
    webRoot,
  );
  const proxy = loaded.config.server?.proxy;
  assert.equal(proxy["/v1"].target, "http://127.0.0.1:8717");
  assert.equal(proxy["/replay"].target, "http://127.0.0.1:5180");
  assert.notEqual(proxy["/v1"].target, proxy["/replay"].target);
  assert.equal(proxy["/v1"].changeOrigin, true);
  assert.equal(proxy["/replay"].changeOrigin, true);
});

test("saved replay stays same-origin and refuses a 409 live fallback", { concurrency: false }, async () => {
  const reportJob = await fixture("contracts/fixtures/ReportJob/completed.json");
  const replayJob = structuredClone(reportJob);
  replayJob.result.replay = {
    source_report_id: replayJob.report_id,
    recorded_at_utc: "2026-10-10T08:00:00Z",
  };
  const calls = [];

  const saved = await withFetch(async (input, init) => {
    calls.push({ input: String(input), init });
    return response(replayJob);
  }, async () => modules.readSavedReplay(new AbortController().signal));
  assert.equal(saved.report_id, replayJob.report_id);
  assert.deepEqual(calls.map((call) => call.input), ["/replay/report"]);

  const conflictCalls = [];
  await assert.rejects(
    withFetch(async (input) => {
      conflictCalls.push(String(input));
      return response({
        schema_version: "0.1",
        error_code: "REPLAY_MISSING",
        live_fallback: false,
      }, 409);
    }, async () => modules.readSavedReplay(new AbortController().signal)),
    /REPLAY_MISSING/,
  );
  assert.deepEqual(conflictCalls, ["/replay/report"]);
});

test("report clients reject request and result identity mismatches", { concurrency: false }, async () => {
  const forecastJob = await fixture("contracts/fixtures/ReportJob/completed.json");
  const anomalyResult = await fixture("contracts/fixtures/ReportResult/ok-anomaly-alert.json");
  const anomalyJob = {
    ...structuredClone(forecastJob),
    report_id: anomalyResult.report_id,
    request: {
      schema_version: "0.1",
      subject_id: anomalyResult.subject_id,
      as_of: anomalyResult.as_of,
      task: "anomaly",
    },
    result: anomalyResult,
  };
  const calls = [];

  const pair = await withFetch(async (input, init) => {
    const request = JSON.parse(init.body);
    calls.push(request.task);
    if (request.task === "physiology_forecast") {
      const wrongResult = structuredClone(forecastJob);
      wrongResult.result.subject_id = "different-subject";
      return response(wrongResult);
    }
    const wrongRequest = structuredClone(anomalyJob);
    wrongRequest.request.subject_id = "different-subject";
    return response(wrongRequest);
  }, async () => modules.requestForecastAndAnomaly(
    "synthetic-001",
    "2026-10-10T07:00:00Z",
    new AbortController().signal,
    "http://api.example.test",
  ));

  assert.deepEqual(calls.sort(), ["anomaly", "physiology_forecast"]);
  assert.equal(pair.forecast.kind, "request-error");
  assert.match(pair.forecast.message, /result that does not match/);
  assert.equal(pair.anomaly.kind, "request-error");
  assert.match(pair.anomaly.message, /different request/);
});

test("forecast chart uses one UTC domain for an off-hour 23-point window", { concurrency: false }, async () => {
  const reportResult = await fixture("contracts/fixtures/ReportResult/ok-physiology-forecast-hourly.json");
  const coverage = await fixture("contracts/fixtures/Coverage/typical.json");
  const offHour = structuredClone(reportResult);
  offHour.as_of = "2026-10-10T06:30:00Z";
  offHour.forecast.series = offHour.forecast.series.map((series) => ({
    ...series,
    points: series.points.slice(0, 23),
  }));
  const markup = renderToStaticMarkup(modules.ReportView({
    section: "forecast",
    design: "analysis",
    subject: { subjectId: "synthetic-001", imported: null },
    coverage,
    asOf: offHour.as_of,
    reports: {
      forecast: { kind: "result", result: offHour },
      anomaly: { kind: "request-error", message: "unused" },
    },
  }));
  const xValues = [...markup.matchAll(/<circle[^>]*cx="([0-9.]+)"/g)].map((match) => Number(match[1]));
  assert.equal(xValues.length, 46);
  assert.equal(Math.min(...xValues), 69.66666666666667);
  assert.equal(Math.max(...xValues), 583);
  assert.match(markup, /Interval start · UTC/);
});
