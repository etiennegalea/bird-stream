const {
  CONFIG_RELATIONSHIPS,
  buildMtlsCommand,
  compareRelationshipValues,
  documentKind,
  isPiConfigTarget,
  isTemplatePath,
  isValidPiId,
  mergeTemplate,
  normalizeConfigValue,
  piConfigTarget,
  readTextSource,
  parseMtlsDeviceIds,
  renderDocument,
  targetPathForTemplate,
} = globalThis.BirdstreamConfiguratorCore;

const BASE_PI_TARGET = "pi-agent/config.yaml";
const SKIP_DIRECTORIES = new Set([
  ".git", ".venv", "node_modules", "__pycache__", "data", "log",
]);

const state = {
  rootHandle: null,
  documents: [],
  activeIndex: -1,
  view: "overview",
  selectedPiTarget: null,
  newPiFormOpen: false,
  linkedRelationshipIds: new Set(),
  mtls: {
    brokerHost: "",
    brokerIps: "",
    deviceIds: "backend",
    outputDir: "mosquitto/pki",
  },
};

const statusNode = document.querySelector("#status");
const tabsNode = document.querySelector("#tabs");
const editorNode = document.querySelector("#editor");
const emptyNode = document.querySelector("#empty");
const saveButton = document.querySelector("#save-project");
const downloadButton = document.querySelector("#download");
const writeAccessButton = document.querySelector("#choose-project-write");

function setStatus(message, tone = "") {
  statusNode.textContent = message;
  statusNode.dataset.tone = tone;
}

function roleForTarget(targetPath) {
  if (targetPath === BASE_PI_TARGET || isPiConfigTarget(targetPath)) return "pi";
  if (targetPath.startsWith("pi-agent/")) return "support";
  return "server";
}

function decorateDocument(model) {
  return { ...model, role: roleForTarget(model.targetPath) };
}

function fieldFor(model, path) {
  return model?.parsed.fields.find((field) => field.path === path) ?? null;
}

function fieldValue(model, path) {
  return normalizeConfigValue(fieldFor(model, path)?.value);
}

function piModels() {
  return state.documents.filter((model) => model.role === "pi");
}

