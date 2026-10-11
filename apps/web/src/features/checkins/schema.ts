import source from "../../../../../contracts/schema/hachi.schema.json?raw";
import { createContractParser } from "./schema-core";
export const { parseDocument, supportsCorrections } = createContractParser(
  JSON.parse(source),
);
