# Birdstream configuration builder

This is a dependency-free, local browser tool for creating ignored
configuration files from tracked templates.

Run it from the repository root:

```bash
make configurator
```

Open `http://localhost:8099` and choose the repository folder. The application:

1. recursively finds files ending in `.example` or `.template`;
2. derives the target by removing that suffix;
3. loads values from the existing matching target when it exists;
4. leaves template keys empty when no matching current value exists;
5. lets you use individual or all template defaults deliberately; and
6. writes the generated target after browser permission, or downloads it.

For example:

| Template | Generated target |
|---|---|
| `.env.template` | `.env` |
| `mediamtx/mediamtx.yml.example` | `mediamtx/mediamtx.yml` |
| `pi-agent/config.yaml.example` | `pi-agent/config.yaml` |

Environment and YAML files are merged by key/path. Other templates are edited
as complete text files. All processing happens in the browser; there are no
network requests and no persistence such as cookies or local storage.

After loading a project, the **Cross-file consistency** panel displays:

- **MATCH**, **MISMATCH**, or **MISSING VALUE** for values that must be
  identical;
- linked or derived relationships for URLs, ports, and feature dependencies;
- the Mosquitto password-file entries that generated credentials must
  correspond to; and
- matching guidance directly beneath every related input.

Sensitive values are compared in browser memory but are not printed in the
consistency panel.

The primary folder picker works when `index.html` is opened directly from disk
and in browsers without the File System Access API. It operates in
download-only mode. Chrome and Edge on localhost additionally expose
**Open folder with write access**, which can save generated targets directly
after permission is granted.
