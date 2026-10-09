# Composite receipt verification

The configured Performance verifier consumes signed synthetic return-method/calendar receipts.
It does not establish bank approval, production IAM readiness or GIPS compliance. Operators
should leave it unconfigured until they have independently reviewed the exact artifact and
transport identity. Missing or invalid configuration returns unavailable evidence.

## Deployment contract

Set `COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON` to the JSON configuration described by
`ReceiptVerifierConfiguration` in
[`configuration.py`](../../app/adapters/composite_receipt_verification/configuration.py).
The [synthetic example](../examples/composite_receipt_verifier.synthetic.json) contains a public
test key and fictitious identities; its endpoint is not a deployed service. Supply the outbound
Bearer credential through the environment variable named by `credential_env`. The configuration
contains no private signing key or outbound credential value.

Each registration independently pins the tenant, composite, definition, immutable subject hash,
exact method binding, effective interval, verifier, issuer and artifact revision/digest. A request
must match exactly one registration. The registry is a bounded deployment allowlist, not a log of
request hashes. It supports `RETURN_METHOD_CALENDAR` with no `source_product`; the legacy boolean
approval port remains unavailable because it lacks the staged subject hash.

The consumer sends the typed `VerificationRequest` as a JSON POST. A successful response is exactly
an object with `owner_service`, `payload` and `credential`: the payload is a typed
`CompositeEvidenceVerificationReceipt:v1`, and the credential is an EdDSA JWT. Its public key must
be pinned by `kid` in the registration. Signed claims must match the registered issuer/principal,
request tenant, operation `composite-evidence.verify`, audience string `lotus-performance`, and
canonical request and payload digests. The `lotus-manage` audience is refused. Tokens require
integer `nbf`/`exp`, current validity, at most 300 seconds remaining lifetime, and a non-revoked
bounded `jti`; delegated actors and unrecognized header fields are refused.

Only `SYNTHETIC_NON_CERTIFYING` receipts are admitted. The retained lifecycle check additionally
requires equality with the original receipt: even a valid signature for a newly registered artifact
cannot replace the historical receipt on replay. The Manage configured signed source is an outbound
adapter, not an HTTP verifier endpoint supplied by this change.

## Transport and recovery

HTTPS is required except explicitly enabled HTTP loopback for synthetic tests. Redirects and
environment proxy inheritance are disabled. Configuration is limited to 256 KiB and 64 registrations,
with 1–30 second timeouts (default 5); responses have 16 KiB header and 64 KiB body bounds. Duplicate
JSON keys, invalid JSON, parser nesting exhaustion, unsuccessful HTTP status, oversized responses,
unavailable credentials, unknown scopes and signature or receipt mismatches return unavailable
evidence. The 2 KiB encoded token-header bound is checked before parsing that header; the 16 KiB
total token and 64 KiB response-body bounds still apply.

Investigate the configured scope and independently retained artifact before changing a registration.
For planned key rotation, configure the reviewed public key and key identifier; at most eight keys
are allowed per registration. Revoke compromised token identifiers through
`revoked_credential_ids`. Neither key rotation nor transport recovery authorizes changing retained
receipt identity. Restore the original authority binding or obtain an explicitly governed new
definition rather than rewriting historical evidence.

## Validation

Method/calendar admission alone does not make a published lifecycle executable. Policy, evaluation,
finalization and financial-source evidence use independent purposes through the same port. This
configured adapter deliberately supports only `RETURN_METHOD_CALENDAR`; missing peer registrations
remain unavailable. The registered worker control admits a signed method receipt, then blocks with
zero ready members when policy verification is absent. A successful method HTTP round trip must
not be reported as full lifecycle or institutional admission.

From the `lotus-performance` repository root, on Windows PowerShell or POSIX shells:

```text
python -m pytest tests/unit/adapters/test_composite_receipt_verifier.py tests/integration/test_composite_receipt_verifier_admission.py -q
```

The controlled tests cover independent artifact registration, exact signed claims, malformed and
oversized transport responses, default refusal, retained-receipt replacement refusal and an owned
loopback HTTP factory round trip with server shutdown. These are engineering proofs using synthetic
keys and artifacts; they do not qualify a real institution or external authority.
