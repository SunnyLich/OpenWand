# Provider model catalog

Verified on 2026-10-27. The curated lists in `ui/settings_panel/dialog.py` are
suggestions for chat and text generation, not exhaustive provider inventories.
Settings, onboarding, and agent task dialogs share these lists. Account access
and task capabilities can differ; use the refresh button for the account's live
catalog or enter a model manually. Saved selections are preserved.

| Provider | Official catalog or reference |
| --- | --- |
| OpenAI API | https://developers.openai.com/api/docs/models/all |
| ChatGPT subscription | https://learn.chatgpt.com/docs/models |
| Anthropic | https://platform.claude.com/docs/en/models/overview |
| Google and Live voice | https://ai.google.dev/gemini-api/docs/models |
| GitHub Copilot | https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference |
| Groq | https://console.groq.com/docs/models |
| DeepSeek | https://api-docs.deepseek.com/quick_start/pricing |
| OpenRouter | https://openrouter.ai/api/v1/models |
| Mistral | https://docs.mistral.ai/models |
| xAI | https://docs.x.ai/developers/models |
| Together | https://docs.together.ai/docs/serverless/models |
| Cerebras | https://inference-docs.cerebras.ai/models/overview |
| Z.AI | https://docs.z.ai/guides/llm/glm-5.3 and https://docs.z.ai/guides/vlm/glm-5.3-flash |
| NVIDIA | https://docs.api.nvidia.com/nim/reference/llm-apis |
| SambaNova | https://api.sambanova.ai/v1/models |
| Hugging Face | https://router.huggingface.co/v1/models |
| Chutes | https://chutes.ai/app |
| Vercel | https://ai-gateway.vercel.sh/v1/models |
| Fireworks | https://docs.fireworks.ai/guides/recommended-models and its linked model pages |
| Cohere | https://docs.cohere.com/docs/models |
| AI21 | https://docs.ai21.com/docs/jamba-foundation-models |
| Nebius | https://nebius.com/services/token-factory/models/glm-models-inference |

Provider IDs are case-sensitive and differ between services. For example,
Anthropic uses `claude-sonnet-5-5`, while Copilot, OpenRouter, and Vercel use
`claude-sonnet-5.5`. Vercel's current Grok prefix is `spacexai/`.

GitHub Models retired on July 30, 2026, per
https://docs.github.com/en/github-models. Its suggestions and new-connection
template are empty/removed; existing settings remain readable. GitHub Copilot
is a separate provider.

GPT-5.5, GPT-5.4, and GPT-5.4 Mini retired from ChatGPT-authenticated Codex;
API availability differs. They are no longer subscription menu suggestions.
Legacy validation entries remain for saved configurations. Newly applied
Low setup presets use `gpt-6.1-sol`; saved profiles are not migrated.

Ollama lists only installed models discovered locally. Custom endpoints have no
universal catalog. Local Whisper speech recognition choices are unchanged.

This refresh verifies model names against official sources, not every model's
support for every OpenWand tool or voice workflow. No paid inference calls were
used to verify the catalogs.
