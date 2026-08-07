# Wisp Action Platform Plan

This document is the source of truth for Wisp's app-aware action work. Update
the status table and decision log as the implementation changes. Code reviews
for action work should reference this plan rather than creating a parallel
architecture in prompts, UI code, or individual integrations.

The implementation handoff for the accessibility/ghost-cursor/keyboard fallback
is in `docs/ACTION_INTERACTION_DRIVER_HANDOFF.md`. That document is subordinate
to this plan and must preserve the safety and preview contract below.

## Product Contract

The General caller (`Ctrl+Q` by default, or `Ctrl+1` in the alternate local
mapping) should understand the active app and propose actions. Rewrite & Paste
(`Ctrl+Shift+Q` by default, or `Ctrl+2` in that mapping) remains a separate,
selection-focused workflow and does not show provider actions. Wisp must show a
preview before changing another app.

The model proposes a versioned, typed `ActionPlan`. Only a registered adapter
may validate and execute its operations. The model never directly emits mouse
coordinates, arbitrary scripts, VBA, PowerShell, or raw API calls for normal
app actions.

Context gathering starts while the overlay is visible and runs concurrently.
Submitting a request must not wait for optional context. If no useful result is
visible after three seconds, Wisp shows a non-blocking progress notice and
continues streaming the plan or result.

## Stable Architecture

1. Detect the foreground app and exact target.
2. Ask its adapter for a bounded, read-only snapshot and available capabilities.
3. Convert the request into a typed `ActionPlan` using only registered actions.
4. Validate schemas, permissions, target freshness, and app preconditions.
5. Render the validated plan as an app-specific HTML/CSS preview.
6. Execute only after the required confirmation.
7. Verify the actual result, record the journal, and offer rollback where the
   adapter can perform it safely.

The preview and executor consume the same `ActionPlan`; preview text must not be
generated separately from the operations that will run.

## Adapter Contract

Every adapter owns its app-specific integration and implements these concepts:

- `detect`: determine whether the supported app is available.
- `capabilities`: report registered, versioned action types.
- `snapshot`: capture a bounded view of the exact target without mutation.
- `validate`: check plan schemas, target identity/freshness, and preconditions.
- `render_preview`: render the validated plan and snapshot.
- `execute`: use the app's supported API, with an idempotency key.
- `verify`: confirm postconditions using the app's actual state.
- `rollback`: reverse journalled changes when the operation supports safe undo.

Use the application's own APIs wherever possible. Accessibility/UI automation
is a fallback for unsupported apps, not the primary implementation strategy.

## Current Progress Snapshot (2026-08-03)

### Functional now: app-context-first picker and forced planning tools

The General caller now detects a supported Browser, VS Code-family editor, or
LibreOffice Calc window from the hotkey-time context snapshot before it builds
the intent overlay. The picker prepends provider-owned actions while preserving
the caller's configured rows, add-on rows, and Custom Prompt. Provider action
rows carry a server-revalidated capability ID and a separate model-safe planning
function name; the UI payload is never trusted as execution authority.

The bottom context preview identifies sources by application and document (for
example, `VS Code: demo.py`) rather than generic `App 1` numbering. When a
readable saved VS Code file and a noisy whole-window UI Automation capture have
the same document identity, Wisp keeps the file source and suppresses the noisy
duplicate. A newer VS Code backup replaces the saved block instead of appearing
as a second copy.

Selecting an explicit provider action forces that exact planning function. A
custom prompt, or a configured rewrite preset in a supported app, first forces a
typed `answer | action | clarification | unsupported` disposition. Only a
validated `action` disposition may enter the provider's exact planner. General
informational presets use answer mode and do not mutate the app.

The shared `brain.action.plan` boundary supports OpenAI-compatible, Anthropic,
and ChatGPT Responses routes. It validates a closed JSON schema, forces the
exact function/tool choice, returns validated arguments, and has no executor
access. Wisp still owns preview, approval, target revalidation, API execution,
verification, and rollback. Browser, VS Code, and Calc now use their named
planning tools instead of asking the rewrite route for prose or JSON to
reinterpret.

This completes context-first intent selection and the forced planning boundary.
The shared `ActionRunner` now implements the invariant detect, snapshot,
capabilities, forced typed plan, validation, preview, approval, revalidation,
execute, verify, and rollback sequence. PowerPoint desktop is its first live
provider. Browser, VS Code, and Calc retain their established production flows
and still need migration into the runner; no new app should add another copied
`FlowController` sequence.

