# Next Continuum Overhaul Agent

You are a bounded worker, not a planner. Read `.codex/OVERHAUL_EXECUTION_PLAN.md` first, then select exactly one task using the Agent scheduling policy.

Before editing, print:
- selected task ID and title
- recommended model class
- recommended reasoning effort
- whether your current model/effort is too weak, acceptable, or stronger than needed

If your model/effort is weaker than recommended, stop and tell the user exactly what to switch to. If stronger than needed, proceed but stay token-frugal.

Implement only the selected task. Do not broaden scope. Read only task-specific files first. Run targeted tests before broader tests. Update `.codex/OVERHAUL_EXECUTION_PLAN.md` with task status and compact handoff notes. Avoid huge output dumps.

## Copy-Paste Prompt

Read `.codex/OVERHAUL_EXECUTION_PLAN.md` and use its Agent scheduling policy to automatically select the next task. Print the selected task, recommended model class, reasoning effort, and whether your current model/effort is too weak, acceptable, or stronger than needed. If acceptable or stronger, implement only that task, run the targeted validation listed for it, update the plan status/handoff, and stop. Do not ask me to choose a task unless the plan is internally inconsistent or blocked by credentials/environment.
