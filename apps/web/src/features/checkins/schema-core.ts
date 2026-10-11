import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
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
export function createContractParser(schema: unknown) {
  if (!object(schema) || !object(schema.$defs))
    throw new Error("Contract schema is missing definitions.");

  const ajv = new Ajv2020({ strict: true });
  addFormats(ajv);
  // Pydantic emits these annotations. The schema's oneOf/anyOf and const rules
  // perform validation; OpenAPI's discriminator mapping is not an Ajv extension.
  ajv.addKeyword({
    keyword: "discriminator",
    schemaType: "object",
    valid: true,
  });
  ajv.addKeyword({
    keyword: "x-hachi-schema-version",
    schemaType: "string",
    valid: true,
  });
  ajv.addSchema(schema, "hachi");

  const references = {
    ApiError: { $ref: "hachi#/$defs/ApiError" },
    ReportJob: { $ref: "hachi#/$defs/ReportJob" },
    ReportResult: { $ref: "hachi#/$defs/ReportResult" },
    SelfReportHistory: { $ref: "hachi#/$defs/SelfReportHistory" },
    SelfReportRequest: { $ref: "hachi#/$defs/SelfReportRequest" },
  } satisfies { [K in keyof Documents]: { $ref: string } };

  function parseDocument<K extends keyof Documents>(
    kind: K,
    value: unknown,
  ): Documents[K] {
    const validate = ajv.compile<Documents[K]>(references[kind]);
    if (!validate(value))
      throw new Error(
        "The API response does not match the current Hachi contract. Reload after updating the API and web app together.",
      );
    return value;
  }

  const onsetDefinition = schema.$defs.SymptomOnsetEntry;
  const supportsCorrections =
    object(onsetDefinition) &&
    object(onsetDefinition.properties) &&
    "supersedes" in onsetDefinition.properties;

  return { parseDocument, supportsCorrections };
}
