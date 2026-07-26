((global) => {
const TEMPLATE_SUFFIXES = [".example", ".template"];

const CONFIG_RELATIONSHIPS = Object.freeze([
  {
    id: "srt-publish-user",
    title: "SRT publish username",
    kind: "exact",
    sensitive: false,
    refs: [
      { target: ".env", path: "MEDIAMTX_PUBLISH_USER" },
      { target: "pi-agent/config.yaml", path: "stream.srt.username" },
    ],
    note: "Every Pi uses these credentials when publishing SRT to MediaMTX.",
  },
  {
    id: "srt-publish-password",
    title: "SRT publish password",
    kind: "exact",
    sensitive: true,
    refs: [
      { target: ".env", path: "MEDIAMTX_PUBLISH_PASSWORD" },
      { target: "pi-agent/config.yaml", path: "stream.srt.password" },
    ],
    note: "The backend auth hook rejects a Pi when these differ.",
  },
  {
    id: "primary-media-path",
    title: "Primary MediaMTX path",
    kind: "exact",
    sensitive: false,
    refs: [
      { target: ".env", path: "MEDIAMTX_PATH" },
      { target: "pi-agent/config.yaml", path: "stream.srt.path" },
    ],
    note: "Additional cameras append the Pi and camera IDs to this base path.",
  },
  {
    id: "media-path-rule",
    title: "MediaMTX path authorization rule",
    kind: "dependency",
    sensitive: false,
    refs: [
      { target: ".env", path: "MEDIAMTX_PATH" },
      { external: "MediaMTX paths regex (~^birdcam...) in mediamtx.yml" },
    ],
    note: "Keep MEDIAMTX_PATH as birdcam unless you also update the MediaMTX paths regex.",
  },
  {
    id: "pi-mqtt-identity",
    title: "Pi ID and MQTT username",
    kind: "recommended",
    sensitive: false,
    refs: [
      { target: "pi-agent/config.yaml", path: "device.id" },
      { target: "pi-agent/config.yaml", path: "mqtt.username" },
    ],
    note: "They can differ technically, but keeping them identical makes per-device users and topics easy to audit.",
  },
  {
    id: "proxmox-lan-host",
    title: "Proxmox LAN address on the Pi",
    kind: "exact",
    sensitive: false,
    refs: [
      { target: "pi-agent/config.yaml", path: "mqtt.host" },
      { target: "pi-agent/config.yaml", path: "stream.srt.host" },
    ],
    note: "Both MQTT control and SRT media are sent to the Proxmox server.",
  },
  {
    id: "backend-mqtt-account",
    title: "Backend MQTT account",
    kind: "external",
    sensitive: true,
    refs: [
      { target: ".env", path: "MQTT_USERNAME" },
      { target: ".env", path: "MQTT_PASSWORD" },
      { external: "Mosquitto password database entry for the backend user" },
    ],
    note: "Create/update it with ./scripts/mosquitto-user.sh backend.",
  },
  {
    id: "mqtt-host-context",
    title: "MQTT host names are intentionally different",
    kind: "derived",
    sensitive: false,
    refs: [
      { target: ".env", path: "MQTT_HOST" },
      { target: "pi-agent/config.yaml", path: "mqtt.host" },
    ],
    note: "The backend uses Docker service name mosquitto; the Pi uses the Proxmox LAN IP or LAN DNS name.",
  },
  {
    id: "pi-mqtt-account",
    title: "Per-Pi MQTT account",
    kind: "external",
    sensitive: true,
    refs: [
      { target: "pi-agent/config.yaml", path: "mqtt.username" },
      { target: "pi-agent/config.yaml", path: "mqtt.password" },
      { external: "Mosquitto password database entry for this Pi user" },
    ],
    note: "Create/update it with ./scripts/mosquitto-user.sh <pi-id>.",
  },
  {
    id: "database-url",
    title: "PostgreSQL connection URL",
    kind: "derived",
    sensitive: true,
    refs: [
      { target: ".env", path: "POSTGRES_DB" },
      { target: ".env", path: "POSTGRES_USER" },
      { target: ".env", path: "POSTGRES_PASSWORD" },
      { target: ".env", path: "DATABASE_URL" },
    ],
    note: "DATABASE_URL must use the same user, password, and database with host db and port 5432.",
  },
  {
    id: "srt-port",
    title: "SRT ingest port",
    kind: "derived",
    sensitive: false,
    refs: [
      { target: "pi-agent/config.yaml", path: "stream.srt.port" },
      { target: "mediamtx/mediamtx.yml", path: "srtAddress" },
    ],
    note: "Pi port 8890 corresponds to MediaMTX address :8890 and the Compose UDP mapping.",
  },
  {
    id: "mediamtx-api",
    title: "MediaMTX control API",
    kind: "derived",
    sensitive: false,
    refs: [
      { target: ".env", path: "MEDIAMTX_API_URL" },
      { target: "mediamtx/mediamtx.yml", path: "apiAddress" },
    ],
    note: "http://mediamtx:9997 corresponds to MediaMTX address :9997.",
  },
  {
    id: "detection-rtsp",
    title: "Detection RTSP source",
    kind: "derived",
    sensitive: false,
    refs: [
      { target: ".env", path: "DETECTION_RTSP_BASE_URL" },
      { target: "mediamtx/mediamtx.yml", path: "rtspAddress" },
    ],
    note: "rtsp://mediamtx:8554 corresponds to MediaMTX address :8554.",
  },
  {
    id: "hls-fallback",
    title: "HLS fallback availability",
    kind: "dependency",
    sensitive: false,
    refs: [
      { target: ".env", path: "VITE_HLS_FALLBACK" },
      { target: "mediamtx/mediamtx.yml", path: "hls" },
    ],
    note: "When frontend fallback is true, MediaMTX hls must be yes. A false frontend flag simply leaves HLS unused.",
  },
  {
    id: "webrtc-hosts",
    title: "WebRTC advertised hosts",
    kind: "override",
    sensitive: false,
    refs: [
      { target: ".env", path: "WEBRTC_PUBLIC_HOSTS" },
      { target: "mediamtx/mediamtx.yml", path: "webrtcAdditionalHosts" },
      { target: "pi-agent/config.yaml", path: "mqtt.host" },
    ],
    note: "The .env list contains the raw public address and Proxmox LAN address. Compose overrides the YAML value, which should stay empty.",
  },
  {
    id: "public-app-url",
    title: "Public application URL",
    kind: "external",
    sensitive: false,
    refs: [
      { target: ".env", path: "APP_URL" },
      { external: "Cloudflare published application hostname" },
    ],
    note: "APP_URL must be the public HTTPS origin used by visitors and email links.",
  },
]);

function targetPathForTemplate(path) {
  const suffix = TEMPLATE_SUFFIXES.find((item) => path.endsWith(item));
  return suffix ? path.slice(0, -suffix.length) : null;
}

function isTemplatePath(path) {
  return targetPathForTemplate(path) !== null;
}

function documentKind(targetPath) {
  const name = targetPath.split("/").pop().toLowerCase();
  if (name === ".env" || name.endsWith(".env")) return "env";
  if (name.endsWith(".yml") || name.endsWith(".yaml")) return "yaml";
  return "text";
}

function isSensitiveKey(key) {
  return /(^|[._-])(password|passwd|secret|token|credential|api[_-]?key|private[_-]?key)([._-]|$)/i
    .test(key);
}

function precedingComment(lines, lineIndex) {
  const comments = [];
  for (let index = lineIndex - 1; index >= 0; index -= 1) {
    const trimmed = lines[index].trim();
    if (!trimmed.startsWith("#")) break;
    comments.unshift(trimmed.replace(/^#\s?/, ""));
  }
  return comments.join(" ");
}

function parseEnv(text) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const fields = [];
  lines.forEach((line, lineIndex) => {
    if (/^\s*#/.test(line)) return;
    const match = line.match(/^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*)$/);
    if (!match) return;
    fields.push({
      id: match[2],
      key: match[2],
      path: match[2],
      lineIndex,
      prefix: `${match[1]}${match[2]}${match[3]}`,
      suffix: "",
      templateValue: match[4],
      description: precedingComment(lines, lineIndex),
      sensitive: isSensitiveKey(match[2]),
    });
  });
  return { lines, fields };
}

function colonOutsideQuotes(value) {
  let quote = null;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    if (quote) {
      if (char === quote && value[index - 1] !== "\\") quote = null;
    } else if (char === "'" || char === '"') {
      quote = char;
    } else if (char === ":") {
      return index;
    }
  }
  return -1;
}

function splitYamlValue(value) {
  let quote = null;
  let depth = 0;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    if (quote) {
      if (char === quote && value[index - 1] !== "\\") quote = null;
      continue;
    }
    if (char === "'" || char === '"') quote = char;
    else if (char === "[" || char === "{") depth += 1;
    else if (char === "]" || char === "}") depth -= 1;
    else if (char === "#" && depth === 0 && (index === 0 || /\s/.test(value[index - 1]))) {
      const beforeComment = value.slice(0, index);
      const trimmedValue = beforeComment.trimEnd();
      return [trimmedValue, value.slice(trimmedValue.length)];
    }
  }
  const trimmedValue = value.trimEnd();
  return [trimmedValue, value.slice(trimmedValue.length)];
}

function cleanYamlKey(key) {
  const trimmed = key.trim();
  if (
    trimmed.length >= 2
    && ((trimmed.startsWith('"') && trimmed.endsWith('"'))
      || (trimmed.startsWith("'") && trimmed.endsWith("'")))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function parseYaml(text) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const fields = [];
  const stack = [];
  const sequenceIndexes = new Map();

  lines.forEach((line, lineIndex) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || trimmed === "---") return;

    const indent = line.match(/^\s*/)[0].length;
    while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop();
    const parentPath = stack.length ? stack[stack.length - 1].path : "";
    let content = line.slice(indent);
    let itemPath = parentPath;
    let sequencePrefix = "";

    if (content.startsWith("- ")) {
      const sequenceKey = `${parentPath}|${indent}`;
      const itemIndex = sequenceIndexes.get(sequenceKey) ?? 0;
      sequenceIndexes.set(sequenceKey, itemIndex + 1);
      itemPath = `${parentPath}[${itemIndex}]`;
      sequencePrefix = "- ";
      content = content.slice(2);
    }

    const colon = colonOutsideQuotes(content);
    if (colon < 0) {
      if (sequencePrefix) {
        const [templateValue, suffix] = splitYamlValue(content);
        fields.push({
          id: itemPath,
          key: itemPath.split(".").pop(),
          path: itemPath,
          lineIndex,
          prefix: `${" ".repeat(indent)}${sequencePrefix}`,
          suffix,
          templateValue,
          description: precedingComment(lines, lineIndex),
          sensitive: isSensitiveKey(itemPath),
        });
      }
      return;
    }

    const keySource = content.slice(0, colon);
    const key = cleanYamlKey(keySource);
    const path = itemPath ? `${itemPath}.${key}` : key;
    const rawAfterColon = content.slice(colon + 1);
    const leadingSpace = rawAfterColon.match(/^\s*/)[0];
    const [templateValue, suffix] = splitYamlValue(
      rawAfterColon.slice(leadingSpace.length),
    );
    const prefix = `${" ".repeat(indent)}${sequencePrefix}${keySource}:`;

    if (!templateValue) {
      stack.push({ indent, path });
      return;
    }

    fields.push({
      id: path,
      key,
      path,
      lineIndex,
      prefix: `${prefix}${leadingSpace}`,
      suffix,
      templateValue,
      description: precedingComment(lines, lineIndex),
      sensitive: isSensitiveKey(path),
    });
  });

  return { lines, fields };
}

