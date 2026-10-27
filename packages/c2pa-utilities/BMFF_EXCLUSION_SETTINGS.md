# BMFF Exclusion Settings Proposal

This is a dependency-blocked proposal for Contentauth `c2pa-js` `main`, based on
`23718c0aebdf75411cc4b46d40923375ea10994d`, not a supported stock-runtime feature.
The unchanged native dependency is `c2pa = "=0.91.7"`. Stock 0.91.7 does **not**
support `builder.bmff_hash_extra_exclusions`.
Do not use this setting with an unsupported native SDK or rely on it producing an
error for unsupported settings. Native validation below assumes a compatible SDK.

The native feature is currently fork-first in
[mstattma/c2pa-rs PR 37](https://github.com/mstattma/c2pa-rs/pull/37), unmerged
upstream. There is no accepted Contentauth release number yet. The minimum
compatible native release must contain the generic
`builder.bmff_hash_extra_exclusions` feature **and matching descriptor support**.
Record the actual accepted Contentauth native version here before upstream
submission; no personal native pins are proposed or added.

## Facade And Limits

`BuilderSettings.bmffHashExtraExclusions` types descriptors with `xpath`, optional
`length`, `data`, `subset`, `version`, `flags`, and `exact`. The existing settings
serializer emits `builder.bmff_hash_extra_exclusions`; omission leaves defaults
unchanged, while an explicit empty array remains an empty array. With a compatible
native SDK, these exclusions append to its required/default exclusions.
`mergeSettings` combines exclusion arrays rather than replacing them: a later
empty array does not clear earlier exclusions. To narrow or replace a list,
assign it on the final settings object after merging.

Lengths and offsets must be nonnegative JavaScript safe integers, at most
`Number.MAX_SAFE_INTEGER`; JavaScript numbers cannot represent every native
64-bit integer. Byte-match values and FullBox versions must be integer bytes
(0-255); flags must contain exactly three integer bytes. `exact` requires flags
even when false. A final subset length of zero means through the box end.
These are caller constraints, not JavaScript runtime validation: native
validation is authoritative. Excluded bytes are unauthenticated, so only exclude
content that is safe to leave unsigned.

No reusable generated settings or BMFF exclusion descriptor type exists in the
current `@contentauth/c2pa-types` exports. Its schema pipeline targets Reader,
ManifestDefinition, Ingredient, Builder, and Action, not SDK settings. This
proposal keeps the small descriptor inline in the existing hand-written facade;
the generation pipeline is not broadened and generated types are unchanged.

The focused Node-only CI job typechecks `tsconfig.settings.json` and runs only
`settings.spec.ts` and `caseConversion.spec.ts`. These tests prove typings and
serialization only, including arrays, numeric conditions, zero/false, input
preservation, and empty/default behavior. They do not prove native acceptance,
signing, validation, or runtime support on stock 0.91.7. Native Builder tests are
deliberately excluded until the dependency blocker is resolved. No local install,
test, or build was run for this proposal.

## Draft PR Text

Unpublished draft. Target: `contentauth/c2pa-js`, base branch `main`.

Title: Add typed BMFF extra-exclusion settings facade (dependency blocked)

Summary: Add optional `builder.bmffHashExtraExclusions` descriptor typings,
numeric settings-value support, focused serialization tests, and a Node-only
utilities CI job. Existing settings resolution and defaults remain unchanged.
This is a typings/serialization proposal, not a claim of stock runtime support.

Minimum native dependency blocker: stock `c2pa = "=0.91.7"` lacks the setting.
The generic feature and matching descriptor support must land in an accepted
Contentauth native release; the actual minimum version must be recorded before
upstream submission. The current native work is fork-first mstattma/c2pa-rs
PR 37, unmerged upstream, with no accepted Contentauth release number yet.
No personal native pins, Rust changes, generated-type changes, version changes,
or release-workflow changes are included.