### Provider coverage added in the multi-app pass

| Surface | Picker behavior | Implementation and verification | Shipping status |
| --- | --- | --- | --- |
| PowerPoint desktop | Three usable actions: create slide, restyle selected slide, speaker notes | Actual shared runner plus PowerPoint COM object model; disposable no-window acceptance passed exact preview, create, readback, progress stages, and unchanged foreground | Live Windows route verified |
| PowerPoint web | Create/restyle options are visible but disabled with a connection explanation | Typed Office.js bridge protocol, snapshots, previews, validation, verification, and rollback contracts; fake-client tests | Not usable until Wisp's authenticated Office.js bridge exists |
| Google Slides | Create/restyle/notes options are visible but disabled | Typed Google Slides REST protocol and fake-client tests | Not usable until Google OAuth/client wiring exists |
| Gmail and Outlook mail | Draft and label/category options are visible but disabled; Outlook also shows disabled-rule creation | API-only typed plans, bounded snapshots, exact previews, revision revalidation, verification, rollback, and fake-client tests | Not usable until account OAuth/client wiring exists |
| Google and Outlook Calendar | Create/reschedule options are visible but disabled | API-only typed plans, etag/revision checks, previews, verification, rollback, and fake-client tests | Not usable until account OAuth/client wiring exists |
| Google Sheets | Title or canonical URL detection shows table cleanup and whole-row sort options, disabled | Shared advanced spreadsheet schemas/executor contract and picker acceptance | Not usable until Google Sheets API/OAuth executor exists |
| Excel desktop | No production picker action yet | Real hidden `DispatchEx` acceptance created and verified `WispTable` plus a six-value `WispChart`, preserved source cells, and kept focus unchanged | Object-model adapter verified; picker/shared-runner route and complete rollback remain |
| LibreOffice Calc | Existing usable chart, table cleanup, sort, and analysis options | Existing managed UNO execution plus new advanced formula/filter/deduplicate/conditional-format/pivot contracts | Current narrow actions live; advanced actions remain bridge contracts |
| VS Code | Existing usable fix/refactor options | Existing saved/Untitled route plus new format, test-file, registered-task, and LSP-rename contracts | Current narrow actions live; advanced extension routes and automatic bridge loading remain |

Unavailable rows deliberately remain visible and muted so app detection is
obvious without pretending the action can run. They cannot be selected, and the
supervisor rejects a forged attempt to route one. Once a concrete authenticated
client or owned app bridge is present, its row can become usable without changing
the typed plan or preview contract.

Gmail filters have no disabled state in the Gmail API, so Wisp refuses that
specific action rather than creating an enabled rule. Outlook message rules do
support an explicit disabled state. PowerPoint web speaker-note mutation is also
withheld because the documented Office.js surface does not expose it.

Verification for this pass:

- 331 focused action, picker, adapter, and supervisor tests passed.
- Ruff passed across `core/actions`, the intent overlay, the supervisor flow,
  and the new focused tests.
- The catalogue contains 195 pytest files with 2,966 collected nodes plus three
  manual diagnostic files; no files are unclassified or unscheduled.
- The monolithic repository command exceeds a practical bounded run on this
  Windows host, so all 195 pytest files were executed in isolated batches. The
  final bounded result is 2,860 passed and 106 skipped, plus 146 passing
  subtests. The stale F192/F193 acceptance claim uncovered by the first run was
  corrected instead of being dismissed as unrelated.

Additional real-application acceptance and fixes:

- PowerPoint desktop ran through the actual shared `ActionRunner`, runtime
  provider, and COM client. The previewed slide was created and read back; all
  public progress stages were emitted and the foreground HWND stayed unchanged.
- Excel desktop ran in a separate hidden instance. Real COM behavior exposed
  and fixed both callable-versus-property `Range.Address` handling and a chart
  source bug that produced zero-valued series for mixed text/numeric tables.
  Readback contained the expected six numeric values.
- VS Code's isolated Untitled run used the real model and official Extension API,
  changed document version 1 to 2, verified exact text, and did not activate the
  editor. Automatic bridge loading for ordinary sessions remains unfinished.
- Gmail, Outlook mail, Google Calendar, and Outlook Calendar rendered through
  the production picker. Outlook's current `outlook.cloud.microsoft` and
  established `outlook.office365.com` hosts are now detected. No account
  mutation was attempted because no OAuth configuration, token cache, concrete
  account client, `googleapiclient`, or `msal` exists.
- The picker now paints the detected provider name above its app-owned actions,
  so otherwise identical Google and Outlook Calendar action lists are visibly
  distinguishable.
