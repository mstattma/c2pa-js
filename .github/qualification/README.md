# Fragment-offset candidate qualification

This is a fork-only, non-publishing check of the JS source patch paired with an
exact maintained SDK candidate, **not** a dependency pin for a published package.
The committed `Cargo.toml` and `Cargo.lock` retain registry `c2pa = "=0.91.0"`.
That stock dependency cannot build the new offset/filter API yet. The source
patch needs acceptance of upstream SDK [#2832](https://github.com/contentauth/c2pa-rs/pull/2832)
and an appropriate released SDK before normal registry builds/publication work.

The candidate is separately configured in `fragment-offset-sdk.json`:
`https://github.com/castlabs/c2pa-rs` at
`6021100cc5060b06061ca15b634281cfeb97c718` (`0.92.0-dev`). There is no moving
branch, second committed Cargo pin, or fallback to a different SDK.

## Trigger and authority

`fragment-offset-qualification.yml` runs on PR open/synchronize/reopen/ready,
including draft PRs. It requires repository **and head repository**
`mstattma/c2pa-js`, branch `feat/upstream-fragment-base-offset`, author `mstattma`,
and `author_association == OWNER`. No label, release event, default-branch push,
dispatch, credentials, or publishing permission is involved. Its token is
`contents: read` and checkout does not persist credentials. All external actions
are SHA-pinned; neither Cargo, pnpm nor Nx uses a shared CI cache.

Only that exact authorization condition skips the ordinary `CI / main` job,
whose stock SDK cannot compile this feature. `CI / Enforce Rust code format`
still runs. All other repositories, branches and PR authors retain normal CI.
**Candidate SDK + Web (Chromium and Firefox)** is the authoritative qualification
check for this fork PR. It does not claim the unmodified registry build passes,
nor qualify c2pa-node or download Trustmark models.

## Transient runner override

`tools/qualification/sdk_override.py prepare` refuses to invoke Cargo outside
GitHub Actions. It snapshots the original manifest/lock and exact JS PR HEAD,
validates the SDK repository allowlist and 40-hex revision, then replaces only
the workspace c2pa dependency source with `git` + `rev` on the runner. A Cargo
`[patch]` alone would not satisfy the existing `=0.91.0` requirement with
`0.92.0-dev`, so this manifest mutation is deliberate and recorded.

The runner generates a new lock and checks both full `cargo metadata --locked`
and the resolved lock for exactly one `c2pa`, the expected version, and the exact
git source including resolved SHA. Registry fallback is an error. The exact
resolved `wasm-bindgen` crate version determines the installed CLI version.

After lock preparation and CLI installation, a runner-generated PATH wrapper
adds `--locked` to every Cargo build, metadata or schema-generation call made by
Nx. It rejects update/install/publish commands and checks manifest/lock digests
before and after every invocation. This keeps the normal Nx executor unchanged;
`CARGO_NET_OFFLINE` alone would not prevent lock mutation. The final gate checks
the digests again. Policy tests mock all subprocesses and execute no Cargo.

## Required checks and evidence

Rust 1.96.0 with `wasm32-unknown-unknown`, Node 22.22.1, pnpm 10.15.0 and frozen JS
dependencies build the Nx WASM target (including its existing Binaryen 124
optimizer), generated schema declarations, utilities and web declarations.
Web lint and the existing web/utilities typecheck targets are mandatory. The
full web suite runs separately on Chromium and Firefox with `testTimeout=60000`.
Both JSON reports must pass and each must contain all nine offset tests with
no skipped/pending cases. Assertions are not relaxed for this newer SDK. Any
semantic baseline differences must be investigated/reported, not suppressed.
After a successful build, typechecks and both browsers run independently so a
typecheck failure still retains browser evidence. Every failure remains fatal
to the job; there is no `continue-on-error`. Nx schedules the selected build
targets together to avoid compiling WASM twice through web dependencies.

Artifacts are retained for 14 days: original/effective manifest and lock,
source identities and tracked JS source archive, full Cargo metadata, effective
override and digests, Cargo-wrapper invocation log, toolchain versions, build,
lint, typecheck and browser logs/reports, generated WASM/JS with `WASM_SRI`, and
the web build. Failed runs retain whatever evidence was produced. Nothing is
released or published, and this is not evidence of Node test coverage.

Local policy-only verification (no Cargo):

```sh
python3 -m unittest discover -s tools/qualification -p 'test_*.py' -v
```
