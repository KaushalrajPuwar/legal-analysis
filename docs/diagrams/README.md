# Diagrams

Two diagrams are kept here as editable Mermaid sources plus rendered images.

| File | Shows | Use |
|---|---|---|
| `architecture.mmd` | Core runtime architecture: client, application, document processing, legal evidence, assessment, data and models | Slides, reports, design reviews |
| `uml-model.mmd` | UML class model of the implemented slice: domain composition and service dependencies | Technical review, implementation handover |

Rendered outputs:

- `architecture.png`, 2352 by 624 pixels, scale 3
- `architecture.svg`, vector
- `uml-model.png`, 2352 by 1089 pixels, scale 3
- `uml-model.svg`, vector

## Reading the architecture diagram

The diagram reads left to right as the request path:

```text
citizen interface -> API -> orchestrator -> ingestion -> structure -> extraction
                  -> legal retrieval -> evidence linking -> severity -> report
```

Solid borders are implemented in the current backend. Dashed borders are designed but
not built. The report is returned through the API; that return edge is omitted so the
diagram stays acyclic and readable.

The evidence layer is shown separately because it is the next milestone and because the
system must not imply legal conclusions before it exists.

## Reading the UML diagram

- Domain composition uses filled diamonds: a document contains blocks, a report
  describes metadata, reports observations, and each observation is supported by one or
  more source spans.
- Service dependencies use dotted arrows.
- Classes carry `implemented` or `planned` stereotypes.
- `AnalysisService` is the composition point. It depends on ingestion, extraction,
  severity and storage, and later on retrieval and linking.

## Regenerating the images

Requires Node.js and the Mermaid CLI. The CLI downloads a headless Chromium through
Puppeteer; no interactive browser is used.

```bash
npm install -g @mermaid-js/mermaid-cli

cd docs/diagrams

mmdc -i architecture.mmd -o architecture.png -c mermaid-config.json -b white -s 3
mmdc -i architecture.mmd -o architecture.svg -c mermaid-config.json -b white

mmdc -i uml-model.mmd -o uml-model.png -c mermaid-config.json -b white -s 3
mmdc -i uml-model.mmd -o uml-model.svg -c mermaid-config.json -b white
```

`mermaid-config.json` holds the shared palette and typography so both diagrams stay
consistent. Scale 3 keeps labels crisp in print and on slides. SVG is provided for
vector use and manual editing.

## Notes on layout

Mermaid chooses node placement automatically. The architecture source uses a
left-to-right flowchart with clusters because attempts at a two-row layout were ignored
by the renderer when edges crossed cluster boundaries. The resulting banner is wide by
design and is intended to be placed across a page or slide at full width.