function piId(model) {
  const configured = fieldValue(model, "device.id");
  if (configured) return configured;
  const pathMatch = model.targetPath.match(/^pi-configs\/([^/]+)\//);
  return pathMatch?.[1] || "unconfigured-pi";
}

function selectedPiModel() {
  return state.documents.find(
    (model) => model.targetPath === state.selectedPiTarget && model.role === "pi",
  ) ?? piModels()[0] ?? null;
}

function initializeLoadedDocuments(documents) {
  state.documents = documents;
  state.activeIndex = -1;
  state.view = "overview";
  state.selectedPiTarget = piModels()[0]?.targetPath ?? null;
  state.newPiFormOpen = false;
  state.linkedRelationshipIds.clear();
  const piDevices = piModels()
    .filter((model) => fieldValue(model, "device.id"))
    .map(piId);
  state.mtls.deviceIds = ["backend", ...piDevices].join("\n");
  const configuredHost = fieldValue(piModels()[0], "mqtt.host");
  if (/^[0-9A-Fa-f:.]+$/.test(configuredHost)) {
    state.mtls.brokerIps = configuredHost;
  } else if (configuredHost) {
    state.mtls.brokerHost = configuredHost;
  }
}

async function walkDirectory(handle, prefix = "", files = new Map()) {
  for await (const [name, entry] of handle.entries()) {
    if (entry.kind === "directory") {
      if (!SKIP_DIRECTORIES.has(name)) {
        await walkDirectory(entry, prefix ? `${prefix}/${name}` : name, files);
      }
      continue;
    }
    const path = prefix ? `${prefix}/${name}` : name;
    files.set(path, entry);
  }
  return files;
}

async function loadFromHandles(files) {
  const templates = [...files.keys()].filter(isTemplatePath).sort();
  const documents = await Promise.all(templates.map(async (templatePath) => {
    const targetPath = targetPathForTemplate(templatePath);
    const templateText = await readTextSource(files.get(templatePath));
    const currentHandle = files.get(targetPath);
    const currentText = currentHandle
      ? await readTextSource(currentHandle)
      : null;
    const kind = documentKind(targetPath);
    return decorateDocument({
      templatePath,
      targetPath,
      templateText,
      currentText,
      kind,
      parsed: mergeTemplate(templateText, currentText, kind),
    });
  }));

  const piTemplate = documents.find(
    (model) => model.targetPath === BASE_PI_TARGET,
  );
  if (piTemplate) {
    const existingTargets = new Set(documents.map((model) => model.targetPath));
    const generatedPiPaths = [...files.keys()]
      .filter(isPiConfigTarget)
      .filter((path) => !existingTargets.has(path))
      .sort();
    for (const targetPath of generatedPiPaths) {
      const currentText = await readTextSource(files.get(targetPath));
      documents.push(decorateDocument({
        templatePath: piTemplate.templatePath,
        targetPath,
        templateText: piTemplate.templateText,
        currentText,
        kind: "yaml",
        parsed: mergeTemplate(piTemplate.templateText, currentText, "yaml"),
      }));
    }
  }

  return documents;
}

function relativePath(file) {
  const source = file.webkitRelativePath || file.name;
  const parts = source.split("/");
  return parts.length > 1 ? parts.slice(1).join("/") : parts[0];
}

async function chooseFolderFallback(event) {
  const files = new Map(
    [...event.target.files]
      .map((file) => [relativePath(file), file])
      .filter(([path]) => !path.split("/").some(
        (part) => SKIP_DIRECTORIES.has(part),
      )),
  );
  state.rootHandle = null;
  initializeLoadedDocuments(await loadFromHandles(files));
  setStatus("Folder loaded in download-only mode.", "success");
  render();
}

async function chooseProject() {
  try {
    state.rootHandle = await window.showDirectoryPicker({ mode: "readwrite" });
    const files = await walkDirectory(state.rootHandle);
    initializeLoadedDocuments(await loadFromHandles(files));
    setStatus("Project loaded with write access.", "success");
    render();
  } catch (error) {
    if (error.name !== "AbortError") setStatus(error.message, "error");
  }
}

function valuesFor(documentModel) {
  return Object.fromEntries(
    documentModel.parsed.fields.map((field) => [field.id, field.value]),
  );
}

function generatedContent(documentModel) {
  return renderDocument(
    documentModel.parsed,
    valuesFor(documentModel),
    documentModel.kind,
  );
}

function download(documentModel) {
  const blob = new Blob([generatedContent(documentModel)], {
    type: "text/plain;charset=utf-8",
  });
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = documentModel.role === "pi"
    ? `${piId(documentModel)}.config.yaml`
    : documentModel.targetPath.split("/").pop();
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
  setStatus(`Downloaded ${anchor.download}.`, "success");
}

async function getTargetHandle(root, path) {
  const parts = path.split("/");
  const filename = parts.pop();
  let directory = root;
  for (const part of parts) {
    directory = await directory.getDirectoryHandle(part, { create: true });
  }
  return directory.getFileHandle(filename, { create: true });
}

async function saveCurrent() {
  const model = state.documents[state.activeIndex];
  if (!state.rootHandle || !model) return;
  try {
    const handle = await getTargetHandle(state.rootHandle, model.targetPath);
    const writable = await handle.createWritable();
    await writable.write(generatedContent(model));
    await writable.close();
    model.currentText = generatedContent(model);
    setStatus(`Saved ${model.targetPath}. It remains ignored by Git.`, "success");
    render();
  } catch (error) {
    setStatus(`Could not save ${model.targetPath}: ${error.message}`, "error");
  }
}

function makeButton(label, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function showOverview(openNewPiForm = false) {
  state.view = "overview";
  state.activeIndex = -1;
  state.newPiFormOpen = openNewPiForm;
  render();
}

function showConsistency() {
  state.view = "consistency";
  state.activeIndex = -1;
  state.newPiFormOpen = false;
  render();
}

function showMtls() {
  state.view = "mtls";
  state.activeIndex = -1;
  state.newPiFormOpen = false;
  render();
}

function selectDocument(model) {
  const index = state.documents.indexOf(model);
  if (index < 0) return;
  state.activeIndex = index;
  state.view = model.role === "pi" ? "pi" : "server";
  state.newPiFormOpen = false;
  if (model.role === "pi") state.selectedPiTarget = model.targetPath;
  render();
}

function openServer() {
  const preferred = state.documents.find((model) => model.targetPath === ".env");
  const fallback = state.documents.find((model) => model.role === "server");
  if (preferred || fallback) selectDocument(preferred || fallback);
}

function makeTab(model) {
  const label = model.role === "pi" ? piId(model) : model.targetPath;
  const button = makeButton(label, "tab", () => selectDocument(model));
  button.classList.toggle(
    "active",
    state.activeIndex >= 0 && state.documents[state.activeIndex] === model,
  );
  return button;
}

function appendTabGroup(label, models) {
  if (!models.length) return;
  const heading = document.createElement("p");
  heading.className = "tab-group-label";
  heading.textContent = label;
  tabsNode.append(heading);
  models.forEach((model) => tabsNode.append(makeTab(model)));
}

function renderTabs() {
  tabsNode.replaceChildren();
  const overview = makeButton("Architecture", "tab overview-tab", () => {
    showOverview(false);
  });
  overview.classList.toggle("active", state.view === "overview");
  tabsNode.append(overview);

  const consistency = makeButton(
    "Cross-file consistency",
    "tab consistency-tab",
    showConsistency,
  );
  consistency.classList.toggle("active", state.view === "consistency");
  tabsNode.append(consistency);

  const mtls = makeButton(
    "MQTT mutual TLS",
    "tab mtls-tab",
    showMtls,
  );
  mtls.classList.toggle("active", state.view === "mtls");
  tabsNode.append(mtls);

  appendTabGroup(
    "PROXMOX SERVER",
    state.documents.filter((model) => model.role === "server"),
  );
  appendTabGroup("RASPBERRY PI", piModels());

  const addPi = makeButton("+ Add transmitter", "tab add-pi-tab", () => {
    showOverview(true);
  });
  tabsNode.append(addPi);

  appendTabGroup(
    "INSTALL TEMPLATES",
    state.documents.filter((model) => model.role === "support"),
  );
}

function referenceUsesPi(reference) {
  return reference.target === BASE_PI_TARGET;
}

function referenceTargetsModel(reference, model) {
  if (referenceUsesPi(reference) && model.role === "pi") return true;
  return reference.target === model.targetPath;
}

function findReferencedField(reference) {
  if (!reference.target) return null;
  const model = referenceUsesPi(reference)
    ? selectedPiModel()
    : state.documents.find(
      (documentModel) => documentModel.targetPath === reference.target,
    );
  const field = model?.parsed.fields.find(
    (candidate) => candidate.path === reference.path,
  );
  return model && field ? { model, field } : null;
}

function relationshipStatus(relationship) {
  if (!["exact", "recommended"].includes(relationship.kind)) {
    const labels = {
      external: ["external", "EXTERNAL CHECK"],
      derived: ["linked", "LINKED VALUES"],
      dependency: ["linked", "CHECK TOGETHER"],
      override: ["linked", "ENV OVERRIDES YAML"],
    };
    const [tone, label] = labels[relationship.kind] ?? ["linked", "RELATED"];
    return { tone, label };
  }

  const references = relationship.refs.filter((reference) => reference.target);
  const located = references.map(findReferencedField);
  if (located.some((item) => !item)) {
    return { tone: "unavailable", label: "TEMPLATE NOT LOADED" };
  }

  const comparison = compareRelationshipValues(
    located.map((item) => item.field.value),
  );
  if (comparison === "missing") {
    return { tone: "missing", label: "MISSING VALUE" };
  }
  if (comparison === "match") {
    return { tone: "match", label: "SAME" };
  }
  return { tone: "mismatch", label: "DIFFERENT" };
}

function referenceLabel(reference) {
  if (reference.external) return reference.external;
  const target = referenceUsesPi(reference)
    ? selectedPiModel()?.targetPath || reference.target
    : reference.target;
  return `${target} → ${reference.path}`;
}

function relationshipsForField(model, field) {
  return CONFIG_RELATIONSHIPS.filter((relationship) => relationship.refs.some(
    (reference) => referenceTargetsModel(reference, model)
      && reference.path === field.path,
  ));
}

function fieldInputId(model, field) {
  return `field-${state.documents.indexOf(model)}-${field.lineIndex ?? 0}`;
}

function openReference(reference) {
  const located = findReferencedField(reference);
  if (!located) return;
  selectDocument(located.model);
  requestAnimationFrame(() => {
    const input = document.getElementById(fieldInputId(located.model, located.field));
    input?.focus();
    input?.scrollIntoView({ behavior: "smooth", block: "center" });
    input?.closest(".field")?.classList.add("linked-field");
  });
}

function makeReferenceControl(reference) {
  if (!findReferencedField(reference)) {
    const text = document.createElement("span");
    text.textContent = referenceLabel(reference);
    return text;
  }
  const button = makeButton(referenceLabel(reference), "reference-link", () => {
    openReference(reference);
  });
  button.title = `Open ${referenceLabel(reference)}`;
  return button;
}

function synchronizeRelationship(relationship, preferredReference = null) {
  const located = relationship.refs
    .map((reference) => ({ reference, field: findReferencedField(reference) }))
    .filter((item) => item.field);
  const preferred = located.find(
    (item) => item.reference === preferredReference,
  )?.field;
  const source = preferred
    ? preferred
    : located.map((item) => item.field).find((item) => item.field.value);
  if (!source) return;
  located.forEach(({ field }) => {
    field.field.value = source.field.value;
    const input = document.getElementById(fieldInputId(field.model, field.field));
    if (input) input.value = source.field.value;
  });
}

function chainIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute(
    "d",
    "M10.6 13.4a1 1 0 0 0 1.4 0l2.8-2.8a3 3 0 1 0-4.2-4.2L9 8m5.6 2.6a1 1 0 0 0-1.4 0l-2.8 2.8a3 3 0 1 0 4.2 4.2L16 16",
  );
  svg.append(path);
  return svg;
}

function refreshChainButtons(relationship) {
  const linked = state.linkedRelationshipIds.has(relationship.id);
  document.querySelectorAll(
    `[data-chain-relationship="${relationship.id}"]`,
  ).forEach((button) => {
    button.classList.toggle("active", linked);
    button.setAttribute("aria-pressed", String(linked));
    button.title = linked
      ? `Unlink ${relationship.title}`
      : `Link ${relationship.title}`;
  });
}

function makeChainButton(relationship, preferredReference = null) {
  const button = makeButton("", "chain-button", () => {
    const linked = state.linkedRelationshipIds.has(relationship.id);
    if (linked) {
      state.linkedRelationshipIds.delete(relationship.id);
      setStatus(`${relationship.title} is no longer linked.`, "success");
    } else {
      state.linkedRelationshipIds.add(relationship.id);
      synchronizeRelationship(relationship, preferredReference);
      setStatus(`${relationship.title} is linked and will stay synchronized.`, "success");
      refreshRelationshipStatuses();
    }
    refreshChainButtons(relationship);
  });
  button.dataset.chainRelationship = relationship.id;
  button.setAttribute("aria-label", `Toggle link for ${relationship.title}`);
  button.append(chainIcon());
  const linked = state.linkedRelationshipIds.has(relationship.id);
  button.classList.toggle("active", linked);
  button.setAttribute("aria-pressed", String(linked));
  button.title = linked
    ? `Unlink ${relationship.title}`
    : `Link ${relationship.title}`;
  return button;
}

function refreshRelationshipStatuses() {
  CONFIG_RELATIONSHIPS.forEach((relationship) => {
    const status = relationshipStatus(relationship);
    document.querySelectorAll(
      `[data-relationship-status="${relationship.id}"]`,
    ).forEach((node) => {
      node.textContent = status.label;
      node.dataset.tone = status.tone;
    });
  });
}

function renderConsistencyMap() {
  const section = document.createElement("section");
  section.className = "consistency";

  const heading = document.createElement("div");
  heading.className = "consistency-heading";
  const title = document.createElement("h3");
  title.textContent = "Cross-file consistency";
  const help = document.createElement("p");
  const selectedPi = selectedPiModel();
  help.textContent = selectedPi
    ? `Compared with ${piId(selectedPi)}. Passwords are never displayed.`
    : "Add or select a Pi to compare transmitter values.";
  heading.append(title, help);
  section.append(heading);

  const grid = document.createElement("div");
  grid.className = "relation-grid";
  CONFIG_RELATIONSHIPS.forEach((relationship) => {
    const card = document.createElement("article");
    card.className = "relation-card";

    const cardHeading = document.createElement("div");
    const cardTitle = document.createElement("h4");
    cardTitle.textContent = relationship.title;
    const status = relationshipStatus(relationship);
    const badge = document.createElement("span");
    badge.className = "relation-status";
    badge.dataset.relationshipStatus = relationship.id;
    badge.dataset.tone = status.tone;
    badge.textContent = status.label;
    cardHeading.append(cardTitle, badge);

    const refs = document.createElement("ul");
    relationship.refs.forEach((reference) => {
      const item = document.createElement("li");
      item.append(makeReferenceControl(reference));
      refs.append(item);
    });

    const note = document.createElement("p");
    note.textContent = relationship.note;
    card.append(cardHeading, refs, note);
    if (["exact", "recommended"].includes(relationship.kind)) {
      card.append(makeChainButton(relationship));
    }
    grid.append(card);
  });
  section.append(grid);
  return section;
}

function renderConsistencyPage() {
  editorNode.classList.remove("architecture-editor");
  editorNode.replaceChildren(renderConsistencyMap());
}

function makeCodeBlock(value, label = "Copy") {
  const wrapper = document.createElement("div");
  wrapper.className = "code-block";
  const pre = document.createElement("pre");
  const code = document.createElement("code");
  code.textContent = value;
  pre.append(code);
  const copy = makeButton(label, "subtle code-copy", async () => {
    try {
      await navigator.clipboard.writeText(code.textContent);
      setStatus("Copied to clipboard.", "success");
    } catch {
      setStatus("Clipboard access was denied; select and copy the text.", "error");
    }
  });
  wrapper.append(copy, pre);
  return wrapper;
}

function makeMtlsInput({ id, label, help, value, multiline = false, onInput }) {
  const field = document.createElement("div");
  field.className = "mtls-field";
  const labelNode = document.createElement("label");
  labelNode.htmlFor = id;
  labelNode.textContent = label;
  const helpNode = document.createElement("p");
  helpNode.className = "description";
  helpNode.textContent = help;
  const input = multiline
    ? document.createElement("textarea")
    : document.createElement("input");
  input.id = id;
  input.value = value;
  input.spellcheck = false;
  input.addEventListener("input", () => onInput(input.value));
  field.append(labelNode, helpNode, input);
  return field;
}

function mtlsCommandResult() {
  try {
    return {
      command: buildMtlsCommand({
        brokerHost: state.mtls.brokerHost,
        brokerIps: state.mtls.brokerIps.split(/[\s,]+/).filter(Boolean),
        deviceIds: parseMtlsDeviceIds(state.mtls.deviceIds),
        outputDir: state.mtls.outputDir,
      }),
      error: "",
    };
  } catch (error) {
    return { command: "", error: error.message };
  }
}

function renderMtlsPage() {
  editorNode.classList.remove("architecture-editor");
  editorNode.replaceChildren();

  const header = document.createElement("header");
  const title = document.createElement("h2");
  title.textContent = "MQTT mutual TLS";
  const intro = document.createElement("p");
  intro.textContent = "Generate one private CA, a broker identity, and a unique certificate for the backend and every Pi. Certificate CNs become Mosquitto usernames, replacing MQTT passwords.";
  header.append(title, intro);
  editorNode.append(header);

  const warning = document.createElement("aside");
  warning.className = "mtls-callout";
  warning.textContent = "Use a DNS name that every client actually uses to connect. Add the LAN IP only when some clients connect by IP. The CA private key authorizes new devices; archive it offline after enrollment.";
  editorNode.append(warning);

  const form = document.createElement("section");
  form.className = "mtls-section";
  const formTitle = document.createElement("h3");
  formTitle.textContent = "1 · Prepare the generator command";
  const formGrid = document.createElement("div");
  formGrid.className = "mtls-form";
  const commandArea = document.createElement("div");
  commandArea.className = "mtls-command";

  const refreshCommand = () => {
    const result = mtlsCommandResult();
    commandArea.replaceChildren();
    if (result.error) {
      const error = document.createElement("p");
      error.className = "form-error";
      error.textContent = result.error;
      commandArea.append(error);
    } else {
      commandArea.append(makeCodeBlock(result.command, "Copy command"));
    }
  };

  formGrid.append(
    makeMtlsInput({
      id: "mtls-broker-host",
      label: "Broker DNS name",
      help: "Certificate hostname, for example mqtt.home.arpa. Do not include mqtt:// or a port.",
      value: state.mtls.brokerHost,
      onInput: (value) => {
        state.mtls.brokerHost = value;
        refreshCommand();
      },
    }),
    makeMtlsInput({
      id: "mtls-broker-ips",
      label: "Broker IP SANs",
      help: "Optional, comma or space separated. Include each IP clients use directly.",
      value: state.mtls.brokerIps,
      onInput: (value) => {
        state.mtls.brokerIps = value;
        refreshCommand();
      },
    }),
    makeMtlsInput({
      id: "mtls-device-ids",
      label: "Client certificate IDs",
      help: "One per line. Keep backend, then add every Pi device.id. Rerun later with a new ID to enroll another device.",
      value: state.mtls.deviceIds,
      multiline: true,
      onInput: (value) => {
        state.mtls.deviceIds = value;
        refreshCommand();
      },
    }),
    makeMtlsInput({
      id: "mtls-output-dir",
      label: "Private PKI directory",
      help: "Generated keys are ignored by Git. The default matches the Compose TLS overlay.",
      value: state.mtls.outputDir,
      onInput: (value) => {
        state.mtls.outputDir = value;
        refreshCommand();
      },
    }),
  );
  form.append(formTitle, formGrid, commandArea);
  editorNode.append(form);
  refreshCommand();

  const references = document.createElement("section");
  references.className = "mtls-section";
  const referencesTitle = document.createElement("h3");
  referencesTitle.textContent = "2 · Broker configuration references";
  const referenceList = document.createElement("ul");
  [
    ["mosquitto/config/mosquitto.conf", "Current password listener; retained as the default for a reversible migration."],
    ["mosquitto/config/mosquitto-mtls.conf.example", "mTLS listener on 8883; the Compose overlay mounts it as mosquitto.conf."],
    ["mosquitto/config/acl-mtls", "Maps certificate CNs to per-device topics and gives backend fleet access."],
    ["docker-compose.mtls.yml", "Mounts only the broker and backend identities into their containers."],
  ].forEach(([path, detail]) => {
    const item = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = path;
    item.append(code, document.createTextNode(` — ${detail}`));
    referenceList.append(item);
  });
  references.append(referencesTitle, referenceList);
  references.append(makeCodeBlock(
    [
      'MQTT_PORT="8883"',
      'MQTT_USERNAME=""',
      'MQTT_PASSWORD=""',
      'MQTT_TLS_ENABLED="true"',
      'MQTT_TLS_CA_CERT="/run/secrets/mqtt/ca.crt"',
      'MQTT_TLS_CLIENT_CERT="/run/secrets/mqtt/client.crt"',
      'MQTT_TLS_CLIENT_KEY="/run/secrets/mqtt/client.key"',
      "",
      "docker compose -f docker-compose.yml -f docker-compose.mtls.yml up -d",
    ].join("\n"),
    "Copy backend settings",
  ));
  editorNode.append(references);

  const pi = selectedPiModel();
  const device = pi && fieldValue(pi, "device.id") ? piId(pi) : "pi-01";
  const piSection = document.createElement("section");
  piSection.className = "mtls-section";
  const piTitle = document.createElement("h3");
  piTitle.textContent = `3 · Install the ${device} client bundle`;
  const piHelp = document.createElement("p");
  piHelp.className = "description";
  piHelp.textContent = "Copy only this device's bundle. Never copy ca.key, the backend key, or another Pi's key.";
  const piInstall = [
    `scp mosquitto/pki/clients/${device}/{ca.crt,client.crt,client.key} pi@${device}:/tmp/`,
    `ssh pi@${device} 'sudo install -d -m 755 /etc/birdstream/mqtt && sudo install -m 644 /tmp/ca.crt /tmp/client.crt /etc/birdstream/mqtt/ && sudo install -m 600 /tmp/client.key /etc/birdstream/mqtt/client.key'`,
  ].join("\n");
  const piYaml = [
    "mqtt:",
    "  port: 8883",
    "  username: null",
    "  password: null",
    "  tls:",
    "    enabled: true",
    "    ca_cert: /etc/birdstream/mqtt/ca.crt",
    "    client_cert: /etc/birdstream/mqtt/client.crt",
    "    client_key: /etc/birdstream/mqtt/client.key",
  ].join("\n");
  piSection.append(
    piTitle,
    piHelp,
    makeCodeBlock(piInstall, "Copy install commands"),
    makeCodeBlock(piYaml, "Copy Pi YAML"),
  );
  editorNode.append(piSection);

  const readme = document.createElement("section");
  readme.className = "mtls-section mtls-readme";
  const readmeTitle = document.createElement("h3");
  readmeTitle.textContent = "4 · Migration checklist";
  const steps = document.createElement("ol");
  [
    "Stop after generating the PKI and verify each expected client bundle exists.",
    "Deploy every Pi bundle and its YAML before disabling password authentication.",
    "Set the backend environment values above, then start the stack with the mTLS Compose overlay.",
    "Restart each Pi agent and confirm its status appears in the admin panel.",
    "Confirm port 1883 is no longer listening, then firewall it and archive ca.key offline.",
    "To add a Pi later, rerun the generator with its new --device ID; existing keys are never overwritten.",
  ].forEach((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    steps.append(item);
  });
  readme.append(readmeTitle, steps);
  editorNode.append(readme);
}

function renderField(model, field) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";

  const heading = document.createElement("div");
  heading.className = "field-heading";
  const label = document.createElement("label");
  label.textContent = field.path === "__content__" ? "File content" : field.path;
  label.htmlFor = fieldInputId(model, field);
  heading.append(label);
  heading.append(makeButton("Use template default", "subtle", () => {
    field.value = field.templateValue;
    renderEditor();
  }));
  wrapper.append(heading);

  if (field.description) {
    const description = document.createElement("p");
    description.className = "description";
    description.textContent = field.description;
    wrapper.append(description);
  }

  const relationships = relationshipsForField(model, field);
  if (relationships.length) {
    const hints = document.createElement("div");
    hints.className = "match-hints";
    relationships.forEach((relationship) => {
      const hint = document.createElement("div");
      hint.className = "match-hint";
      const otherReferences = relationship.refs
        .filter((reference) => !(
          referenceTargetsModel(reference, model)
          && reference.path === field.path
        ));
      const prefixes = {
        exact: "Must match",
        recommended: "Recommended to match",
        external: "Must correspond to",
        derived: "Linked with",
        dependency: "Depends on",
        override: "Overrides",
      };
      const prefix = document.createElement("span");
      prefix.textContent = `${prefixes[relationship.kind] ?? "Related to"}: `;
      hint.append(prefix);
      otherReferences.forEach((reference, index) => {
        if (index) hint.append(document.createTextNode(" · "));
        hint.append(makeReferenceControl(reference));
      });
      if (["exact", "recommended"].includes(relationship.kind)) {
        const status = relationshipStatus(relationship);
        const badge = document.createElement("span");
        badge.className = "relation-status field-relation-status";
        badge.dataset.relationshipStatus = relationship.id;
        badge.dataset.tone = status.tone;
        badge.textContent = status.label;
        hint.append(badge);
        const currentReference = relationship.refs.find(
          (reference) => referenceTargetsModel(reference, model)
            && reference.path === field.path,
        );
        hint.append(makeChainButton(relationship, currentReference));
      }
      hints.append(hint);
    });
    wrapper.append(hints);
  }

  const value = field.value ?? "";
  const isLong = field.path === "__content__" || value.length > 100;
  const input = isLong
    ? document.createElement("textarea")
    : document.createElement("input");
  input.id = label.htmlFor;
  if (!isLong) input.type = field.sensitive ? "password" : "text";
  input.value = value;
  input.placeholder = field.templateValue || "Required value";
  input.spellcheck = false;
  input.addEventListener("input", () => {
    field.value = input.value;
    relationships
      .filter((relationship) => (
        ["exact", "recommended"].includes(relationship.kind)
        && state.linkedRelationshipIds.has(relationship.id)
      ))
      .forEach((relationship) => {
        const currentReference = relationship.refs.find(
          (reference) => referenceTargetsModel(reference, model)
            && reference.path === field.path,
        );
        synchronizeRelationship(relationship, currentReference);
      });
    refreshPreview(model);
    refreshRelationshipStatuses();
  });
  wrapper.append(input);

  if (field.sensitive && !isLong) {
    wrapper.append(makeButton("Show / hide", "reveal", () => {
      input.type = input.type === "password" ? "text" : "password";
    }));
  }
  return wrapper;
}

