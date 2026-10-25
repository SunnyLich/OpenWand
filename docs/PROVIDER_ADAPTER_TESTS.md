# Provider adapter conformance tests

Run from the repository with Python 3.12 and the locked runtime/development dependencies:

```powershell
.\.venv\Scripts\python.exe scripts\run_provider_adapter_matrix.py
```

The default runs all recovered offline suites and the recreated OpenAI supplement.
It blocks socket connections before collection, substitutes synthetic tools,
disables live provider tests, and isolates settings, app data, addons, and keychain
lookups. Temporary state stays under `.tmp/provider-adapters/`; JUnit output goes
to the ignored `reports/provider-adapters/offline.xml`.

## Sources and integration

The input was the recovered `provider-adapter-tests` bundle from October 11,
2026, based on `24aafe1ee34a9830d686f716e391008dce383fcc`. All supplied files
matched their delivery manifest's byte lengths and SHA-256 hashes before import.

| Recovered source | Repository location |
| --- | --- |
| `original/source/tests/test_provider_adapter_*.py` | `tests/test_provider_adapter_*.py` |
| Original matrix support and Claude credit guard tests | `tests/support/provider_adapter_matrix.py`, `tests/test_claude_credit_runner.py` |
| Original matrix and credit runners | `scripts/run_provider_adapter_matrix.py`, `scripts/run_claude_credit_tests.py` |
| `claude_v2/` Python modules, configuration, synthetic ledger fixture | `tests/integration/provider_adapters/claude_v2/` |
| `gemini_v2/parallelfix/` | `tests/integration/provider_adapters/gemini_v2/` |
| Gemini tests-only diff | `tests/test_gemini_provider_regressions.py` |
| Missing October 12 OpenAI supplement | Newly recreated as `tests/test_openai_provider_adapter.py` |

Imports were adapted to packages; obsolete checkout defaults now resolve relative
to this repository. The Gemini harness no longer creates directories, changes
process settings, clears credentials, or disables logging at import. Runner temp
paths work on Windows. The existing pytest configuration and catalogue generator
were merged selectively; historical copies did not replace them. The current
catalogue includes the imported tests and classifies live cases as isolated-host.
The runner does not grant itself isolated-host status.

Historical README instructions, pricing, budgets, and claimed live outcomes are
source context, not authorization for a new live run. No product fixes were
included in this integration.

## Windows comparison: October 24, 2026

Local environment: Python 3.12.13, pytest 9.1.1, OpenAI SDK 2.44.0, Anthropic SDK
0.113.0, on `dev` at `06a27ac4bee793127c33b38ddb80871c20bbb692` before this
integration. All provider responses were synthetic; no live provider or token-count
requests were sent and no provider charges were incurred.

After adapting the harness, the unmarked recovered Gemini regressions produced:
**405 passed, 17 failed, 36 skipped, 5 expected failures**. The local raw comparison
is retained in `reports/provider-adapters/baseline/offline.xml`.

The additional 17 failures are now strict expected failures, with their assertions
retained. Final execution: **405 passed, 36 skipped, 22 expected failures**.
Expected failures indicate unresolved behavior, not successful conformance.
Unexpected passes fail the suite so these annotations must be reviewed after fixes.

The related existing fallback, history, neutral harness, action planning, rewrite,
unsupported-parameter, SDK-client, and catalogue tests also passed: **127 tests
plus 53 subtests**. Their JUnit report is
`reports/provider-adapters/existing-regressions.xml`. Ruff and diff whitespace
checks passed. Standard-library temporary directories were directed inside this
repository for these checks because this Windows sandbox's system temp directory
denied access to child directories.

| Suite | Passed | Expected failures | Live skipped |
| --- | ---: | ---: | ---: |
| Original protocol | 23 | 2 | 0 |
| Matrix harness self-tests | 152 | 0 | 0 |
| Original Claude credit-runner guards | 20 | 0 | 0 |
| Claude v2 adapter, budget, review, continuation | 162 | 3 | 0 |
| Gemini v2 harness | 19 | 1 | 0 |
| Gemini recovered regression diff | 2 | 16 | 0 |
| Recreated OpenAI supplement | 27 | 0 | 0 |
| Live provider matrix | 0 | 0 | 36 |

The original five expected failures reproduce the documented follow-up tool-call
loss when Chat Completions ends with `finish_reason=stop` (four overlapping
provider checks), and Anthropic truncation being labeled final (one check).

The Gemini bundle's successful patched behavior does **not** reproduce on this
checkout: six checks expose dropped thought-signature metadata, lost indexless
parallel calls, or acceptance of unidentified fragments. Another eleven cannot
exercise their contract because the product helper
`core.llm_clients.tool_call_metadata.StreamToolCallAccumulator` is absent; these
are missing implementation prerequisites, not eleven independently proven defects.
The helper/product patches were excluded from the delivered sources.

Historical live Claude wording/content outcomes and Gemini's live `17,29` answer
cannot be compared here: historical result logs were excluded and no new live run
was performed. The retained authorized-prefix JSON is a synthetic accounting
fixture, not evidence of a provider run on this computer.

## Recreated OpenAI coverage

The new supplement is a reconstruction, not recovery of the lost file. It uses
the installed OpenAI SDK through `httpx.MockTransport`, exercising actual HTTP
serialization and SDK response parsing with socket connections prohibited:

- Nine synthetic scenarios on both Chat Completions and Responses: no tools,
  no tool needed, weather, numeric arrays, nested JSON, Unicode, parallel tools,
  dependent rounds, and tool-error recovery.
- HTTP 401, 403, 429, and 500 classification on both routes with SDK retries
  disabled and no tool execution after an error.
- Stateless Responses replay across three turns, retaining initial conversation
  and image context, encrypted reasoning, reverse-ordered parallel results, and
  exact `call_id` links without duplicate replay or server item IDs.

The replay contract follows [official OpenAI function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling).
The synthetic model name intentionally makes no claim about a particular model's
availability or quality. The SDK emits one Pydantic serialization warning while
the streaming Responses snapshot is recorded; the corresponding assertions pass.
These checks do not validate ChatGPT subscription/OAuth access or real model output.

## Optional live harnesses

Live entry points remain available for a separately authorized run. Ordinary
pytest skips the entire 36-case live matrix. No live opt-in is added to CI.
The matrix runner requires `--live`, an explicit provider/model, verified
non-billable credentials, hidden interactive key input, and an explicitly
designated isolated host (`OPENWAND_ISOLATED_TEST_HOST=1`). Request limits are
not account billing limits. Historical Claude pricing/date guards and Gemini's
reviewed-commit/prior-ledger guards remain intact; do not reset those guards to
reuse an old authorization.