- Action telemetry is now best-effort: an unwritable timing-log path cannot
  crash an approved application action.

### Functional now: truthful live action progress

Calc and VS Code action routes now publish a shared monotonic progress state to
one replace-in-place bubble line. The public stages identify the real work Wisp
is doing: target read, planning, validation, preview construction, approval,
Apply/verification, and a terminal result. Provider reasoning summaries are not
treated as execution state and private model reasoning is never displayed.

The progress payload is content-free apart from a fixed user-facing status: it
contains the registered action ID, app, stage, sequence, and terminal flag. The
same stage changes are recorded in private action telemetry. Backward stage
movement and updates after a terminal state are refused. If model planning is
still running after four seconds, the same `planning` stage updates with an
explicit heads-up that drafting is continuing and may take a few more seconds.

### Functional now: LibreOffice Calc on Windows

The first bounded action set works end to end for a Wisp-managed LibreOffice
Calc session:

- The General caller detects the exact Calc window before opening the intent overlay,
  but deliberately does not invoke Calc's accessible Copy command while the
  popup is visible. Wisp gathers the selected range, values, and fingerprint
  only after the user chooses a Calc action and the picker closes normally.
- The app-aware picker now offers `Create a bar chart`, `Clean up this table`,
  `Sort this table`, and a non-mutating `Analyze this data` path.
- Mutating requests are forced through registered planning tools and become one
  typed, immutable `calc.add_chart@1`, `calc.format_table@1`, or
  `calc.sort_range@1` plan. The same plan drives the HTML/CSS preview and Apply.
- Apply revalidates the recorded window, range, and fingerprint before changing
  anything.
- The preview fingerprint and Apply fingerprint now both cover UNO's typed
  range values and formulas. UI Automation identifies only the selected address. This avoids
  false "data changed" failures caused by comparing formatted clipboard text
  with typed numeric/date/formula results.
- The action uses LibreOffice's UNO API in the same open document through a
  Wisp-owned, random user-local named pipe persisted in LibreOffice's own
  startup configuration. LibreOffice can therefore be opened before or after
  Wisp once the integration is installed, and the action does not take keyboard
  focus.
- Wisp verifies the requested result and the unchanged foreground window.
  Formatting must preserve values, formulas, and number formats; sorting must
  match the exact previewed whole-row order. Repeated Apply events are idempotent.
- Both new mutations are grouped into one LibreOffice Undo action. Failed
  verification automatically rolls the operation back and checks the restored
  range. Sorting formula-containing rows is refused until formula-reference
  movement has its own verified contract.
- Chart creation never writes the source range. In particular, Wisp does not use
  `setDataArray` to "restore" values, because that would flatten formulas into
  their calculated results.
- Non-chart Calc requests are protected from the ordinary rewrite-and-paste path.

Verification completed:

- The focused Calc, localization, formatted-preview, intent-overlay, and flow
  suite passes all 295 tests.
- The broader runtime regression run passed 445 tests and skipped 2 after fixing
  the `ui.show_chat` message-action handshake and explicit add-on-root isolation.
- The test catalogue is current at 195 pytest files and 2,966 pytest nodes.
- A real hidden-workbook smoke test created `WispChart` from `A1:C7`, verified
  the source fingerprint, and kept the foreground window handle unchanged
  (`592286` before and after).
- The temporary smoke-test workbook was closed after verification.
- A second live acceptance started LibreOffice from the normal user profile
  without `--accept`, connected through the persisted Wisp named pipe, and then
  closed only the two invisible acceptance-test processes.
- A formula-preservation acceptance captured `A1:B3` through UNO, created
  `WispChart`, kept focus unchanged, and verified that `=1+1` and `=2+2`
  remained formulas after chart creation.
- A disposable real-LibreOffice acceptance formatted `A1:C5` without changing
  contents, sorted complete rows by Sales into the previewed order, then used
  the two grouped Undo actions to restore both the original row order and the
  original formatting.

This is deliberately a narrow production-capable slice, not a claim that every
Calc action is complete. Current limitations are:

- Chart creation is still limited to a generic vertical bar chart. Table
  formatting currently provides one restrained preset, and sorting supports
  one exact unique header in ascending or descending order.
- An already-running LibreOffice process cannot load a newly installed startup
  connection into that same process. Existing development profiles therefore
  need one LibreOffice reopen when this integration is first installed. This is
  a one-time update, not a launch-order requirement; subsequent sessions work
  whether Calc or Wisp starts first.
