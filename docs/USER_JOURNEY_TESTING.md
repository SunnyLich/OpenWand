# OpenWand user journey testing and reports

The `User journeys` GitHub Actions workflow launches the real app, completes
first-run setup, adds a provider through Settings, sends prompts through the
real workers and SDK, and checks the visible results and persistence across
eight separate launches. It runs on Windows, Linux and macOS for pull requests
and pushes to `dev` and `main`. Release builds repeat these journeys in a test
executable, then rebuild and smoke-test the production executable before packaging.
Full journey drivers and fake services are excluded from production bundles.
Set `OPENWAND_BUILD_JOURNEYS=1` only while building a test executable for the
`--packaged` runner. The source runner needs no special build flag.

The provider is an explicit HTTP fixture, credentials use a disposable keyring
backend, and external desktop input is synthetic. OAuth cache paths are isolated
too. An external browser fixture tests declined, mismatched-state and incomplete
ChatGPT callbacks without visiting OpenAI or issuing tokens. No personal provider
account or login is supplied. The report
does not describe those substitutions as a live provider or real ChatGPT login.

## What completing the tests means

Running the existing tests is verification of the current slice. Completing this
work means writing the missing user journeys in the
[full checklist](USER_JOURNEY_COVERAGE.md), beginning with ordinary daily actions.
The implementation is still in progress; a passing count is not a substitute for
coverage of the remaining capabilities.

For each user capability, the applicable journeys must cover its normal result,
invalid input, cancellation or refusal, failure and recovery, and saved state after
reopening or restarting. Each journey needs an observable outcome: what the user
sees and the relevant real request, file, stored state or system effect. Opening a
page alone does not prove that its controls work. Newer product surfaces also
belong in the checklist even when they have no older inventory ID.

Account, voice, native-desktop and installed-release paths need appropriate test
environments and their own execution evidence. Missing environments remain gaps;
they do not turn into passed journeys. The numbered report describes specific
executed states, while the checklist identifies the authoring work still needed.

## What runs together

The input driver sends Qt mouse, keyboard, and file-drop events to production
widgets in the running UI worker. It does not call the app's send, save, model,
or persistence handlers in place of a user action. Those widgets use their
normal signals, the real supervisor, worker IPC, production SDK, HTTP socket,
and file stores. The provider records received requests independently, allowing
the tests to check the model, conversation context, privacy redaction and tool
access that actually reached the network boundary.

The numbered scenarios in
[`scenarios.py`](../scripts/user_journeys/scenarios.py) have comments explaining
the user action and the result being checked. They include onboarding, provider
and model setup, save and discard, prompting, follow-up, new conversations,
attachments, errors and recovery, cancellation, all Settings pages, appearance,
Memory, Addon Manager, multiline input, history search, privacy, context controls
and process restart. Additional commented stories in
[`extended_scenarios.py`](../scripts/user_journeys/extended_scenarios.py) cover
provider removal/search/filtering, fallbacks and cooldown, project and conversation
menus, memory editing/deletion/tools, privacy review/cancellation, profiles, real
Qt file/folder choosers, file permissions/approval/refusal/writes/blocked paths,
manual model names, large connection lists and ChatGPT sign-in error recovery.
They also click the floating icon, wait for its picker to become interactive,
submit custom prompts, observe live text, cancel with Escape, choose built-in
actions by mouse/key, and open the bubble's saved conversation for follow-up.
Each completed answer also requires independent evidence of a real HTTP request.
The basic stories in [`basic_scenarios.py`](../scripts/user_journeys/basic_scenarios.py)
run before the more complex workflows. They cover blank and whitespace prompts,
keyboard sending, IME/Unicode, drafts, attachment cancellation/removal/multiple
files/images, history switching, the three Settings model-test buttons and their
errors, zoom, branch/rewind, page reset, picker timeouts, context controls and
reopening guided setup. [`addon_scenarios.py`](../scripts/user_journeys/addon_scenarios.py)
installs a disposable package through the real installer, reviews access, edits
settings, executes model tools, checks separate host logs and tests enable/disable
and unsafe-package errors. [`agent_scenarios.py`](../scripts/user_journeys/agent_scenarios.py)
uses real tasks, role handoffs, scoped file creation, approval/refusal, cancellation
and saved history. Its fixture controls model decisions, not the runner.
[`workspace_scenarios.py`](../scripts/user_journeys/workspace_scenarios.py) installs
the shipped Workspace addon and exercises its actual authenticated local server,
file explorer, editor, recoverable trash, reconnection and service shutdown.

[The complete coverage checklist](USER_JOURNEY_COVERAGE.md) lists every inventory
entry and the newer product surfaces. An implementation link describes a specific
written path; it does not close untested variants or establish a passing result.
The HTTP fixture checks the configured synthetic credential without logging it.
A wrong-key/replacement journey verifies authentication errors and client reload.
The final audit compares UI observations with independent HTTP timestamps: some
answer text must be visible before the provider finishes its response. Provider
previews and the final answer update the same Chat/bubble response state. Addons
that require a complete response still transform it before any raw answer becomes
visible. The timing audit remains a required check; it is not satisfied by a
waiting indicator or text revealed only after the provider finishes.
This is an expanding whole-app suite, not a claim that every
function in the older catalogue already has whole-app coverage.

## Run locally

Use a new output directory for each execution:

