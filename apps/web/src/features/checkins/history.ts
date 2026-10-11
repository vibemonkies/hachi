import type { UtcDatetime } from "../../../../../contracts/typescript/index";
import type { CheckinApi } from "./client";
import { supportsCorrections } from "./schema";

export async function readCheckinHistory(
  api: CheckinApi,
  subjectId: string,
  asOf?: UtcDatetime,
) {
  const history = await api.history(subjectId, "current", asOf);
  // Episode roots must come from the same recording cutoff as visible entries.
  const versions = supportsCorrections
    ? (await api.history(subjectId, "all", asOf)).entries
    : history.entries;
  return { history, versions };
}
