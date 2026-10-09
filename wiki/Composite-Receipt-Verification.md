# Composite receipt verification

Performance can consume independently configured, signed synthetic return-method/calendar receipts.
The bounded deployment registration pins subject, full method binding, issuer, verifier, public
keys, endpoint and credential reference. Missing or invalid configuration returns unavailable.
No private signing key or outbound credential belongs in the configuration document.

Only `RETURN_METHOD_CALENDAR` and `SYNTHETIC_NON_CERTIFYING` are supported. Policy, evaluation,
finalization and financial-source verification remain independently required. The registered worker
test proves that method admission with a missing policy peer blocks with zero ready members.
This adapter does not establish production IAM, bank approval or GIPS qualification.

See the [deployment, transport and recovery guide](https://github.com/sgajbi/lotus-performance/blob/main/docs/guides/composite_receipt_verification.md)
and [synthetic configuration](https://github.com/sgajbi/lotus-performance/blob/main/docs/examples/composite_receipt_verifier.synthetic.json).
Retained replay requires the original receipt; key rotation cannot authorize replacing historical evidence.

[Composite Performance](Composite-Performance)
