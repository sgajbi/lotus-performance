# Lineage Volume Recovery

## Purpose

Use this runbook when the API or worker readiness reports that persisted lineage storage is
unreadable or unwritable after first deployment, restore, host migration, or restart. Restore the
governed non-root access contract without deleting lineage evidence or broadening permissions.

## Governed invariant

- shared volume: `performance-lineage-data`
- mount: `/app/lineage_data`
- workload identity: UID/GID `10001:10001` (`lotus`)
- directory mode after initialization: `0770`
- initializer: `performance-lineage-volume-init`
- workload dependency: `condition: service_completed_successfully`

The initializer runs as root only for bounded ownership repair. It uses a read-only root filesystem,
`no-new-privileges`, drops all capabilities, and adds only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`.
API and worker containers continue to run as non-root.

## Normal startup verification

```bash
docker compose up -d --build performance-analytics performance-lineage-worker performance-compute-executor
docker compose ps -a performance-lineage-volume-init performance-analytics performance-lineage-worker performance-compute-executor
docker compose logs performance-lineage-volume-init
```

Expected result:

1. `performance-lineage-volume-init` exits with code `0`;
2. API, lineage worker, and compute executor become healthy;
3. retained lineage artifacts remain readable;
4. new artifacts can be written by UID/GID `10001:10001`.

## Isolated release proof

```bash
make lineage-volume-recovery-smoke
```

The command creates a generated `lotus-performance-lineage-recovery-*` Compose project, builds the
production runtime target, seeds a root-owned `0755` volume with a retained marker, runs the bounded
initializer, verifies all three non-root workloads, restarts them, and verifies the marker plus
write access again. Its finalizer removes only that exact project's containers, volume, network, and
locally built images. A JSON summary with `status: passed` is the acceptance signal.

Do not reuse this disposable proof project name for a live deployment. The validator rejects names
outside its owned prefix so cleanup cannot target the canonical Compose project.

## Incident response

1. Preserve the named lineage volume and capture `docker compose ps -a` plus initializer logs.
2. Determine whether the failure is owner/mode verification, a read-only or unavailable mount,
   storage exhaustion, or a storage-driver/host-filesystem error.
3. Re-run the normal Compose `up` command so the bounded initializer executes before workloads.
4. Confirm workload health and retrieve a known retained lineage artifact before accepting recovery.
5. Record the deployment revision, volume identity, initializer exit code, owner/mode evidence, and
   affected calculation identifiers in the incident record.

Do not run `docker compose down -v`, delete the lineage directory, replace the volume, or apply
world-writable permissions as a recovery step. Those actions can destroy or weaken audit and
client-support evidence. Escalate persistent storage errors to the deployment or storage owner after
capturing the evidence above.
