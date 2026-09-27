# UI-only preview

This is a static visual preview of the seven-step annotation workflow. It does not import the annotation backend, run detection, save files, or modify application state.

From the repository root, run:

```bash
python3 -m http.server 8080
```

Then open:

```text
http://127.0.0.1:8080/gradio/ui_preview/
```

You can also open `index.html` directly in a browser.