- Execution journals exist, but there is not yet a user-facing journal browser.
- macOS and Linux execution are not implemented or tested yet.
- Formula-writing, totals/subtotals, filters, data cleaning, conditional
  formatting, and arbitrary cell edits are not implemented yet.

### Real adapter acceptance, production route pending: Microsoft Excel

The shared contracts and `pywin32` adapter have now been exercised against a
real, hidden disposable Excel instance. Wisp created a table and chart, read back
the exact six numeric series values, preserved the source cells, kept the
foreground window unchanged, and closed the owned instance. Excel is still not
a shipped General-caller action because provider-picker/shared-runner wiring and
complete rollback remain unfinished.

### Functional saved-file and Untitled slice: VS Code on Windows

The first narrow VS Code action now runs through the General caller's production
intent path rather than through a disconnected file API:

- Wisp recognizes VS Code, VS Code Insiders, Cursor, and Windsurf windows without
  requiring an editor extension.
- The first action accepts one unique selection in the active saved UTF-8 file,
  sends the selected block plus bounded surrounding code to the configured model,
  and asks the model to describe the issue and return the replacement block.
- An empty saved UTF-8 file is also supported as an exact whole-file insertion;
  this lets Wisp create the first contents of a new file without editor focus.
- An Untitled buffer uses the text target captured when the General caller opens. Wisp
  accepts a selected range or a collapsed caret, drafts the exact replacement,
  displays the same sanitized diff preview, and writes only after Apply through
  the existing anchored paste-back boundary.
- The normal three-second slow-response notice is used while the model is still
  working, so the overlay gives the user feedback before a longer action returns.
- The model result becomes a typed `vscode.replace_selection@1` plan and an exact
  HTML/CSS unified-diff preview. Apply and Cancel operate on that same plan.
- Apply rechecks the whole-file fingerprint, selected range, selected-text
  fingerprint, and dirty-tab marker. It then performs an atomic saved-file write,
  reads the result back, and never activates VS Code or sends keyboard input.
- Repeated Apply events are idempotent and the result contains an in-memory undo
  journal entry, although user-facing persistent Undo is not implemented yet.

Verification completed:

- The focused unit and flow suite passes, including stale-file refusal, duplicate
  selection refusal, required confirmation, preview sanitization, and prevention
  of direct paste-back.
- An off-screen acceptance smoke used Wisp's real `FlowController.intent_chosen`
  route and the configured ChatGPT model. The model proposed the fix, Wisp
  rendered the diff, Apply updated the temporary saved file, no paste command
  ran, and the Windows foreground handle stayed `592286` before and after.
- A live user-opened `Untitled-1` test originally reached the real model-generated
  HTML/CSS preview but exposed that the file adapter was the wrong executor for
  an unsaved editor. The route now uses the already-captured editor target
  instead; a fresh live acceptance remains required for that corrected Apply.
- The user then saved the tab as `C:\Users\sunny\Desktop\test wisp vs code.txt`.
  Wisp resolved the exact live window and Desktop path, ran the configured model,
  displayed the interactive preview, rechecked the empty-file fingerprint on
  Apply, atomically wrote the reviewed code, and read the exact result back.

This is not yet a full VS Code integration. Current limitations are:

- The user must select one unique code block. Whole-file diagnosis, multiple
  files, new files, workspace edits, tests, tasks, and terminal commands are not
  implemented yet.
- Dirty saved tabs, non-UTF-8 files, files over 200 KB, and saved-file selections
  over 8,000 characters are refused instead of being changed unsafely.
- The saved-file mechanism is portable, but live window/path detection has only
  been exercised on Windows so far.

### Functional managed-Chrome form slice on Windows

Chrome is the next completed application slice through the production
General-caller intent route:

- Wisp recognizes explicit form-fill requests in Chrome/Edge/Brave/Chromium.
- A Wisp-managed Chromium DevTools endpoint snapshots visible editable text,
  textarea, email, date, number, and select fields. Password, hidden, file,
  checkbox, radio, disabled, and read-only controls are excluded.
- The configured model receives bounded field IDs and metadata, then returns a
  typed `browser.fill_form` assignment list. It cannot invent selectors, click,
  navigate, or submit through this capability.
- Wisp validates every field and select option, renders a sanitized HTML table
  of current and proposed values, and waits for Apply.
- Apply reconnects to the same tab, rechecks the full form fingerprint and each
  expected value, uses Chrome's DevTools API to set only reviewed fields,
  dispatches normal input/change events, verifies exact values, and rolls back
  already-changed fields if any later field fails.
