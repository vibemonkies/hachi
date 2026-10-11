import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import contractSource from "../../../../contracts/schema/hachi.schema.json?raw";

type SchemaDefinition = "Coverage" | "ImportStatus" | "ReportJob" | "ReportResult";

const schema = JSON.parse(contractSource) as { $defs: Record<string, unknown> };
const ajv = new Ajv2020({ strict: true });
addFormats(ajv);
ajv.addKeyword({ keyword: "discriminator", schemaType: "object", valid: true });
ajv.addKeyword({ keyword: "x-hachi-schema-version", schemaType: "string", valid: true });
ajv.addSchema(schema, "hachi");

const validators = new Map<SchemaDefinition, ReturnType<typeof ajv.compile>>();

export function parseContractDocument<T>(kind: SchemaDefinition, value: unknown): T {
  let validate = validators.get(kind);
  if (!validate) {
    validate = ajv.compile({ $ref: `hachi#/$defs/${kind}` });
    validators.set(kind, validate);
  }
  if (!validate(value)) {
    throw new Error("The API response does not match the current Hachi contract.");
  }
  return value as T;
}
