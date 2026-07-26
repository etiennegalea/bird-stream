import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const {
  CONFIG_RELATIONSHIPS,
  compareRelationshipValues,
  documentKind,
  isPiConfigTarget,
  isValidPiId,
  mergeTemplate,
  parseYaml,
  piConfigTarget,
  readTextSource,
  renderDocument,
  targetPathForTemplate,
} = require("./core.js");

test("maps example and template names to generated targets", () => {
  assert.equal(targetPathForTemplate(".env.template"), ".env");
  assert.equal(
    targetPathForTemplate("mediamtx/mediamtx.yml.example"),
    "mediamtx/mediamtx.yml",
  );
  assert.equal(targetPathForTemplate("README.md"), null);
});

test("merges env keys from current file and leaves missing values empty", () => {
  const template = "# App\nHOST=\"example\"\nPASSWORD=\"change-me\"\nPORT=80\n";
  const current = "HOST=\"server\"\nPASSWORD=\"secret\"\n";
  const parsed = mergeTemplate(template, current, "env");
  const values = Object.fromEntries(parsed.fields.map((field) => [field.id, field.value]));

  assert.deepEqual(values, {
    HOST: '"server"',
    PASSWORD: '"secret"',
    PORT: "",
  });
  assert.equal(
    renderDocument(parsed, values, "env"),
    "# App\nHOST=\"server\"\nPASSWORD=\"secret\"\nPORT=\n",
  );
});

test("merges nested YAML and sequence values by path", () => {
  const template = [
    "webrtc: yes",
    "servers:",
    "  - url: stun:default",
    "paths:",
    '  "~^birdcam$":',
    "    source: publisher",
    "",
  ].join("\n");
  const current = [
    "webrtc: no",
    "servers:",
    "  - url: stun:custom",
    "",
  ].join("\n");
  const parsed = mergeTemplate(template, current, "yaml");
  const values = Object.fromEntries(parsed.fields.map((field) => [field.id, field.value]));

  assert.equal(values.webrtc, "no");
  assert.equal(values["servers[0].url"], "stun:custom");
  assert.equal(values['paths.~^birdcam$.source'], "");
});

test("parses MediaMTX regex path as a nested YAML key", () => {
  const parsed = parseYaml([
    "paths:",
    '  \"~^birdcam(-[A-Za-z0-9_-]+)*$\":',
    "    source: publisher",
  ].join("\n"));
  assert.equal(
    parsed.fields.at(-1).path,
    "paths.~^birdcam(-[A-Za-z0-9_-]+)*$.source",
  );
});

test("recognizes configuration document kinds", () => {
  assert.equal(documentKind(".env"), "env");
  assert.equal(documentKind("pi-agent/config.yaml"), "yaml");
  assert.equal(documentKind("service.conf"), "text");
});

test("compares quoted and YAML relationship values without revealing them", () => {
  assert.equal(compareRelationshipValues(['"picam"', "picam"]), "match");
  assert.equal(compareRelationshipValues(['"secret-one"', '"secret-two"']), "mismatch");
  assert.equal(compareRelationshipValues(['"picam"', ""]), "missing");
});

test("declares unique cross-file relationship identifiers", () => {
  const ids = CONFIG_RELATIONSHIPS.map((relationship) => relationship.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(CONFIG_RELATIONSHIPS.some(
    (relationship) => relationship.id === "srt-publish-password"
      && relationship.kind === "exact"
      && relationship.sensitive,
  ));
});

test("creates safe per-device Pi configuration targets", () => {
  assert.equal(isValidPiId("pi-02"), true);
  assert.equal(isValidPiId("../escape"), false);
  assert.equal(piConfigTarget("garden_pi-2"), "pi-configs/garden_pi-2/config.yaml");
  assert.equal(isPiConfigTarget("pi-configs/garden_pi-2/config.yaml"), true);
  assert.equal(isPiConfigTarget("pi-configs/../../config.yaml"), false);
  assert.throws(() => piConfigTarget("../escape"), /Invalid Raspberry Pi/);
});

test("reads both browser File objects and writable file handles", async () => {
  assert.equal(
    await readTextSource({ text: async () => "download-only" }),
    "download-only",
  );
  assert.equal(
    await readTextSource({
      getFile: async () => ({ text: async () => "write-access" }),
    }),
    "write-access",
  );
  await assert.rejects(() => readTextSource({}), /Unsupported configuration/);
});