```powershell
Set-Location C:\OpenWand
.\.venv\Scripts\python.exe -m scripts.user_journeys --output reports/user-journeys-local
```

After building the application, exercise the executable with:

```powershell
.\.venv\Scripts\python.exe -m scripts.user_journeys --packaged --output reports/packaged-user-journeys-local
```

An output directory contains isolated test state and synthetic credentials.
The runner refuses to seed over an existing state directory. Later launches
reuse the state created by the previous launch; the tests
must obtain saved settings and history through the app. A separate real Windows
mutex prevents the test instance from contending with the installed app's
single-instance guard. Launch-at-login synchronization is disabled for these
disposable profiles. Global hotkeys, native clipboard and live audio are not
certified by an offscreen GUI run.

## Read the reports

Download `user-journeys-windows`, `user-journeys-linux`, or
`user-journeys-macos` from the GitHub run. Each artifact contains:

- `report.md`: numbered journeys, what each tests, actual execution status,
  screenshots, and links to exact code sections. GitHub links use the run's
  commit SHA and line ranges obtained from Python syntax, rather than manually
  maintained line numbers.
- `coverage-checklist.md`: every inventory capability, its written journey links,
  and the remaining implementation work, including newer product surfaces.
- Phase result JSON: user actions, observations, failures, durations and
  screenshots for onboarding, the next launch and the restart launch.
- Phase readiness JSON: supervisor and worker process identities and readiness.
- Process logs and `provider-requests.json`: runtime diagnostics and independently
  observed synthetic provider requests. Authentication headers are not recorded.

The report also lists all 472 entries from the existing product inventory,
their existing test-code sections and any whole-app evidence from this run.
An old `real_entry_accepted` label is not treated as evidence of a whole-app pass.
Missing, blocked, repeated or skipped required journeys fail the new runner.
Screenshot capture failure also fails it. An exception in a prerequisite leaves
dependent cases explicitly blocked. Independent basic, addon, agent and workspace
stories continue, with normal Cancel/Escape/Stop recovery recorded between them.
Failures remain failures and later phases still run; an incomplete initial setup
blocks the launch chain. An unexpected standard modal is cancelled with Escape
and recorded as a failure, never automatically approved.

Each hosted job also runs a negative control: its provider deliberately returns
an unrelated answer. That control succeeds only when the real first-prompt
journey fails its visible-response assertion. An unrelated startup failure is
not accepted as proof of failure detection. Its deliberately failing journey
report is retained in a separate `user-journeys-negative-control-*` artifact.

Regular CI and macOS test shards upload `test-code-report-*` artifacts. These
separate reports explain each executed existing test, preserve its pass, failure
or skip, and link its code section. Independent test files continue after an
earlier file fails, so the report can show the remaining results. The job retains
its failure status.

## Live services and full product acceptance

Browser OAuth, real provider accounts, microphones and speakers, native app
actions, and installation/update/uninstall require their own appropriate test
environments. Their whole-app coverage remains unverified until actual execution
evidence exists. A startup-only package smoke does not prove installation or
updates. A source run does not prove a packaged build. A local HTTP fixture does
not prove external browser sign-in.

The existing manual `isolated-tests` workflow references dedicated runners and
test-only secrets. That configuration is not proof that those runners or accounts
exist. The new hosted workflow uses no real provider secrets and runs with a
read-only GitHub token; checkout does not persist credentials. Its artifacts
exclude the disposable credential file and application state directory.

Full-product acceptance must be assessed from the explicit gaps in the report,
not inferred from a green result for this bounded set of journeys. The earlier
function inventory remains the product scope reference:
[`APP_FUNCTION_INVENTORY.md`](APP_FUNCTION_INVENTORY.md).

## Reading the test code in plain language

For example, `app.send("E2E_FIRST_PROMPT")` types and sends that text through
the app. `app.reply("E2E_FIRST_PROMPT")` checks the visible answer and the
provider's independent record. `app.request("E2E_FIRST_PROMPT")` reads the
request that actually arrived at the local test provider.

| Code term | Meaning here |
|---|---|
| `self` | The current test helper, holding its connection to the running app and its recorded steps. |
| `marker` | A distinctive piece of test text used to find the correct prompt or answer. |
| Request log | `provider-requests.json`: a record written by the local HTTP provider when it receives a request. |
| `OPENWAND_E2E_OUTPUT` | An environment variable containing this run's report folder, set by the outer runner. |
| `os.environ[...]` | Read an environment variable. |
| `Path(...) / "provider-requests.json"` | Build the path to that file inside the report folder. |
| `json.loads(...)` | Turn the file's JSON text into Python lists and dictionaries that the checks can inspect. |
| `rows` | All recorded provider requests. |
| `matches` | Only the requests containing the marker being checked. |
| `matches[-1]` | The last matching request. |
| `assert condition, "message"` | Fail the test with that message if the condition is false. |
| `payload` | The request body, including the model name, messages and offered tools. |
| `authenticated` | Whether the expected synthetic test credential reached the provider; the credential itself is not logged. |
| `return` | Give the checked value back to the calling test for further checks. |

An assertion proves only the particular condition it checks. Receiving a request
does not by itself prove that a user saw the right answer; that is why these
journeys also check the UI, completed response, saved state and relevant side
effects. The report identifies the external substitutes and remaining gaps.
