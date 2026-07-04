# Documentation Pack

## Purpose

This pack contains the durable product, engineering, methodology, operation, RFC, and certification
truth for `lotus-performance`.

## Audience

- business, sales, and demo readers use guides and supported-feature material to understand current
  implementation-backed capability,
- operators use runbooks, standards, and certification evidence,
- engineers and agents use architecture, API, methodology, RFC, and docs-regression material.

## Reading Order

1. `../AGENTS.md` for the governed operating contract, mandatory reading order, skill routing, and
   wiki publication rule.
2. `../README.md`
3. `../REPOSITORY-ENGINEERING-CONTEXT.md`
4. `guides/api_reference.md`
5. `technical/runtime_topology.md`
6. `../../lotus-platform/context/PROCEDURAL-MEMORY-INDEX.md` when the task is mainly about
   execution method, PR loops, validation depth, or fix-forward work.
7. the relevant methodology, runbook, RFC, or endpoint certification file for the slice

## Major Areas

| Area | Use |
| --- | --- |
| `architecture/` | Review playbook, issue closure matrix, and codebase review ledger. |
| `guides/` | Human-facing API and product guides. |
| `methodologies/` | Calculation methodology and metric definitions. |
| `operations/` | Operator playbooks, alert explanations, and support workflows. |
| `runbooks/` | First-response and runtime operation procedures. |
| `standards/` | Repo-local engineering, runtime, security, and alert standards. |
| `technical/` | Architecture, endpoint certification, runtime topology, and evidence maps. |
| `RFCs/` | Local RFC history and implementation status. |
| `examples/` | Maintained request, response, environment, and compose examples. |

## Maintenance Notes

- Update docs in the same slice as implementation truth.
- Run `python -m pytest tests/unit/docs/test_public_docs_contract.py -q` when public docs, README,
  or wiki navigation changes.
- Do not bulk-edit historical RFCs unless the task is explicitly archival governance.
