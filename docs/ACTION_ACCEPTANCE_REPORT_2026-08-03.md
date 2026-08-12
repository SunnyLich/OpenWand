# OpenWand multi-app action acceptance report — 2026-08-03

This report distinguishes real application execution, production picker
acceptance, fake-client contract coverage, and blocked integrations. A picker
screenshot proves detection and UI behavior; it is not counted as successful
application mutation.

## Results

| Surface | Detection/picker | Real mutation | Evidence | Remaining blocker |
| --- | --- | --- | --- | --- |
| PowerPoint desktop | Pass; three live actions | Pass through shared `ActionRunner` and COM; exact slide readback; foreground HWND unchanged | `.codex_tmp/acceptance_report/presentation/shared-runner/` | Broader ordinary-session user acceptance |
| PowerPoint web | Pass; two disabled actions | Not attempted | `.codex_tmp/acceptance_report/provider-pickers/powerpoint-web.png` | OpenWand Office.js bridge and authentication |
| Google Slides | Pass; three disabled actions | Not attempted | `.codex_tmp/acceptance_report/provider-pickers/google-slides.png` | Concrete Slides REST client and Google OAuth |
| Excel desktop | Adapter acceptance pass | Pass in a hidden disposable `DispatchEx` workbook; table/chart readback, source preservation, and unchanged focus | `.codex_tmp/acceptance_report/excel/` | Production picker/shared-runner route and complete rollback |
| LibreOffice Calc | Pass; four app actions | Existing managed UNO acceptances pass for chart, formatting, sort, verification, and Undo | `.codex_tmp/acceptance_report/calc/` | Advanced formula/filter/deduplication/conditional-format/pivot executors |
| Google Sheets | Pass from canonical URL or foreground title; two disabled actions | Not attempted | `.codex_tmp/acceptance_report/provider-pickers/google-sheets.png` | Concrete Sheets executor and Google OAuth |
| VS Code saved file | Pass; fix/refactor live | Pass with fingerprint revalidation and disk readback | `.codex_tmp/acceptance_report/vscode/` | Broader multi-file operations |
| VS Code Untitled | Pass in isolated owned session | Pass through official Extension API; version 1 to 2; exact readback; no focus activation | `.codex_tmp/acceptance_report/vscode/` | Automatic bridge loading for ordinary OpenWand-managed sessions |
| Gmail web | Pass; draft/label rows visibly disabled | Not attempted | `.codex_tmp/acceptance_report/account-pickers/gmail.png` | OAuth/token storage and concrete Gmail/Calendar clients |
| Outlook mail web/desktop | Pass; draft/category/disabled-rule rows visibly disabled | Not attempted | `.codex_tmp/acceptance_report/account-pickers/outlook-mail.png` | OAuth/token storage, concrete Graph clients, live acceptance |
| Google Calendar | Pass; create/reschedule visibly disabled | Not attempted | `.codex_tmp/acceptance_report/account-pickers/google-calendar.png` | OAuth/token storage and concrete Calendar client |
| Outlook Calendar | Pass; create/reschedule visibly disabled | Not attempted | `.codex_tmp/acceptance_report/account-pickers/outlook-calendar.png` | OAuth/token storage, concrete Graph client, notification-policy acceptance |
| Chrome form fill | Existing managed-session pass | Existing real-model acceptance filled reviewed fields, verified values, and never submitted | `.codex_tmp/chrome-form-api-after.png` | Authenticated DevTools pipe and automatic session adoption |

No email, calendar, category, rule, or attendee state was changed during this
audit. The environment contains no matching Google/Microsoft OAuth configuration
or OpenWand token cache, and OpenWand does not yet contain concrete authenticated account
clients. The account tests use normalized fake clients and are not presented as
live acceptance.

## Bugs found and fixed

1. Outlook's current `outlook.cloud.microsoft` and established
   `outlook.office365.com` hosts were missing from account detection.
2. Google Sheets, Google Slides, and PowerPoint web could fall through to the
   generic browser provider when browser URL capture was disabled. Conservative
   browser-process plus app-title detection now covers that case.
3. Provider names were passed to the picker but not painted. App-owned rows now
   have a visible `Gmail actions`, `Google Calendar actions`, `VS Code actions`,
   and equivalent heading.
4. Excel's real late-bound COM `Range.Address` can be a string property rather
   than a callable. Snapshot capture now accepts both forms.
5. Excel mixed text/numeric tables could retain a chart whose series consisted
   entirely of zeroes. Chart creation now uses the first text column as
   categories and numeric columns as series; the real acceptance read back all
   six expected revenue values.
6. An unwritable action telemetry log raised `PermissionError` and crashed Calc,
   VS Code, and browser action tests. Timing diagnostics are now best-effort and
   cannot block an approved action.
7. An explicit `OPENWAND_ADDONS_DIR` test/runtime override was contaminated by
   automatically seeded bundled addons. Explicit addon roots are now isolated.
8. Feature-acceptance manifests still claimed a removed external-transcript
   push UI was accepted. The manifest now truthfully records one component-only
   function, one untested function, and one pending interaction.
9. The default-caller test inherited the user's real `CALLER_1_HOTKEY`, so a
   valid `ctrl+1` preference was misreported as a product-default failure. The
   test now isolates that variable.
10. A Settings Apply workflow invoked real Windows startup synchronization; its
    failure opened an offscreen modal warning and hung the suite. The workflow
    now isolates that operating-system side effect.
11. A TTS worker-lifetime test launched machine-dependent optional-runtime
    probes. It now controls the first status probe and tests only the lifecycle
    contract it claims to cover.
12. Locale catalogues had drifted, Windows UIA fixtures described an obsolete
    clipboard route, and several Qt styles used unsupported `rgba()` syntax.
    The catalogues and compiled translations are synchronized, the fixtures
    assert the captured background-input identities, and the styles use solid
    composited/theme-derived colors.

## Verification

- Every one of the 195 catalogued pytest files was attempted. The 146 top-level
  files passed 2,107 tests and skipped 104, with 97 additional subtests passing.
- The 49 runtime, integration, support, and catalogue files were rerun together
  after all fixes: 753 passed, 2 skipped, and 49 subtests passed.
- Aggregate bounded result: **2,860 passed, 106 skipped, and 146 subtests
  passed**. This accounts for all 2,966 collected pytest nodes; the catalogue
  also contains three manual diagnostics.
- The two formerly timed-out files are fully covered by bounded splits:
  `test_app_user_workflows.py` passed 92/92 and
  `test_feature_acceptance_workflows.py` passed 45/45.
- A final action, picker, locale, native UIA, and catalogue regression passed
  189 tests. Ruff and Python compilation pass for the modified action/runtime
  surfaces.
