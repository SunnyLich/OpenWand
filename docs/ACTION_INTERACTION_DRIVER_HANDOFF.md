# OpenWand Interaction Driver Handoff

Status: design handoff; implementation has not started.

Owner: the next engineer or agent implementing OpenWand's semantic cursor/keyboard
fallback. The canonical product and safety rules remain in
`docs/ACTION_PLATFORM_PLAN.md`; this document is the build brief for one feature.

## Mission

Give a confirmed OpenWand `ActionPlan` a way to operate apps that do not expose a
usable file or native API, while the user can keep working. The interaction
driver is a fallback executor, not a replacement for Calc UNO, Excel's object
model, saved-file edits, Graph, or other supported app APIs.

OpenWand must show what it is doing through exact public progress stages and a
purple ghost cursor. It must not pretend to show private model reasoning. It
must never silently fight the user's real mouse or keyboard.

## Non-negotiable product rules

- Do not require an extension in every target app.
- Prefer, in order: app/file API, accessibility semantics, supported background
  window operation, and finally real mouse/keyboard injection.
- The model emits semantic, registered operations. It never emits arbitrary
  screen coordinates, key streams, shell commands, or accessibility scripts.
- Show the complete action preview before the first mutation.
- Re-resolve and revalidate the target before every operation. Stop if the app,
  window, element, or expected value changed.
- Semantic actions should not move the physical cursor or take focus. Animate a
  separate purple ghost cursor over the resolved target instead.
- Real input requires a short-lived interaction lease. Any physical user input
  pauses OpenWand immediately and releases the lease; OpenWand resumes only after the
  target is revalidated and the user explicitly allows it.
- Escape/Cancel stops queued operations. Every operation declares whether it is
  reversible; never promise rollback where it cannot be verified.
- Start truthful progress immediately. If no preview or useful action is ready
  by four seconds, keep the exact current stage visible and plainly say OpenWand is
  still working.

## Architecture to implement

Create a platform-neutral package under `core/actions/interaction/`:

- `contracts.py`: typed locators, semantic operations, preconditions,
  postconditions, results, and versioned schemas.
- `session.py`: execution state, current operation, cancellation, pause/resume,
  revalidation, journal, and idempotency.
- `driver.py`: chooses the best available transport for each registered
  operation and refuses unsupported or unsafe fallbacks.
- `arbiter.py`: owns the interaction lease and distinguishes physical input from
  OpenWand-tagged injected input.

Add native backends behind one interface:

- Windows: UI Automation.
- macOS: Accessibility API (`AXUIElement`).
- Linux: AT-SPI.

Do not make Windows `SendMessage` or coordinate clicking the shared contract;
those are optional platform executors with explicit capability flags.

The first semantic operation set should be deliberately small:

- `interaction.inspect@1`: bounded read-only element tree.
- `interaction.invoke@1`: invoke a button/menu item through its semantic action.
- `interaction.set_value@1`: set a text/value control when the accessibility API
  explicitly supports it.
- `interaction.toggle@1`: set a checkbox/toggle to an exact state.
- `interaction.select@1`: select an exact list/tab/menu item.
- `interaction.scroll@1`: scroll one resolved container by a bounded amount.

Every locator must use stable semantic evidence where available: app identity,
window identity, role/control type, automation identifier, accessible name,
ancestor path, and a snapshot fingerprint. Bounds are a verification hint, not
the model's primary locator.

## Visible behavior

Use the existing `ActionProgress` state machine and `ui.action.progress` path.
The bubble owns one replaceable line; it is not a growing activity log. Expected
stages are:

1. `targeting`: identifying the recorded app/window.
2. `reading`: inspecting the bounded accessibility tree.
3. `planning`: resolving registered semantic operations.
4. `validating`: checking target identity, permissions, and preconditions.
5. `preparing_preview`: rendering the exact operations.
6. `awaiting_approval`: no mutation has occurred.
7. `applying`: executing the confirmed operation currently named in the UI.
8. `verifying`: reading the actual postcondition.
9. terminal `complete`, `cancelled`, or `failed`.

The ghost cursor is a click-through, always-on-top transparent overlay owned by
OpenWand. It follows resolved element bounds, shows an invoke/click pulse, and can
display a compact operation label. It never moves the OS cursor. Hide it when
the target is stale, the user interrupts, the action pauses, or the action ends.

For actual input fallback, the progress line must say that OpenWand needs brief
control before acquiring the lease. Show a visible countdown or explicit
Continue control; never seize active input without that boundary.

## Interaction lease state machine

`idle -> requested -> owned -> released`

From `owned`, physical user input causes `paused_by_user` immediately. From
`paused_by_user`, OpenWand may go only to `cancelled` or back through `requested`
after target revalidation and explicit user approval. Window changes, stale
elements, timeouts, or verification failures go to `failed` and release all
input hooks.

Injected events must carry a OpenWand-specific tag so the arbiter does not treat its
own events as user interruption. Hooks must be process-lifetime safe: install
only while a lease is requested/owned and always remove them in `finally` and
on worker shutdown.

## Delivery slices

1. Contracts and a deterministic fake accessibility backend. Prove locator
   ambiguity refusal, stale-target refusal, cancellation, and idempotency.
2. Read-only platform inspector. Capture a bounded tree from a OpenWand-owned test
   window without focus changes and redact editable values from diagnostics.
3. Semantic `invoke`, `set_value`, `toggle`, and `select` in the test window.
   Execute only after the normal HTML/CSS preview.
4. Purple ghost cursor driven by resolved bounds. Confirm it is click-through,
   does not activate the target, and disappears on every terminal path.
5. User-activity arbiter and lease using a test-only injected-input backend.
   Prove physical input pauses before adding production mouse/keyboard injection.
6. Real-input fallback behind a disabled-by-default capability flag. Add one
   tightly bounded real-app acceptance slice only after the pause/release tests
   pass.
7. Cross-platform parity: Windows UIA first, then macOS AX and Linux AT-SPI using
   the same contracts and acceptance cases.

## Definition of done for the first real slice

- The request enters through `Ctrl+Shift+Q`, not a disconnected test API.
- Context is gathered while the overlay is open.
- A typed semantic plan and exact HTML/CSS preview are produced.
- Cancel performs zero mutations.
- Apply resolves the same window and element again, executes, verifies the real
  postcondition, and records a content-free timing trace.
- The physical cursor does not move on the semantic path.
- Foreground focus is unchanged on the semantic path.
- Physical user input pauses an actual-input lease before OpenWand sends the next
  event.
- No target-app extension is installed.
- Windows, macOS, and Linux capability reporting is honest; unimplemented
  backends refuse rather than silently degrading to blind coordinates.

## Explicitly out of scope for the first slice

- Free-form computer use generated directly by the model.
- OCR-only targeting when no semantic element can be resolved.
- Credential entry, payments, security settings, destructive file operations,
  or approval dialogs.
- Long unattended workflows.
- Claiming simultaneous physical keyboard/mouse control. There is only one real
  OS input stream; coexistence comes from semantic APIs plus prompt yielding.

## Files already available to integrate with

- `core/actions/progress.py`: monotonic public progress stages.
- `runtime/supervisor/flows.py`: action routing, preview, confirmation, and
  content-free action telemetry.
- `runtime/workers/ui_host.py`: `ui.action.progress` and the HTML/CSS action
  preview host.
- `core/actions/contracts.py` and `core/actions/registry.py`: existing typed
  action boundary.
- `docs/ACTION_PLATFORM_PLAN.md`: canonical architecture, status, and decisions.
