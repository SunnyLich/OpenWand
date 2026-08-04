# Wisp Shared Workspace capability report

Last verified: 2026-08-03

## Real configured-provider verification

The complete seven-file smoke task was run against the configured ChatGPT
`gpt-5.5` route, not a scripted model callback. The model produced seven scoped
file calls; all seven succeeded and none failed. The production Shared
Workspace window displayed the seven files, kept Workspace visible beside the
Activity panel, and rendered `preview.md`. A second production-path pass opened
every artifact and observed the expected modes: Markdown, HTML, CSV, SVG image,
PDF, Python text, and JSON text. Automatic Python and JSON checks both passed.

Evidence is preserved under
`outputs/real-provider-workspace-smoke/20260803-170355/`, including the agent
run, exact files, structured results, preview verification, and a production
window capture.

The provider took about 101 seconds to emit its first token and 143 seconds to
finish the seven-file response. Wisp records waiting and streaming progress in
Activity, but file writes cannot become visible until their complete JSON tool
calls arrive from the provider.

## Working and tested

| Capability | Result | Notes |
|---|---|---|
| Plain text and source code | Working | Editable shared view with optimistic saving, persistent changed-line colors, and the `Wisp agent` collaborative caret during writes. |
| Markdown | Working | Raw Markdown is editable; Preview renders it natively without changing the file. |
| HTML | Working with intentional limits | Rendered by a non-scriptable native Qt document view. Links, navigation, scripts, local-file resources, and network resources are blocked. |
| CSV and TSV | Working | Rendered as bounded tables rather than raw comma/tab text. |
| Images | Working | In-memory preview for formats supported by the installed Qt image codecs, including the tested PNG path. |
| PDF | Working | Rendered in memory by QtPdf; no external PDF application opens. |
| Unsupported binary files | Working fallback | Shows a readable unsupported-preview message instead of mojibake or a blank screen. |
| Python syntax check | Working | Compiles syntax only; the source file is not executed. |
| JavaScript syntax check | Working when Node.js is installed | Uses the fixed `node --check` operation; it does not run the script. |
| JSON validation | Working | Parses JSON with a fixed helper; no user-supplied command is accepted. |
| Activity history | Working | Permanent resizable side panel with compact clickable cards and hidden full details. Privacy cards show safe category/source/reason metadata without storing secret values. |
| Shared file explorer | Working | Nested folders preserve navigation state; agent-created paths are blue, edited paths orange, and deleted tombstones red. |
| Focus isolation | Working | Previewing and checking files does not use the physical cursor, keyboard, terminal window, or another application. |

## Security boundaries

- The preview bridge binds only to authenticated `127.0.0.1` and never returns
  host paths through its state or preview endpoints.
- Preview reads reject traversal, folders, symlinks in every path component,
  file swaps, oversized files, and paths outside the session.
- Preview files are capped at 12 MiB.
- Background checks accept typed relative file paths only. They reject arbitrary
  command strings, argument arrays, wrong extensions, symlinks, oversized input,
  excessive output, and long-running processes.
- Checker processes receive no terminal window or stdin and support timeout and
  cancellation.

## Not implemented because it would be misleading or unsafe

- Arbitrary execution of model-generated programs.
- A general shell or terminal inside Shared Workspace.
- Host/network isolation for untrusted processes without a VM, container, or
  comparable operating-system sandbox.
- Controlling Word, Excel, Photoshop, VS Code, or other real desktop apps from
  this window.
- JavaScript-powered webpages or webpages that fetch external resources.
- Character-level simultaneous merging. User saves are revision-checked; a
  concurrent Wisp change preserves the user's unsaved editor text and rejects
  a stale overwrite.
- Editing spreadsheets, PDFs, or images as native structured documents. They
  can currently be previewed, while their source files are created or replaced
  through scoped file tools.

## Test coverage

Automated tests exercise all preview modes, authenticated binary delivery,
preview size and path restrictions, syntax/data checking, cancellation and
timeouts, no-window process behavior, the production Shared Workspace window,
the expandable Activity panel, shared editing/conflicts, file/line change
colors, privacy details, and automatic check results. Windows symlink-specific tests
are skipped when the current Windows account lacks permission to create test
symlinks; the non-symlink traversal and containment tests still run.
