# Shared Workspace (Experimental)

An optional OpenWand addon for visible, focus-free background work. When the
model starts or changes files in its isolated session, OpenWand automatically
opens the native workspace window. It never moves the user's physical mouse,
types into the user's applications, or opens a browser.

The primary window contains:

- a nested shared-file explorer with blue agent-created, orange agent-edited,
  and red agent-deleted paths;
- a raw editable text surface with optimistic conflict-safe saving, persistent
  line-change colors, and an optional rich Preview mode;
- a permanent resizable **Activity** panel whose compact cards expand on click
  to reveal details, including secret-free privacy-redaction categories;
- a task composer scoped to the current session;
- cooperative pause, resume, and stop controls; and
- a compact mouse indicator only for actual virtual mouse actions, plus a
  Google Docs-style `OpenWand agent` caret for text edits.

Native previews currently support plain text and code, rendered Markdown,
network-isolated non-scriptable HTML, CSV/TSV tables, Qt-supported images, and
PDF documents. Binary preview payloads travel only over the token-authenticated
IPv4 loopback bridge and are capped at 12 MiB.

Python, JavaScript, and JSON files can be checked automatically without opening
a terminal. These are fixed syntax/data checks, not arbitrary commands. See
[`CAPABILITY_REPORT.md`](CAPABILITY_REPORT.md) for the tested matrix and exact
security limitations.

Session files remain under OpenWand's per-addon data directory after the session
stops so the user can audit them.

This is cooperative file editing, not character-level CRDT merging. If OpenWand
changes a file while the user has unsaved text, the editor preserves the user's
text and rejects a stale save instead of silently overwriting either version.
