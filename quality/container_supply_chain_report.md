# Container Supply-Chain Evidence

Report date: 2026-06-30
Mode: PR/Main release evidence; vulnerability report is report-only until the baseline is accepted.

## Current Posture

`lotus-performance` now has repo-native container supply-chain evidence for the CI image:

```bash
make container-supply-chain-evidence
```

The target builds `lotus-performance:ci`, generates a CycloneDX SBOM, and writes a high/critical
container vulnerability report under `output/container-security/`.

Generated artifacts:

| Artifact | Purpose | Source control posture |
| --- | --- | --- |
| `output/container-security/lotus-performance-image-sbom.cdx.json` | CycloneDX SBOM for the CI image. | Ignored generated evidence; uploaded by PR/Main workflows. |
| `output/container-security/lotus-performance-image-vulnerabilities.json` | Trivy vulnerability report scoped to `HIGH,CRITICAL` and ignoring unfixed findings during the report-only baseline phase. | Ignored generated evidence; uploaded by PR/Main workflows. |

The PR Merge Gate and Main Releasability Gate publish those artifacts. Main Releasability also
attests SBOM provenance through GitHub artifact attestations using
`actions/attest-build-provenance@v3`.

## Exception And Promotion Policy

The report-only phase exists to avoid turning an unknown base-image baseline into noisy release
lane failures. Promote `make container-vulnerability-gate` to blocking when:

1. at least one PR and one main run have produced reviewed artifacts,
2. current high/critical findings are zero or explicitly accepted with owner, expiry, and
   remediation path,
3. the exception policy is recorded in this report and in the review ledger,
4. the blocking target is wired into PR Merge Gate and Main Releasability without
   `continue-on-error`.

Accepted exceptions must be narrow, time-bound, and tied to image package identity, severity,
CVE/advisory identifier, affected version, fixed version if available, and owner. Do not use a broad
scanner allowlist to hide unknown image risk.

## Security Tab Alignment

This slice benefits from GitHub Security features by publishing release artifacts that can be tied
to the repository's security evidence trail. Repository settings currently have secret scanning and
push protection enabled. Dependabot alerts/security updates are disabled, and CodeQL analysis still
needs a separate enablement or workflow/configuration slice.