function refreshPreview(model) {
  const preview = editorNode.querySelector("#preview");
  if (preview) preview.value = generatedContent(model);
}

function renderEditor() {
  editorNode.classList.remove("architecture-editor");
  editorNode.replaceChildren();
  const model = state.documents[state.activeIndex];
  if (!model) return;

  const header = document.createElement("header");
  const title = document.createElement("h2");
  title.textContent = model.role === "pi"
    ? `Raspberry Pi · ${piId(model)}`
    : model.targetPath;
  const source = document.createElement("p");
  source.textContent = `Target: ${model.targetPath} · Template: ${
    model.templatePath
  } · Existing target: ${
    model.currentText == null ? "not found" : "loaded"
  }`;
  header.append(title, source);

  const defaults = makeButton(
    "Fill empty fields from template defaults",
    "secondary",
    () => {
      model.parsed.fields.forEach((field) => {
        if (!field.value) field.value = field.templateValue;
      });
      renderEditor();
    },
  );
  header.append(defaults);
  editorNode.append(header);

  const form = document.createElement("div");
  form.className = "fields";
  model.parsed.fields.forEach((field) => form.append(renderField(model, field)));
  editorNode.append(form);

  const previewDetails = document.createElement("details");
  previewDetails.className = "preview-details";
  const previewSummary = document.createElement("summary");
  previewSummary.textContent = "Reveal generated preview";
  const previewWarning = document.createElement("p");
  previewWarning.className = "description";
  previewWarning.textContent = "The preview can contain plaintext secrets. Keep it collapsed when screen sharing.";
  const previewLabel = document.createElement("label");
  previewLabel.className = "preview-label";
  previewLabel.htmlFor = "preview";
  previewLabel.textContent = "Generated preview";
  const preview = document.createElement("textarea");
  preview.id = "preview";
  preview.className = "preview";
  preview.readOnly = true;
  preview.value = generatedContent(model);
  previewDetails.append(previewSummary, previewWarning, previewLabel, preview);
  editorNode.append(previewDetails);
}