function parseTemplate(text, kind) {
  if (kind === "env") return parseEnv(text);
  if (kind === "yaml") return parseYaml(text);
  return {
    lines: text.replace(/\r\n/g, "\n").split("\n"),
    fields: [{
      id: "__content__",
      key: "File content",
      path: "__content__",
      lineIndex: null,
      prefix: "",
      suffix: "",
      templateValue: text,
      description: "This template is edited as a complete text file.",
      sensitive: false,
    }],
  };
}

function mergeTemplate(templateText, currentText, kind) {
  const parsed = parseTemplate(templateText, kind);
  const current = currentText == null ? null : parseTemplate(currentText, kind);
  const currentValues = new Map(
    (current?.fields ?? []).map((field) => [field.path, field.templateValue]),
  );

  const fields = parsed.fields.map((field) => ({
    ...field,
    value: currentValues.has(field.path) ? currentValues.get(field.path) : "",
  }));

  if (kind === "text" && currentText != null) fields[0].value = currentText;
  return { ...parsed, fields };
}

function renderDocument(parsed, values, kind) {
  if (kind === "text") return values.__content__ ?? "";
  const lines = [...parsed.lines];
  parsed.fields.forEach((field) => {
    const value = values[field.id] ?? "";
    lines[field.lineIndex] = `${field.prefix}${value}${field.suffix}`;
  });
  return lines.join("\n");
}

function normalizeConfigValue(value) {
  const trimmed = String(value ?? "").trim();
  if (
    trimmed.length >= 2
    && ((trimmed.startsWith('"') && trimmed.endsWith('"'))
      || (trimmed.startsWith("'") && trimmed.endsWith("'")))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function compareRelationshipValues(values) {
  const normalized = values.map(normalizeConfigValue);
  if (normalized.some((value) => !value)) return "missing";
  return normalized.every((value) => value === normalized[0])
    ? "match"
    : "mismatch";
}

const api = Object.freeze({
  CONFIG_RELATIONSHIPS,
  targetPathForTemplate,
  isTemplatePath,
  documentKind,
  isSensitiveKey,
  parseEnv,
  parseYaml,
  parseTemplate,
  mergeTemplate,
  renderDocument,
  normalizeConfigValue,
  compareRelationshipValues,
});

global.BirdstreamConfiguratorCore = api;
if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
