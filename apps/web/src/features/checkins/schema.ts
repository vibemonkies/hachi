import source from "../../../../../contracts/schema/hachi.schema.json?raw";
import type {
  ApiError,
  ReportJob,
  ReportResult,
  SelfReportHistory,
  SelfReportRequest,
} from "../../../../../contracts/typescript/index";

type Documents = {
  ApiError: ApiError;
  ReportJob: ReportJob;
  ReportResult: ReportResult;
  SelfReportHistory: SelfReportHistory;
  SelfReportRequest: SelfReportRequest;
};
function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
const schema: unknown = JSON.parse(source);
if (!object(schema) || !object(schema.$defs))
  throw new Error("Contract schema is missing definitions.");
const definitions = schema.$defs;

// Temporary until the coordinated Ajv dependency lands. Refuse new validation
// keywords rather than accepting a shape this reader does not understand.
const supportedKeywords = new Set([
  "$ref",
  "type",
  "anyOf",
  "oneOf",
  "const",
  "enum",
  "minLength",
  "maxLength",
  "pattern",
  "format",
  "minimum",
  "maximum",
  "exclusiveMinimum",
  "exclusiveMaximum",
  "minItems",
  "maxItems",
  "items",
  "properties",
  "required",
  "additionalProperties",
  "title",
  "description",
  "default",
  "discriminator",
]);
// The committed generated schema owns response shapes; the API owns cross-field domain rules.
function matches(value: unknown, rule: unknown): boolean {
  if (
    !object(rule) ||
    Object.keys(rule).some((keyword) => !supportedKeywords.has(keyword))
  )
    return false;
  if (typeof rule.$ref === "string")
    return matches(value, definitions[rule.$ref.replace("#/$defs/", "")]);
  if (
    Array.isArray(rule.anyOf) &&
    !rule.anyOf.some((part) => matches(value, part))
  )
    return false;
  if (
    Array.isArray(rule.oneOf) &&
    rule.oneOf.filter((part) => matches(value, part)).length !== 1
  )
    return false;
  if ("const" in rule && value !== rule.const) return false;
  if (Array.isArray(rule.enum) && !rule.enum.includes(value)) return false;
  switch (rule.type) {
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "string":
      if (typeof value !== "string") return false;
      if (typeof rule.minLength === "number" && value.length < rule.minLength)
        return false;
      if (typeof rule.maxLength === "number" && value.length > rule.maxLength)
        return false;
      if (
        typeof rule.pattern === "string" &&
        !new RegExp(rule.pattern).test(value)
      )
        return false;
      if (rule.format === "date-time" && !Number.isFinite(Date.parse(value)))
        return false;
      return true;
    case "integer":
    case "number":
      if (typeof value !== "number" || !Number.isFinite(value)) return false;
      if (rule.type === "integer" && !Number.isInteger(value)) return false;
      if (typeof rule.minimum === "number" && value < rule.minimum)
        return false;
      if (typeof rule.maximum === "number" && value > rule.maximum)
        return false;
      if (
        typeof rule.exclusiveMinimum === "number" &&
        value <= rule.exclusiveMinimum
      )
        return false;
      if (
        typeof rule.exclusiveMaximum === "number" &&
        value >= rule.exclusiveMaximum
      )
        return false;
      return true;
    case "array":
      if (!Array.isArray(value)) return false;
      if (typeof rule.minItems === "number" && value.length < rule.minItems)
        return false;
      if (typeof rule.maxItems === "number" && value.length > rule.maxItems)
        return false;
      return value.every((item) => matches(item, rule.items));
    case "object": {
      if (!object(value) || !object(rule.properties)) return false;
      const properties = rule.properties;
      if (
        Array.isArray(rule.required) &&
        !rule.required.every((key) => typeof key === "string" && key in value)
      )
        return false;
      return Object.entries(value).every(([key, item]) =>
        key in properties
          ? matches(item, properties[key])
          : rule.additionalProperties !== false,
      );
    }
    default:
      return true;
  }
}
export function parseDocument<K extends keyof Documents>(
  kind: K,
  value: unknown,
): Documents[K] {
  if (!matches(value, definitions[kind]))
    throw new Error(
      "The API response does not match the current Hachi contract. Reload after updating the API and web app together.",
    );
  // Kept at this single schema-validated boundary; callers never cast network data.
  return value as Documents[K];
}

const onsetDefinition = definitions.SymptomOnsetEntry;
export const supportsCorrections =
  object(onsetDefinition) &&
  object(onsetDefinition.properties) &&
  "supersedes" in onsetDefinition.properties;
