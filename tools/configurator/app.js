const {
  CONFIG_RELATIONSHIPS,
  compareRelationshipValues,
  documentKind,
  isTemplatePath,
  mergeTemplate,
  renderDocument,
  targetPathForTemplate,
} = globalThis.BirdstreamConfiguratorCore;

const SKIP_DIRECTORIES = new Set([
  ".git", ".venv", "node_modules", "__pycache__", "data", "log",
]);

const state = {
  rootHandle: null,
  documents: [],
  activeIndex: 0,
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

async function readHandle(handle) {
  return (await handle.getFile()).text();
}

async function loadFromHandles(files) {
  const templates = [...files.keys()].filter(isTemplatePath).sort();
  return Promise.all(templates.map(async (templatePath) => {
    const targetPath = targetPathForTemplate(templatePath);
    const templateText = await readHandle(files.get(templatePath));
    const currentHandle = files.get(targetPath);
    const currentText = currentHandle ? await readHandle(currentHandle) : null;
    const kind = documentKind(targetPath);
    return {
      templatePath,
      targetPath,
      templateText,
      currentText,
      kind,
      parsed: mergeTemplate(templateText, currentText, kind),
    };
  }));
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
  state.documents = await loadFromHandles(files);
  state.activeIndex = 0;
  saveButton.hidden = true;
  setStatus("Folder loaded in download-only mode.", "success");
  render();
}

async function chooseProject() {
  try {
    state.rootHandle = await window.showDirectoryPicker({ mode: "readwrite" });
    const files = await walkDirectory(state.rootHandle);
    state.documents = await loadFromHandles(files);
    state.activeIndex = 0;
    saveButton.hidden = false;
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
  anchor.download = documentModel.targetPath.split("/").pop();
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
  setStatus(`Downloaded ${documentModel.targetPath}.`, "success");
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
    setStatus(`Saved ${model.targetPath}. It should remain ignored by Git.`, "success");
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

function renderTabs() {
  tabsNode.replaceChildren();
  state.documents.forEach((model, index) => {
    const button = makeButton(model.targetPath, "tab", () => {
      state.activeIndex = index;
      render();
    });
    button.classList.toggle("active", index === state.activeIndex);
    tabsNode.append(button);
  });
}

function findReferencedField(reference) {
  if (!reference.target) return null;
  const model = state.documents.find(
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
  return reference.external
    ? reference.external
    : `${reference.target} → ${reference.path}`;
}

function relationshipsForField(model, field) {
  return CONFIG_RELATIONSHIPS.filter((relationship) => relationship.refs.some(
    (reference) => reference.target === model.targetPath
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
  help.textContent = "Passwords are compared locally but never displayed here.";
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
          reference.target === model.targetPath
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

  const isLong = field.path === "__content__" || field.value.length > 100;
  const input = isLong ? document.createElement("textarea") : document.createElement("input");
  input.id = label.htmlFor;
  if (!isLong) input.type = field.sensitive ? "password" : "text";
  input.value = field.value;
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
  editorNode.replaceChildren();
  const model = state.documents[state.activeIndex];
  if (!model) return;

  const header = document.createElement("header");
  const title = document.createElement("h2");
  title.textContent = model.targetPath;
  const source = document.createElement("p");
  source.textContent = `Template: ${model.templatePath} · Existing target: ${
    model.currentText == null ? "not found; unmatched values are empty" : "loaded"
  }`;
  header.append(title, source);

  const defaults = makeButton("Fill every empty field from template defaults", "secondary", () => {
    model.parsed.fields.forEach((field) => {
      if (!field.value) field.value = field.templateValue;
    });
    renderEditor();
  });
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

function render() {
  const hasDocuments = state.documents.length > 0;
  emptyNode.hidden = hasDocuments;
  tabsNode.hidden = !hasDocuments;
  editorNode.hidden = !hasDocuments;
  downloadButton.disabled = !hasDocuments;
  saveButton.disabled = !hasDocuments;

  if (!hasDocuments) {
    setStatus("No supported .example or .template files were found.", "error");
    return;
  }
  setStatus(
    `Found ${state.documents.length} templates. Existing matching files were loaded locally.`,
    "success",
  );
  renderTabs();
  renderEditor();
}

writeAccessButton.addEventListener("click", chooseProject);
document.querySelector("#folder-fallback").addEventListener("change", chooseFolderFallback);
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