function configuredFieldCount(model) {
  const relevantPaths = [
    "device.id",
    "mqtt.host",
    "mqtt.username",
    "mqtt.password",
    "stream.srt.host",
    "stream.srt.username",
    "stream.srt.password",
  ];
  return relevantPaths.filter((path) => fieldValue(model, path)).length;
}

function makePiCard(model) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "architecture-node pi-node";
  card.addEventListener("click", () => selectDocument(model));

  const top = document.createElement("span");
  top.className = "node-kicker";
  top.textContent = "RASPBERRY PI TRANSMITTER";
  const title = document.createElement("strong");
  title.textContent = piId(model);
  const path = document.createElement("code");
  path.textContent = model.targetPath;
  const progress = document.createElement("span");
  progress.className = "node-status";
  progress.textContent = `${configuredFieldCount(model)}/7 required values set`;

  const cameras = document.createElement("span");
  cameras.className = "camera-row";
  cameras.append(
    Object.assign(document.createElement("i"), { textContent: "CAM 1" }),
    Object.assign(document.createElement("i"), { textContent: "CAM +" }),
  );

  card.append(top, title, path, progress, cameras);
  return card;
}

function createNewPi(piIdValue) {
  const id = piIdValue.trim();
  if (!isValidPiId(id)) {
    return "Use 1–64 letters, numbers, underscores, or dashes.";
  }
  if (piModels().some((model) => piId(model) === id)) {
    return `A transmitter named ${id} already exists.`;
  }

  const template = state.documents.find(
    (model) => model.targetPath === BASE_PI_TARGET,
  ) ?? piModels()[0];
  if (!template) return "The Pi config template was not loaded.";

  const parsed = mergeTemplate(template.templateText, null, "yaml");
  parsed.fields.forEach((field) => {
    field.value = field.templateValue;
  });
  const idField = parsed.fields.find((field) => field.path === "device.id");
  const mqttUser = parsed.fields.find((field) => field.path === "mqtt.username");
  if (idField) idField.value = `"${id}"`;
  if (mqttUser) mqttUser.value = `"${id}"`;

  const model = decorateDocument({
    templatePath: template.templatePath,
    targetPath: piConfigTarget(id),
    templateText: template.templateText,
    currentText: null,
    kind: "yaml",
    parsed,
    createdInSession: true,
  });
  state.documents.push(model);
  state.selectedPiTarget = model.targetPath;
  state.mtls.deviceIds = [
    ...parseMtlsDeviceIds(state.mtls.deviceIds),
    id,
  ].filter((value, index, values) => values.indexOf(value) === index).join("\n");
  setStatus(
    `Created ${model.targetPath}. Save it to the project or download it.`,
    "success",
  );
  selectDocument(model);
  return null;
}

