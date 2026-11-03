# Continuum Rework Navigation

Use this existing page as the documentation entry point. Start with the [release handoff](rework_release_handoff.md) for the checkpoint recorded in tracked documentation; an active frozen-source validation may have a newer restart block in the local workspace described below. The execution writer reconciles that progress into the final factual handoff.

| What you need | Read |
| --- | --- |
| Current checkpoint, remaining work and human-review questions | [Release handoff](rework_release_handoff.md) |
| Which document owns each decision | [Canonical plan stack](rework_plan_stack.md) |
| Approved scope and mandatory gates | [Milestone policy](rework_milestone_release_plan.md) |
| Current bounded execution and development pilot plans | The entries linked from the handoff and plan stack; files under `docs/superpowers/plans/` have their own scope and approval status |
| Runnable introduction and execution flow | [README walkthrough](../README.md#part-2-use-the-framework) and [runtime pipeline](runtime_execution_pipeline.md) |
| YAML syntax and semantics | [Configuration reference](configuration_reference.md) and [configuration design](configuration_restructuring_design.md) |
| Software module semantics | [Software architecture](software_module_architecture_plan.md) |
| Supported combinations and attributed evidence | [Certification matrix](release_certification_matrix.md) |
| Host execution, troubleshooting and test selection | [Host runbook](smoke_runner_isolation.md), [VM debugging](vm_debugging_runbook.md) and [testing strategy](operational_testing_strategy.md) |
| Configuration accounting and historical research scope | [Configuration inventory](configuration_inventory.md) and [reproduction inventory](reproduction_inventory.md) |

Historical phase plans describe completed implementation, not an active queue. Dated `release_evidence_*.md` files record different configurations or dates; they are historical evidence, not competing current plans. The post-release roadmap and overhaul dispatcher are retired. Preserve their provenance and use the current authorities above.

## Local artifacts outside the tracked documentation

These locations explain where agent and runtime files live; they are not additional documentation entry points. Git-ignored files and outside-repository directories are not transferred by a normal clone or automatically discovered by another thread. Share an explicit path only when the other thread has access to the same filesystem; another host needs an explicit transfer or its own corresponding artifacts.

| Location | Purpose and retention boundary |
| --- | --- |
| `.superpowers/sdd/<plan-name>/` | Ignored local execution workspace: restart log, task briefs, reviews, checks and staged patches. Use the latest restart block, not every historical brief. |
| `.superpowers/sdd/<plan-name>/future-plan-docs/` | Existing separate Git worktree for deferred documentation. It contains another checkout, so counting its Markdown again overstates the number of distinct plans. Its changes require integration by the execution writer. |
| `/tmp/continuum*` | Temporary helpers, reviews, staging, receipts and copied checkouts. Some active workflows pin these exact paths and hashes; a temporary filename does not establish that deletion is safe. |
| `/mnt/sdc/continuum_migration_evidence/` | Preserved migration and validation evidence, including command streams, JSON receipts, source copies and compact archives. These records are not a planning queue and must retain their attribution. |
| `/mnt/sdc/continuum_smoke/` | Local VM/runtime storage: disk images, configuration, logs and results. This is workload data, not a documentation archive. Other owners may have corresponding roots on other hosts. |
| `$CODEX_HOME` (normally `~/.codex/`) | Codex-wide instructions, configuration, sessions, plugins and caches across projects. Its contents are separate from Continuum documentation; do not clean authentication or session state as a repository cleanup. |

Prefer updating these existing entry points over adding another roadmap, report or tracker. New prose uses one physical line per paragraph; preserve structural Markdown and code formatting. Do not move or delete active or hash-bound artifacts merely to reduce file counts. Once their consuming workflows are closed, apply the [retention review guideline](smoke_runner_isolation.md#artifact-retention-review) rather than keeping every intermediate copy indefinitely. Historical file hashes and original line counts refer to their named commits or captured bytes; reflowing current prose does not renew their runtime evidence.

Support claims are owned by `docs/release_certification_matrix.md`; this page is navigation, not certification. No merge, push, tag, release or publication is authorized before final explicit approval. Static/parser success is not runtime certification.
