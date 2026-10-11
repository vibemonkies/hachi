import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { createInterface } from "node:readline";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import react from "@vitejs/plugin-react";

const web = fileURLToPath(new URL("../", import.meta.url));
const repo = fileURLToPath(new URL("../../../", import.meta.url));
let output, backend, lines, originalFetch, api, Checkins, readCheckinHistory;
const requests = [];
before(async () => {
  await mkdir(`${web}.cache`, { recursive: true });
  output = await mkdtemp(`${web}.cache/history-test-`);
  await build({
    root: web,
    configFile: false,
    plugins: [react()],
    logLevel: "silent",
    build: {
      ssr: fileURLToPath(
        new URL("./checkins-history-entry.ts", import.meta.url),
      ),
      outDir: output,
    },
  });
  const module = await import(
    pathToFileURL(`${output}/checkins-history-entry.js`)
  );
  Checkins = module.Checkins;
  readCheckinHistory = module.readCheckinHistory;
  backend = spawn(
    process.env.HACHI_TEST_PYTHON ?? `${repo}.venv/bin/python`,
    [
      "-I",
      fileURLToPath(new URL("./checkins-history-api.py", import.meta.url)),
    ],
    { cwd: repo, stdio: ["pipe", "pipe", "inherit"] },
  );
  lines = createInterface({ input: backend.stdout })[Symbol.asyncIterator]();
  assert.deepEqual(JSON.parse((await lines.next()).value), { ready: true });
  originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    requests.push(new URL(url));
    backend.stdin.write(
      `${JSON.stringify({
        url,
        method: init.method ?? "GET",
        headers: init.headers,
        body: init.body,
      })}\n`,
    );
    const response = JSON.parse((await lines.next()).value);
    return new Response(response.status === 204 ? null : response.body, {
      status: response.status,
    });
  };
  api = module.createCheckinApi("http://127.0.0.1");
});
after(async () => {
  if (originalFetch) globalThis.fetch = originalFetch;
  if (backend) {
    backend.stdin.end();
    await once(backend, "exit");
  }
  if (output) await rm(output, { recursive: true, force: true });
});

const subjectId = "synthetic-cutoff";
const early = "2026-09-02T08:00:00Z";
const beforeRecording = "2026-09-02T07:59:59Z";
const later = "2026-09-03T09:00:00Z";
const original = {
  kind: "symptom_onset",
  entry_id: "synthetic-onset",
  entered_at_utc: early,
  onset_earliest_utc: "2026-09-01T20:00:00Z",
  onset_latest_utc: "2026-09-02T06:00:00Z",
  symptoms: ["cough"],
  severity: 1,
};
const correction = {
  ...original,
  entry_id: "synthetic-correction",
  supersedes: original.entry_id,
  entered_at_utc: later,
  severity: 3,
};
const laterEntry = {
  kind: "alertness_rating",
  entry_id: "synthetic-rating",
  entered_at_utc: later,
  rated_at_utc: "2026-09-02T07:00:00Z",
  scale: "kss_1_9",
  value: 6,
};
const ids = (history) => history.entries.map((entry) => entry.entry_id);
test("actual API hides later entries/corrections at the selected cutoff in current and all-version reads", async () => {
  await api.save(subjectId, { schema_version: "0.1", entries: [original] });
  await api.save(subjectId, {
    schema_version: "0.1",
    entries: [correction, laterEntry],
  });
  requests.length = 0;
  const before = await readCheckinHistory(api, subjectId, beforeRecording);
  assert.deepEqual(ids(before.history), []);
  assert.deepEqual(before.versions, []);
  const { history: currentEarly, versions: earlyVersions } =
    await readCheckinHistory(api, subjectId, early);
  const allEarly = { entries: earlyVersions };
  assert.deepEqual(ids(currentEarly), [original.entry_id]);
  assert.deepEqual(ids(allEarly), [original.entry_id]);
  assert.equal(currentEarly.entries[0].severity, 1);
  const { history: currentLater, versions: laterVersions } =
    await readCheckinHistory(api, subjectId, later);
  const allLater = { entries: laterVersions };
  assert.deepEqual(ids(currentLater), [
    correction.entry_id,
    laterEntry.entry_id,
  ]);
  assert.deepEqual(ids(allLater), [
    original.entry_id,
    correction.entry_id,
    laterEntry.entry_id,
  ]);
  assert.equal(currentLater.entries[0].severity, 3);
  assert.equal(currentLater.entries[0].supersedes, original.entry_id);
  assert.equal(
    currentLater.entries[0].onset_earliest_utc,
    currentEarly.entries[0].onset_earliest_utc,
  );
  assert.deepEqual(
    requests.map((url) => url.searchParams.get("as_of")),
    [beforeRecording, beforeRecording, early, early, later, later],
  );
  assert.deepEqual(
    requests.map((url) => url.searchParams.get("versions") ?? "current"),
    ["current", "all", "current", "all", "current", "all"],
  );
  // Returning to an earlier cutoff is a backend projection, not a client filter.
  assert.deepEqual(ids(await api.history(subjectId, "all", early)), [
    original.entry_id,
  ]);
  assert.deepEqual(ids(await api.history(subjectId)), [
    correction.entry_id,
    laterEntry.entry_id,
  ]);
  assert.equal(requests.at(-1).searchParams.has("as_of"), false);
  assert.deepEqual(ids(await api.history(subjectId, "all")), [
    original.entry_id,
    correction.entry_id,
    laterEntry.entry_id,
  ]);
  assert.equal(requests.at(-1).searchParams.has("as_of"), false);
  // URL encoding must retain a supplied offset, including its literal + sign.
  const utcOffsetCutoff = "2026-09-03T09:00:00+00:00";
  assert.deepEqual(
    ids(await api.history(subjectId, "current", utcOffsetCutoff)),
    [correction.entry_id, laterEntry.entry_id],
  );
  assert.equal(requests.at(-1).searchParams.get("as_of"), utcOffsetCutoff);
  const offsetCutoff = "2026-09-03T10:00:00+01:00";
  await assert.rejects(
    api.history(subjectId, "current", offsetCutoff),
    /query.as_of/,
  ); // The authoritative UtcDatetime boundary refuses non-UTC offsets.
  assert.equal(requests.at(-1).searchParams.get("as_of"), offsetCutoff);
  await api.deleteEntry(subjectId, correction.entry_id);
  assert.deepEqual(ids(await api.history(subjectId, "all", early)), []);
  assert.deepEqual(ids(await api.history(subjectId, "all", later)), [
    laterEntry.entry_id,
  ]);
});
test("changing only the selected cutoff starts a fresh check-in workspace", () => {
  const props = { subjectId, apiBaseUrl: "http://127.0.0.1" };
  const initial = Checkins({ ...props, asOf: early });
  assert.equal(initial.key, Checkins({ ...props, asOf: early }).key);
  assert.notEqual(initial.key, Checkins({ ...props, asOf: later }).key);
  assert.notEqual(initial.key, Checkins(props).key);
});