function renderNewPiForm(container) {
  const panel = document.createElement("form");
  panel.className = "new-pi-panel";
  const title = document.createElement("h3");
  title.textContent = "Add Raspberry Pi transmitter";
  const help = document.createElement("p");
  help.textContent = "A new ignored config will be created from pi-agent/config.yaml.example.";
  const label = document.createElement("label");
  label.htmlFor = "new-pi-id";
  label.textContent = "Unique device ID";
  const input = document.createElement("input");
  input.id = "new-pi-id";
  input.name = "pi-id";
  input.placeholder = "pi-02";
  input.autocomplete = "off";
  input.required = true;
  const error = document.createElement("p");
  error.className = "form-error";
  error.setAttribute("aria-live", "polite");
  const actions = document.createElement("div");
  actions.className = "new-pi-actions";
  const create = makeButton("Create transmitter config", "", () => {});
  create.type = "submit";
  const cancel = makeButton("Cancel", "secondary", () => {
    state.newPiFormOpen = false;
    renderArchitecture();
  });
  actions.append(create, cancel);
  panel.append(title, help, label, input, error, actions);
  panel.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = createNewPi(input.value);
    if (message) error.textContent = message;
  });
  container.append(panel);
  input.focus();
}

function renderArchitecture() {
  editorNode.classList.add("architecture-editor");
  editorNode.replaceChildren();

  const header = document.createElement("div");
  header.className = "architecture-heading";
  const title = document.createElement("h2");
  title.textContent = "Deployment configuration map";
  const help = document.createElement("p");
  help.textContent = "Select a machine to edit only the configuration deployed to it.";
  header.append(title, help);
  editorNode.append(header);

  const map = document.createElement("section");
  map.className = "deployment-map";

  const publicEdge = document.createElement("div");
  publicEdge.className = "public-edge";
  publicEdge.innerHTML = "<span>PUBLIC VIEWERS</span><strong>Cloudflare + WebRTC</strong>";

  const publicLink = document.createElement("div");
  publicLink.className = "map-link vertical-link";
  publicLink.innerHTML = "<span>HTTPS signaling</span><span>UDP 8189 media</span>";

  const proxmox = document.createElement("button");
  proxmox.type = "button";
  proxmox.className = "architecture-node proxmox-node";
  proxmox.addEventListener("click", openServer);
  const proxmoxKicker = document.createElement("span");
  proxmoxKicker.className = "node-kicker";
  proxmoxKicker.textContent = "PROXMOX SERVER";
  const proxmoxTitle = document.createElement("strong");
  proxmoxTitle.textContent = "Media and application hub";
  const services = document.createElement("span");
  services.className = "service-grid";
  ["Traefik", "Backend", "Frontend", "Postgres", "MediaMTX", "Mosquitto"]
    .forEach((name) => {
      const service = document.createElement("i");
      service.textContent = name;
      services.append(service);
    });
  const serverAction = document.createElement("span");
  serverAction.className = "node-action";
  serverAction.textContent = "Configure server →";
  proxmox.append(proxmoxKicker, proxmoxTitle, services, serverAction);

  const lanLink = document.createElement("div");
  lanLink.className = "map-link vertical-link";
  lanLink.innerHTML = "<span>MQTT control ↕</span><span>SRT streams ↑</span>";

  const fleet = document.createElement("div");
  fleet.className = "pi-fleet";
  const fleetHeading = document.createElement("div");
  const fleetTitle = document.createElement("h3");
  fleetTitle.textContent = "Raspberry Pi transmitters";
  const add = makeButton("+", "add-pi-button", () => {
    state.newPiFormOpen = true;
    renderArchitecture();
  });
  add.title = "Create a new Raspberry Pi configuration";
  add.setAttribute("aria-label", "Add Raspberry Pi transmitter");
  fleetHeading.append(fleetTitle, add);

  const cards = document.createElement("div");
  cards.className = "pi-card-grid";
  piModels().forEach((model) => cards.append(makePiCard(model)));
  fleet.append(fleetHeading, cards);
  if (state.newPiFormOpen) renderNewPiForm(fleet);

  map.append(publicEdge, publicLink, proxmox, lanLink, fleet);
  editorNode.append(map);

  const note = document.createElement("p");
  note.className = "architecture-note";
  note.textContent = "Generated Pi configs are stored under pi-configs/<device-id>/config.yaml and remain ignored by Git.";
  editorNode.append(note);
}

