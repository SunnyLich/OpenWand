# Provider adapter conformance tests

## Shared adapter upgrade: October 27, 2026

The implementation now has an explicit registry for every provider in Settings.
Chat and structured planning/rewrite requests share protocol adapters and tool
validation, rather than separate per-provider argument parsers:

| Transport | Provider routes |
| --- | --- |
| Chat Completions | Groq, OpenAI, Google, DeepSeek, OpenRouter, Mistral, xAI, Together, Cerebras, Z.ai, NVIDIA, SambaNova, Hugging Face, Chutes, Vercel, Fireworks, Cohere, AI21, Nebius, Ollama, custom connections |
| Responses | ChatGPT; OpenAI GPT-6 tool requests |
| Anthropic Messages | Anthropic |
| GitHub Copilot SDK | Copilot, with only explicitly offered OpenWand tools enabled |
| Retired | GitHub Models is rejected with an explicit configuration error |

`provider_adapters.py` selects the protocol; `adapter_protocol.py` validates wire
data; `chat_tool_loop.py` applies the common execution policy. The compatible,
Responses, and Anthropic adapters retain conversation history and correlate every
tool result with its original call. Compatible streaming and complete replies use
the same decoder on every round, including calls ending with `finish_reason=stop`.
Provider reasoning and opaque Google signatures stay in the assistant transcript.

All tool executors enforce offered schemas, caller allowlists, stable unique IDs,
and call budgets. Malformed arguments receive correlated error results without
execution. Truncation, ambiguous IDs, and incomplete streams stop execution.
Schema references cannot fetch remote documents. Once a tool is dispatched,
transport failures cannot automatically replay the request on another model.
Legacy multimodal routes retain their existing screenshot handling; this upgrade
does not broaden screenshot forwarding. Model-specific tool and image support
still depends on the selected provider/model.

The new `tests/test_all_provider_adapters.py` exercises every compatible route
(including named custom connections) with the real OpenAI SDK over an in-memory
HTTP/SSE transport. It covers plain answers, no-call answers, single/parallel and
dependent calls, metadata, malformed JSON, schema failures, budgets, authentication
and provider errors, compatibility retries, and replay prevention. Native adapter
and Copilot fixtures cover their separate protocols. Registry coverage is checked
against the Settings provider list.

Verification after the upgrade: **586 passed, 36 live skipped, zero expected
failures**, recorded in `reports/provider-adapters/all-provider-upgrade/offline.xml`.
The existing chat, failover, action-planning, and rewrite regressions also pass
(97 tests and 53 subtests), as do the three mocked Copilot bridge tests. Ruff and
diff whitespace checks pass. One existing OpenAI SDK/Pydantic snapshot warning
remains; its assertions pass, as described under the recreated OpenAI coverage.

These are offline protocol tests. They do not prove live model availability,
account access, model quality, or every model's support for tools/images. No live
provider calls or paid inference are part of the default run. The historical
results below describe earlier implementations and are retained for comparison.

Protocol decisions follow the official [OpenAI function-calling guide](https://developers.openai.com/api/docs/guides/function-calling),
[OpenAI latest-model guide](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra),
[Anthropic tool definitions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools),
[Google compatibility guide](https://ai.google.dev/gemini-api/docs/openai),
[DeepSeek thinking guide](https://api-docs.deepseek.com/guides/thinking_mode/),
and [OpenRouter reasoning guide](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

## Live web-search workflows: October 31, 2026

OpenWand's client-side `web_search` uses DDGS public metasearch with automatic
engine fallback and no separate search API key. Cloud model requests still use
the selected provider's credentials. Claude's Messages route retains Anthropic's
server-side search; the client completion guard does not replay a search that
Anthropic executes inside the API request.

Real isolated ChatWindow workflows passed with Ollama `llama3.1:8b`, Google
`gemini-2.5-flash-lite`, and ChatGPT `gpt-6-luna`. Each requested the official
London, Ontario forecast page and returned its title and exact Environment Canada
URL from live search. Provider replies and search results were not mocked.
Screenshots captured only the isolated offscreen test window; desktop, personal
browser, clipboard, and audio access were disabled.

The Windows executable also passed a real brain-worker search using Ollama and
the bundled DDGS networking extension. No Claude credential was configured for
these live checks, so Claude's server-search handling was verified with a protocol
fixture, not a live Claude request. These results do not establish live support
for the remaining providers or every model. Local evidence is under the ignored
`reports/readiness/2026-10-31/` and `reports/web-search/2026-10-31-ddgs/` directories.

Public search-source URLs remain readable in tool results. Credentials, detected
private URL content, and local-network source URLs remain protected. Other tool
results retain the normal privacy policy.

## Running the offline matrix

Run from the repository with Python 3.12 and the locked runtime/development dependencies:

```powershell
.\.venv\Scripts\python.exe scripts\run_provider_adapter_matrix.py
```

The default runs the all-provider matrix, recovered offline suites, and recreated OpenAI supplement.
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

### Gemini tool-call fix after the imported baseline

The product adapter now preserves `extra_content` (including Google's opaque
`thought_signature`) in streamed calls, nonstreaming fallback responses, and
later tool rounds. The stream accumulator correlates fragments by index or call
ID, retains metadata-only deltas, and rejects conflicting identities before tool
execution. Replay copies metadata so SDK responses and request history do not
share mutable dictionaries.

The 17 Gemini expected-failure annotations described above have been removed;
all those checks now pass. The offline matrix after this fix reports **422
passed, 36 skipped, 5 expected failures**, with no failures or errors. Its JUnit
report is `reports/provider-adapters/gemini-signature-fix/offline.xml`. The five
remaining expected failures are the unrelated behaviors described above. This
verifies the source adapter with synthetic responses; installed applications
need a new build containing the fix.

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