- Browser action stages, the four-second heads-up, preview chrome, errors, and
  completion text are included in the Traditional Chinese localization surface.

Verification completed on a separate hidden Windows desktop with the installed
Chrome and the real configured Wisp model. The model produced three assignments,
the preview contained all reviewed values, Apply filled name/email/country in
239 ms, postcondition reads matched all three values, and the form's independent
submit counter remained zero. A DevTools screenshot visually confirmed the
filled page. Eight temporary Chrome processes owned by the isolated profile were
cleaned up; the user's visible desktop, cursor, keyboard, and normal Chrome
profile were never used.

Current limitation: the API is available only to Chrome sessions launched or
adopted with Wisp's private DevTools endpoint. Automatic managed-session launch
and adoption UX must be shipped before this works in an arbitrary already-open
Chrome window. Button clicks, navigation, downloads, uploads, payments, password
fields, and form submission remain intentionally unsupported. Production
discovery requires a per-session Wisp marker so it cannot adopt an unrelated
debug browser. Before general shipping, replace the random localhost DevTools
port with an inherited DevTools pipe (or an equivalently authenticated channel)
to prevent another same-user local process from racing the endpoint.

### Next implementation order

1. Migrate Chrome, VS Code, and Calc onto the shared `ActionRunner` without
   changing their proven execution transports.
2. Add Wisp-owned Google and Microsoft account OAuth/token storage, concrete
   Gmail/Calendar and Microsoft Graph clients, and real disposable-account
   acceptance. Never implement account rules as browser clicks.
3. Ship the PowerPoint Office.js bridge and Google Slides REST client, then run
   real web-app acceptance for the currently disabled picker actions.
4. Wire the accepted Excel adapter into the picker/shared runner, complete its
   rollback, and implement Google Sheets through its account API.
5. Add the owned VS Code extension routes for format, test-file generation,
   registered tasks, and LSP rename, plus automatic bridge loading.
6. Persist action journals and expose safe Undo for every shipped provider.
7. Replace Chrome's localhost DevTools endpoint with an inherited pipe or
   equivalently authenticated channel and ship automatic session adoption.
8. Test the supported transports on macOS and Linux where corresponding app
   APIs exist.

## Delivery Order

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Shared contracts, action registry, validation boundary | Complete for the first Calc slice |
| 2 | Excel: inspect active selection | Real hidden-instance adapter acceptance complete; production picker/shared-runner route pending |
| 3 | LibreOffice Calc: real UNO table/chart smoke test | Live smoke complete |
| 4 | Capture Calc selection after a Calc action is chosen through its recorded window | Complete on Windows |
| 5 | Add Calc action planning, HTML preview, and Apply to the General caller | Complete for one column-chart action in Wisp-managed Windows Calc sessions |
| 6 | Calc table formatting, chart options, journals, and safe Undo | Next |
| 7 | VS Code-family saved-file context, model fix, diff preview, safe Apply | First saved-file slice live and complete on Windows |
| 8 | Managed Chrome: model-planned form fill, HTML preview, safe Apply | Live isolated smoke complete on Windows |
| 9 | Outlook/Gmail APIs: drafts, categories, disabled rules, rule preview | Typed API foundation complete; OAuth/live clients pending |
| 10 | Calendar APIs: create and reschedule with notification policy | Typed API foundation complete; OAuth/live clients pending |
| 11 | PowerPoint desktop/web and Google Slides | Desktop COM smoke and shared-runner route complete; web bridges pending |
| 12 | Advanced Excel/Sheets/Calc and VS Code actions | Typed foundations complete; app bridge executors pending |
| 13 | Public action-provider/add-on contract | Planned |
| 14 | Restricted accessibility fallback, ghost cursor, and user-yielding input lease | Design handoff complete; implementation not started |

Finish and test one vertical slice before broadening the capability list.

## Microsoft Excel Vertical Slice (Adapter Accepted, Not Yet Shipped)

Target journey:

> Select a range in Excel -> open the General caller -> ask "make this a table and
> add a chart" -> inspect the real selection -> preview the exact table/chart
> operations -> Apply -> verify the created objects.

Excel exposes the active workbook, active worksheet, selection, ranges,
`ListObjects` (tables), and `ChartObjects`. Wisp should orchestrate these Excel
objects through `pywin32`; Excel remains responsible for spreadsheet behavior.

Initial registered actions:

- `excel.create_table@1`
- `excel.add_chart@1`