function render() {
  const hasDocuments = state.documents.length > 0;
  emptyNode.hidden = hasDocuments;
  tabsNode.hidden = !hasDocuments;
  editorNode.hidden = !hasDocuments;

  const model = state.activeIndex >= 0
    ? state.documents[state.activeIndex]
    : null;
  downloadButton.disabled = !model;
  downloadButton.textContent = model?.role === "pi"
    ? `Download ${piId(model)} config`
    : "Download current file";
  saveButton.hidden = !state.rootHandle || !model;

  if (!hasDocuments) {
    setStatus("No supported .example or .template files were found.", "error");
    return;
  }
  renderTabs();
  if (state.view === "overview") renderArchitecture();
  else if (state.view === "consistency") renderConsistencyPage();
  else if (state.view === "mtls") renderMtlsPage();
  else renderEditor();
}

writeAccessButton.addEventListener("click", chooseProject);
document.querySelector("#folder-fallback").addEventListener(
  "change",
  chooseFolderFallback,
);
downloadButton.addEventListener("click", () => {
  const model = state.documents[state.activeIndex];
  if (model) download(model);
});
saveButton.addEventListener("click", saveCurrent);

if (
  typeof window.showDirectoryPicker === "function"
  && window.isSecureContext
) {
  writeAccessButton.hidden = false;
}
