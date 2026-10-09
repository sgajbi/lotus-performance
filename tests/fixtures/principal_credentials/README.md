# Signed principal conformance fixtures

These fourteen files are unchanged committed fixtures from
`sgajbi/lotus-platform` at `2b4082f387e6cce559e3f5410dbdf6851890fad1`,
under `platform-contracts/principal-credential/examples/`.
The JWKS committed blob is `c2ed7197ee82714f6a71fc1834ed93a8f330492e`.
They exercise three signed valid credentials and ten denial cases against
Performance's own cryptographic adapter. Their pinned issuer, audiences and
September evaluation instant are conformance inputs, never deployment trust.

Performance-specific API tests generate independent ephemeral Ed25519 keys and
install isolated test-only revocation, membership and grant ports. No production
identity provider, entitlement store or financial-maker approval is certified.