The first implementation is Windows-only and uses the active desktop Excel
instance. Office Scripts and Microsoft Graph are later executors behind the same
typed action names, not separate planner contracts.

## Safety Rules

- Snapshot reads are bounded; never serialize an entire workbook by default.
- Plans include workbook, worksheet, selection, and snapshot fingerprint.
- Re-check target identity and fingerprint immediately before execution.
- Require confirmation for every mutation in the first release.
- Use idempotency keys so repeated Apply events cannot duplicate an action.
- Never silently switch to a different workbook, worksheet, or range.
- Never activate, focus, or send keyboard input to an app as a side effect of
  a background action. Refuse the action if the selected transport cannot keep
  the user's foreground window unchanged.
- Mark rollback support honestly per operation; do not claim full Excel Undo
  until before-state restoration has been verified in real Excel.
- Do not run formulas, macros, external links, or arbitrary code from model text.

## Definition of Done for an Action

Every registered action must have:

- A versioned action ID and JSON-compatible input schema.
- A declared risk level and confirmation policy.
- Supported app/platform information.
- Bounded required context.
- Deterministic validation and preview.
- An executor using a documented app API.
- Postcondition verification.
- Explicit rollback capability or limitation.
- Contract tests and adapter tests using fakes.
- A real-app smoke test before production status.
- Timing events for detection, snapshot, planning, preview, Apply, and verify.
- Timing telemetry is private and content-free: it is written to rotating JSONL
  diagnostics, never rendered in the overlay. Records include stage timestamps,
  durations, outcome/error types, operation counts, and character counts, but
  never prompts, selected text, generated content, secrets, or full file paths.

## Decision Log

- 2026-08-01: Start with Excel because its native object model supplies the
  operations and the table/chart journey exercises the complete action pipeline.
- 2026-08-01: Keep action contracts in `core/actions`; do not embed them in the
  existing rewrite model call or Qt preview widgets.
- 2026-08-01: Use direct Excel object-model calls rather than UI automation.
- 2026-08-01: Treat add-on contribution as a later public boundary. Prove the
  core contract with the built-in Excel adapter first.
- 2026-08-01: The user's installed spreadsheet is LibreOffice Calc. Keep the
  shared Excel prototype, but prioritize a production Calc adapter using UNO.
- 2026-08-01: The first real Calc chart smoke exposed a corner-header mutation
  by the legacy chart bridge. Preserve the previewed source range, verify it
  after chart creation, and roll back the chart if source cells differ.
- 2026-08-01: A normal running LibreOffice instance cannot be given a new UNO
  listener after startup. Wisp reads the recorded Calc selection off-screen
  through the window's UI Automation name box and accessible Copy command,
  under the shared clipboard lock; mutation still requires the private action
  connection.
- 2026-08-03: Do not run that accessible Copy read while the intent picker is
  visible. On Windows the invocation can disturb popup focus and dismiss the
  picker, including when Copy returns no text. Detect Calc before showing the
  picker, defer the range read until a Calc action is chosen, and never attempt
  ordinary UIA text-focus capture for a structured Calc cell target.
- 2026-08-01: Calc's accessible Chart command creates the requested chart but
  activates Calc and its Chart Wizard even when the window is off-screen and
  marked `WS_EX_NOACTIVATE`. It is not a production action transport. Wisp may
  keep using UI Automation for bounded context capture, but chart mutation must
  use LibreOffice's built-in UNO API.
- 2026-08-01: The first safe Calc executor connects only to a Wisp-managed UNO
  session, revalidates the exact range fingerprint, creates and verifies the
  chart, verifies source cells, and rolls back if foreground focus changes.
- 2026-08-03: LibreOffice's persistent `ooSetupConnectionURL` was validated in a
  normally launched Windows process with no `--accept` command-line argument.
  Wisp now provisions a random named-pipe endpoint once and waits through slow
  LibreOffice startup with a truthful four-second progress update. This removes
  the recurring Wisp-before-Calc launch-order restriction. Only a LibreOffice
  process that was already running when the integration was first installed
  needs one reopen, because a process cannot reload startup configuration.
- 2026-08-03: Do not compare the UIA/clipboard display-text fingerprint from
  preview with UNO's typed-value fingerprint at Apply; identical sheets can
  legitimately encode those values differently. Snapshot and revalidate with
  the same UNO normalization on both sides. The UIA path now contributes only
  the selected address. Also never rewrite the source range after chart
  creation: verification is read-only and rollback removes only the chart.
