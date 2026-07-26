const {
  CONFIG_RELATIONSHIPS,
  compareRelationshipValues,
  documentKind,
  isPiConfigTarget,
  isTemplatePath,
  isValidPiId,
  mergeTemplate,
  normalizeConfigValue,
  piConfigTarget,
  readTextSource,
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
    [...event.target.files].map((file) => [relativePath(file), file]),
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
    return {
      tone: "match",
      label: relationship.kind === "recommended"
        ? "RECOMMENDED MATCH"
        : "MATCH",
    };
  }
  return relationship.kind === "recommended"
    ? { tone: "review", label: "REVIEW" }
    : { tone: "mismatch", label: "MISMATCH" };
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

function refreshRelationshipStatuses() {
  CONFIG_RELATIONSHIPS.forEach((relationship) => {
    const status = relationshipStatus(relationship);
    const node = document.querySelector(
      `[data-relationship-status="${relationship.id}"]`,
    );
    if (!node) return;
    node.textContent = status.label;
    node.dataset.tone = status.tone;
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
      item.textContent = referenceLabel(reference);
      refs.append(item);
    });

    const note = document.createElement("p");
    note.textContent = relationship.note;
    card.append(cardHeading, refs, note);
    grid.append(card);
  });
  section.append(grid);
  return section;
}

function renderField(model, field) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";

  const heading = document.createElement("div");
  heading.className = "field-heading";
  const label = document.createElement("label");
  label.textContent = field.path === "__content__" ? "File content" : field.path;
  label.htmlFor = `field-${state.activeIndex}-${field.lineIndex ?? 0}`;
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
      const hint = document.createElement("p");
      const otherReferences = relationship.refs
        .filter((reference) => !(
          referenceTargetsModel(reference, model)
          && reference.path === field.path
        ))
        .map(referenceLabel);
      const prefixes = {
        exact: "Must match",
        recommended: "Recommended to match",
        external: "Must correspond to",
        derived: "Linked with",
        dependency: "Depends on",
        override: "Overrides",
      };
      hint.textContent = `${prefixes[relationship.kind] ?? "Related to"}: ${
        otherReferences.join(" · ")
      }`;
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
  editorNode.append(renderConsistencyMap());

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
