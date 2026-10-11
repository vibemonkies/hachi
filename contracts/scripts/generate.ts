// Generate typescript/index.ts from schema/hachi.schema.json. `--check` fails if it is stale.
import { compile } from "json-schema-to-typescript";

const root = new URL("..", import.meta.url);
const schemaFile = Bun.file(new URL("schema/hachi.schema.json", root));
const outUrl = new URL("typescript/index.ts", root);

const schema = await schemaFile.json();
const generated = await compile(schema, "HachiContracts", {
  bannerComment:
    "/* Generated from src/hachi/contracts by `make build`. Do not edit by hand. */",
  unreachableDefinitions: true,
  additionalProperties: false,
  strictIndexSignatures: true,
  format: true,
  style: { printWidth: 100 },
});

if (process.argv.includes("--check")) {
  const current = (await Bun.file(outUrl).exists()) ? await Bun.file(outUrl).text() : "";
  if (current !== generated) {
    console.error("typescript/index.ts is stale; run `make build`");
    process.exit(1);
  }
} else {
  await Bun.write(outUrl, generated);
}
