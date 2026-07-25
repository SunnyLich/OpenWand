# Speech installation contract

Wisp treats speech configuration, package files, runtime imports, model assets,
and live readiness as separate facts. A provider is ready only when every
required layer is valid.

## Source and release ownership

| Runtime | Initial speech packages | Repair/install tool | Runtime preference |
| --- | --- | --- | --- |
| Source checkout | Platform lock in `.venv` provides STT and ElevenLabs | Current Python and `pip` stage a managed repair | Valid managed repair first, otherwise the locked source environment |
| Packaged release | STT, Kokoro, and ElevenLabs SDKs are excluded from the ZIP | Bundled `uv` stages packages under the user-data directory | Managed package layer only |

Remote TTS providers that use Wisp's normal HTTP clients do not need an
optional package installation. Kokoro is always optional because its Torch and
model payload is too large for the release bundle.

## Installation transaction

1. Build an exact provider plan. Its contract includes package pins, platform,
   CPU architecture, Python implementation/ABI, selected device mode, and the
   Wisp version.
2. Download into a new staging directory. The running package directory is not
   modified.
3. Persist the plan, log, and status under the stable user-data `installers`
   directory. A per-run diagnostics directory never owns control state.
4. Report `restart_required`. Download completion is not installation success.
5. After Wisp exits, copy the active optional layer, replace distributions
   supplied by the stage, atomically swap the replacement into place, and roll
   back if activation fails.
6. Verify exact distribution metadata and the real import entry point. STT also
   verifies device/model construction; Kokoro verifies Torch and pinned
   model/voice assets.
7. Only after verification succeeds, save the selected speech settings, mark
   the install successful, and reopen Wisp when the user requested an immediate
   restart.

Interrupted staged installs remain resumable. A Wisp/package/Python contract
change invalidates and discards the old stage instead of applying incompatible
wheels later.

## Canonical status states

`core.speech_status` is the authority used by Setup Check, Settings, and the
audio worker. It reports the package source and these phases:

- `disabled` / `not_configured`: the feature is intentionally off or incomplete.
- `not_installed` / `repair_required`: package metadata is absent or invalid.
- `installing`: a durable installer plan is downloading or preparing files.
- `restart_required`: files are staged but have not been applied or verified.
- `install_failed`: the installer or post-install verification failed.
- `assets_required`: local packages load, but selected model/voice assets do not.
- `installed`: packages/runtime/assets pass; lazy model warmup has not completed.
- `warming`, `ready`, `failed`: live audio-worker state.

The current package/runtime checks remain authoritative over an old successful
installer message. Persisted installer state is accepted only when its Wisp and
installation-contract fingerprints still match.

## Recovery rule

Install/Repair always creates a complete managed provider layer. This is also
the recovery path for a source checkout whose `.venv` metadata exists but whose
native files cannot import. Unrelated optional providers are preserved during
the staged merge.
