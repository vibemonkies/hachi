import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createContractParser } from "../src/features/checkins/schema-core.ts";
const read = (path) =>
  JSON.parse(
    readFileSync(
      new URL(`../../../contracts/${path}`, import.meta.url),
      "utf8",
    ),
  );
const { parseDocument, supportsCorrections } = createContractParser(
  read("schema/hachi.schema.json"),
);
test("Draft2020 generated documents validate without coercion or default mutation", () => {
  for (const [kind, path] of [
    ["SelfReportHistory", "empty"],
    ["SelfReportHistory", "recorded-entries"],
    ["SelfReportRequest", "symptoms-tests-and-alertness"],
    ["SelfReportRequest", "correction-of-onset"],
    ["ReportJob", "queued"],
    ["ReportJob", "completed"],
    ["ReportResult", "ok-recovery"],
    ["ReportResult", "ok-alertness-simulation"],
    ["ReportResult", "unavailable-recovery-no-episode"],
    ["ApiError", "validation-failed"],
  ]) {
    const document = read(`fixtures/${kind}/${path}.json`);
    const before = JSON.stringify(document);
    assert.equal(parseDocument(kind, document), document);
    assert.equal(JSON.stringify(document), before);
  }
  assert.equal(supportsCorrections, true);
});
test("malformed nested entries, extra response fields and invalid dates are refused", () => {
  const history = read("fixtures/SelfReportHistory/recorded-entries.json");
  const broken = structuredClone(history);
  broken.entries.find((entry) => entry.kind === "alertness_rating").value = "6";
  assert.throws(() => parseDocument("SelfReportHistory", broken));
  assert.throws(() =>
    parseDocument("SelfReportHistory", { ...history, unexpected: true }),
  );
  const badDate = structuredClone(history);
  badDate.entries[0].entered_at_utc = "2026-02-30T08:00:00Z";
  assert.throws(() => parseDocument("SelfReportHistory", badDate));
});
test("unrecognized schema keywords fail compilation rather than being ignored", () => {
  const schema = read("schema/hachi.schema.json");
  schema.$defs.SelfReportHistory.newValidationRule = true;
  const parser = createContractParser(schema);
  assert.throws(() =>
    parser.parseDocument(
      "SelfReportHistory",
      read("fixtures/SelfReportHistory/empty.json"),
    ),
  );
});
