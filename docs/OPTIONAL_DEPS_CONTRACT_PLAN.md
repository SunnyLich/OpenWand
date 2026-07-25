# Optional dependency contracts

## Invariants

Wisp recognizes complete dependency contracts, never a package-by-package
union. An installed optional runtime is valid only when every dependency in one
recognized contract has its exact locked version and its required imports are
present.

- **Source contract:** exact versions from the checked-in platform runtime lock.
- **Release contract:** exact versions embedded in the in-app installer for the
  release being built.
- Source and Release may be identical. If a release artifact is unavailable,
  an alternative is accepted only after the entire Release contract is resolved,
  tested, and committed. Runtime pip resolution never invents a third contract.
- A mixture of Source and Release versions is invalid even when every individual
  version would satisfy upstream range constraints.
- Model weights and voices are shared assets; Python dependency contracts do not
  force duplicate model downloads.

## Supported targets

| Platform | Architecture | STT variants | Kokoro variants |
| --- | --- | --- | --- |
| Windows | x86-64 | CPU, CUDA/Auto | CPU, GPU/Auto |
| Linux | x86-64 | CPU | CPU, GPU/Auto |
| macOS | ARM64 | CPU | CPU |

ElevenLabs and Live voice each have one variant on every supported target.

Other operating-system/architecture combinations are source-only and best
effort. They use the source environment normally. Wisp does not build a release,
generate a compatibility contract, or promise support for those targets.

## Contract sources

Both contract kinds are materialized under `requirements/optional/` as 30
independent locks (15 supported variants times two kinds). They are resolved
against the matching checked-in runtime constraint:

- `requirements/requirements-windows.lock`
- `requirements/requirements-linux.lock`
- `requirements/requirements-macos.lock`

`scripts/compile_dependency_locks.ps1 optional` and
`scripts/compile_dependency_locks.sh optional` regenerate the full matrix with
uv's cross-platform resolver. Source and Release files remain separate even
when they are currently identical, so a later release-only deviation cannot
silently alter the Source contract. The optional installer reads its package
list directly from the applicable Release lock.

## Installation and activation

1. Resolve/download packages into a staging directory.
2. Validate that staging matches one complete Release contract.
3. Add or update `.wisp-contract.json` inside the replacement directory.
4. Atomically rename the replacement directory into service.
5. Deep-import the feature in a short-lived process before reporting success.
6. Retain or restore the prior directory if activation fails.

The provenance document records the contract kind, fingerprint, exact package
map, target platform/architecture, Python ABI, and selected device variant.

## Verification

- Lock tests reject conflicts between runtime, developer, and build locks.
- Contract tests accept a complete Source manifest and a complete Release
  manifest, and reject hybrids.
- `.github/workflows/optional-contracts.yml` installs and imports every CPU
  Release contract natively on Windows x64, Linux x64, and macOS ARM64.
  Cross-compilation produces locks but does not replace native import testing.
- GPU contracts are resolution/import checked where hosted CI has no GPU; real
  model initialization remains a hardware acceptance test.