- 2026-08-01: The focusless executor passed a real hidden-workbook smoke test:
  it created `WispChart` from `A1:C7`, verified the chart and source fingerprint,
  and left the Windows foreground handle unchanged.
- 2026-08-01: VS Code support must not require users to install an extension.
  The first executor uses the editor's saved file as the stable app boundary,
  with OS window/path detection for context and exact fingerprint checks for
  mutation. An optional future editor integration may add richer diagnostics,
  but it cannot be a prerequisite for the core action.
- 2026-08-01: The first VS Code off-screen Wisp/model smoke completed the real
  intent -> model -> HTML diff preview -> confirmed Apply route, changed only the
  controlled saved file, made no direct paste call, and preserved foreground
  focus. A live visible VS Code acceptance test remains required before calling
  the app integration production-complete.
- 2026-08-01: A live empty untitled-tab test reached the real model-generated
  HTML diff preview. Apply was then refused and rolled back because Monaco's
  Windows Accessibility ValuePattern forcibly activated VS Code's Electron
  window, even for an empty-to-empty diagnostic write, and Windows would not
  restore the prior foreground window. That experiment established that the
  saved-file adapter cannot own an unsaved buffer; it did not invalidate Wisp's
  separately captured editor paste-back target.
- 2026-08-01: The follow-up live saved-file acceptance succeeded on the user's
  Desktop file. Wisp fixed a basename-only VS Code path-resolution gap by using
  one unambiguous exact match in standard user folders, then completed the real
  model -> preview -> confirmed Apply -> disk readback path. VS Code never became
  the foreground window during Apply.
- 2026-08-01: Action latency becomes structured private telemetry rather than a
  visible timer. The VS Code trace begins at hotkey/summon, preserves initial
  capture and overlay/context milestones, records model request/first activity/
  completion, exact preview-presented and decision timestamps, native Apply
  validation/write/readback timings, and every terminal outcome. Records rotate
  under Wisp's user-data logs and exclude user content and full paths.
- 2026-08-01: The first completed private live trace measured 28.477 seconds.
  It initially mislabeled 17.033 seconds after `dialog.show()` as user approval
  time, even though Windows kept the dialog behind another window until the test
  harness raised it. `dialog.show()` is now recorded honestly as a show request,
  and Windows previews are placed topmost without activating VS Code. The model
  worker used 9.438 seconds, model IPC/routing added about 0.355 seconds, and the
  UI worker called show 1.223 seconds after a 41 ms plan/render step. Confirmed
  Apply took 20.246 ms in the
  native worker, including 18.009 ms atomic write and 0.673 ms readback verify.
  Context snapshot work was 0.691 ms. Optimize model time and preview-window
  presentation first; context capture and Apply are not current bottlenecks.
- 2026-08-01: The slow rewrite used the ChatGPT OAuth route with `gpt-5.5`,
  inherited the global `high` chat reasoning effort, and called the Responses
  endpoint non-streaming. The action route now uses direct Responses streaming,
  bounded `none` reasoning for the simple rewrite action. Provider-generated reasoning
  summaries and explicit progress may stream as thought/progress UI; private
  chain-of-thought and partial function-call JSON are never shown.
- 2026-08-01: The first corrected streaming/topmost trace measured 11.513 seconds
  total with a genuine 2.240-second approval interval. Model work fell to 6.014
  seconds but the ChatGPT OAuth endpoint emitted no reasoning-summary events for
  that forced tool call. Wisp now emits an immediate truthful local action-stage
  message while waiting, keeps support for provider summaries when available,
  and uses the fastest action reasoning supported by the configured model. It does not fabricate or expose private
  chain-of-thought.
- 2026-08-01: Live validation proved `gpt-5.5` rejects `minimal`; its supported
  values are `none`, `low`, `medium`, `high`, and `xhigh`. Simple rewrite actions
  now request `none`, and the streaming route drops an unsupported reasoning
  block and retries instead of failing the entire action.
- 2026-08-01: With `reasoning.effort=none`, truthful local progress appeared at
  0.241 seconds and the model completed in 5.646 seconds; the preview was raised
  topmost at 7.693 seconds and Apply finished at 9.245 seconds including a real
  1.473-second approval interval. A second request on the same warm brain process
  took 6.327 seconds in the model, so client/model warm-up is not the material
  bottleneck. The ChatGPT OAuth `gpt-5.5` forced-tool route emitted no reasoning
  summary deltas in either run. Keep the immediate stage message and direct
  streaming, but do not describe local progress as model thought.
