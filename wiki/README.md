# Wiki Source Pack

## Purpose

This pack is the governed source for the `lotus-performance` GitHub wiki.

## Audience

- business, demo, operations, support, engineering, and agent readers who need a concise navigation
  layer over implementation-backed truth,
- maintainers publishing wiki updates after merge.

## Publication Rule

Repo-local `wiki/` is the authored source. The standalone GitHub wiki repository is publication
plumbing only.

Use:

```powershell
..\lotus-platform\automation\Sync-RepoWikis.ps1 -CheckOnly -Repository lotus-performance
```

After merge to `main`, publish changed wiki source with the platform wiki sync automation.

## Maintenance Notes

- Keep `Home.md` and `_Sidebar.md` reachable and professional.
- Do not duplicate long-form docs; link to `docs/`, contracts, commands, and evidence.
- Make current support, limitations, and ownership boundaries visible for business and operations
  readers.
