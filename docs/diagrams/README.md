# Edit and render the diagrams

The README embeds SVG images so it does not depend on GitHub's Mermaid parser.
The `.mmd` files here are the editable source. Each diagram answers one question:

| Source | Question |
| --- | --- |
| `overview.mmd` | Who executes work, and who controls it? |
| `lifecycle.mmd` | What question does each delivery gate answer? |
| `model-call.mmd` | When can a request reach the provider? |
| `run-states.mmd` | What do pause, resume and stop mean? |
| `artifact-check.mmd` | How do checks bind to the artifact being staged? |

From the repository root, with Node.js 24 and Chrome or Chromium installed:

```sh
npm --prefix tools/diagrams ci --ignore-scripts
npm --prefix tools/diagrams run diagrams
npm --prefix tools/diagrams run check:diagrams
```

The renderer uses an installed browser, with no browser download. Set
`PUPPETEER_EXECUTABLE_PATH` if it is not in a standard location. `diagrams`
updates the SVGs; `check:diagrams` renders every source into a temporary directory
and validates README image references and source fingerprints. CI rejects stale
SVGs when a source, renderer configuration or tool lockfile changes. Commit source and SVG
changes together, and inspect the result for clipping, tiny text and tangled
arrows before publishing.