- 2026-08-01: Action progress is now a shared monotonic state machine rendered
  through one replaceable bubble line. Calc and VS Code publish exact public
  stages from target read through preview, Apply, verification, and terminal
  status. Provider summaries cannot overwrite or impersonate execution state.
- 2026-08-01: A real controlled VS Code action showed its first progress at
  142 ms, completed model drafting at 10.036 seconds, displayed the preview,
  applied the reviewed replacement, and verified the saved file in about 17 ms.
  The run exposed a static planning interval, so planning now emits a truthful
  four-second heads-up while retaining the same stage instead of inventing new
  model activity.
- 2026-08-01: The computer-interaction fallback is specified separately in
  `ACTION_INTERACTION_DRIVER_HANDOFF.md`: semantic accessibility operations and
  a non-interactive purple ghost cursor come before physical input. Real input
  requires a short lease that pauses immediately when the user touches the
  mouse or keyboard. No per-app extension and no model-generated coordinates.
- 2026-08-01: Action localization is owned by one UI-side boundary across app
  adapters, rather than by VS Code or any individual executor. Traditional
  Chinese now covers Calc, Excel, VS Code, and the semantic interaction
  lifecycle: live stages, the four-second heads-up, preview chrome, warnings,
  Apply/Cancel, cancellation, failures, and verified completion. Dynamic file
  names, model summaries, cell values, ranges, and code remain byte-for-byte
  user content. Excel's legacy preview was also moved onto the host's sanitized
  HTML presentation contract so it can use the same localized review surface.
- 2026-08-01: Untitled VS Code tabs now use the target Wisp captures before the
  intent overlay takes focus. Windows retains collapsed UI Automation caret
  ranges as well as selected ranges; macOS retains its focused AX element. Wisp
  drafts and previews first, then Apply calls the existing anchored paste-back
  operation. A stale or missing token fails closed instead of falling back to
  the current caret. Dirty saved files still require Save because their disk
  content and live editor content disagree. Microsoft Excel work is deferred.
- 2026-08-01: The original Windows anchored paste still activated VS Code while
  selecting Monaco and issuing Ctrl+V, so it is not an acceptable non-interfering
  Untitled executor. A real smoke test on a separate hidden Windows desktop sent
  simulated `WM_CHAR` input first to Electron's top-level window and then to its
  `Chrome_RenderWidgetHostHWND`; both preserved foreground focus, but Chromium
  discarded the messages and Monaco remained unchanged. A target-addressed
  background mouse click inside the renderer followed by the same keyboard
  messages was also accepted by Windows but discarded before reaching Monaco.
  Windows queue success
  is therefore never treated as action success: Wisp verifies the resulting
  accessible document and fails closed, with no focus-stealing fallback. The
  next viable Untitled investigation is a focusless application channel such as
  a Wisp-managed Chromium DevTools input session; ordinary SendInput cannot be
  both target-specific and non-interfering.
- 2026-08-01: Chromium DevTools input was proven only while the isolated VS Code
  page retained session focus. In the complete Wisp/model flow, both DevTools
  `Input.insertText` and a synthetic Monaco textarea input event were ignored;
  this is not a reliable background editor API and is not the production route.
- 2026-08-01: The supported VS Code Extension API bridge passed the complete
  isolated smoke: real Wisp model -> sanitized HTML diff preview -> approval ->
  `vscode.window.activeTextEditor.edit()` -> Extension Host document readback ->
  independent Monaco rendering check. It edited an actual Untitled buffer,
  advanced its document version from 1 to 2, and never used the visible desktop,
  physical cursor, keyboard, or saved-file mutation. Wisp owns and authenticates
  this small local bridge; the user is not asked to find or manually install an
  extension. Shipping still requires automatic bridge loading for Wisp-managed
  VS Code sessions and captured document-version/selection validation before
  Apply to protect against user edits made while the preview is open.
- 2026-08-03: Managed Chrome became the next real application slice. On a
  separate hidden desktop, the installed Chrome exposed three safe form fields
  through a private DevTools endpoint; the real Wisp model mapped the request to
  exact field IDs, Wisp rendered and auto-approved the normal preview in the
  smoke harness, Apply filled and verified all three values in 239 ms, and an
  independent page counter proved no submission occurred. The production flow
  excludes password/file/toggle controls and has no click or navigation action.
  Traditional Chinese coverage was extended to the full browser lifecycle and
  preview. Existing arbitrary Chrome windows remain unsupported until managed
  launch/adoption is connected to product startup.
