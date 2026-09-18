# Branch formatting and lint cleanup

Completed on 2026-09-18 against reviewed commit `f47b36a39b01dcca8fcf83d3f6c282aca07bdab6` on `codex/fns-2026-10-08`. The user reviewed and approved the cleanup for commit and push, accepting the remaining findings for the demo. This milestone is a completed formatting and lint review, not a zero-warning Pylint result.

## Scope and tools

The branch-creation reflog records `39022508131df910a2a92562e5528d234b34a7c9` as the starting point; first-parent history confirms it precedes the FNS commits. The later merge of main is `a6b772c`. The current main merge-base, `59c3ce0`, would include inherited text-translation code and omit some files changed since branch creation, so this pass uses the recorded branch starting point.

The initial workspace was clean. The base-to-reviewed-commit diff contains 52 surviving Python files: 32 image-batch files, 14 infrastructure files, three input/parser files, and the Continuum entry point, OpenFaaS module and Kubernetes resource manager. The new registry regression brings final validation to 53 files. Untouched files, generated output, captured evidence, dependencies and environments were excluded. Existing logs and validation captures were not modified.

Black 22.12.0 ran with `--line-length 100`, once per scoped file to avoid a stalled multiprocessing invocation. Pylint 3.3.9 ran from the repository root with `--rcfile=sysconfig/pylintrc --jobs=1 --source-roots=.,application/image_batch/src,application/image_batch/tests,infrastructure/tests`. Source and test directories were on PYTHONPATH. No lint rules or thresholds were changed globally. Tool packages were installed in a temporary directory without changing repository requirements or existing environments.

The user authorized alternative tool versions. Pylint 2.15.8 crashed while inspecting an existing enumerate start expression; 3.3.9 completed normally. Before/after counts below both use 3.3.9, after the initial Black pass. The forecast environment uses Python 3.10.12. The worker was additionally linted and imported in a separate environment with its pinned NumPy 1.26.4, Pillow 10.4.0 and TFLite runtime 2.14.0; that check reports only the same five missing-function-docstring findings.

## Changes and verification

Black formatting and wrapping long Python string literals preserve executable structure and emitted string contents. Cleanup removes seven unused imports, renames four unused bindings, makes six intentionally unchecked subprocess calls explicit with check=False, specifies UTF-8 for controlled text files, uses the public dataclass field API, simplifies a nested integer maximum and redundant return branches, and clarifies QEMU's required resource-manager lookup. Useful existing docstrings were retained; the new test and newly intentional exception are documented. No empty Args sections or redundant Returns: None sections were found in scoped docstrings.

One error-path defect was fixed: registry image selection now raises ValueError for an unsupported Kubernetes version instead of proceeding with undefined etcd/pause versions. A new mocked regression covers both kubecontrol and kube_kata; it reproduced the old UnboundLocalError before the fix and passes afterward. No new simulation workflow, capacity model, runner placement or packaging behavior was introduced. Removed checksum XML, JAR inventory, normalization script and version JSON remain removed.

Pre-commit verification exposed a test-only race in the process-group timeout regression: a terminated descendant could disappear between checking and reading its procfs status, raising ProcessLookupError. The test now reads directly and treats FileNotFoundError or ProcessLookupError as successful disappearance, while retaining the zombie-state check and failure for a surviving process. Independent review confirmed that the assertion remains effective. All five process tests passed five consecutive runs, and the complete 141-test image-batch suite then passed again.

- Black checks pass on all 53 files. All reported overlength Python lines were resolved.
- Complete image-batch discovery passes: 141 tests.
- Infrastructure discovery passes: 31 discovered, 27 passed and four opt-in skips. Three require an isolated network namespace; one requires the pinned MahiMahi source checkout.
- The four OpenDC-results tests pass after the final string-only edit; its executable AST is unchanged by that edit.
- git diff --check passes. Of the 52 pre-existing scoped files, 34 retain identical executable ASTs after excluding docstrings; the 18 files with executable changes were individually reviewed. An independent Superpowers review found no actionable defects.
- Pylint completes with zero errors and zero fatal findings, but exits 28: 338 convention messages, 91 refactoring suggestions and 39 warnings remain. The strict repository lint gate therefore does not pass.

The image-batch HTTP regression needed local socket permission outside the sandbox. No full Continuum deployment, VM provisioning, Kubernetes integration, container rebuild or full classifier inference was run: the behavioral fix is an invalid-input path covered by the mocked regression. No deployments, workloads or VM topology were changed.

## Finding types and disposition

Pylint findings decreased from 573 to 468, with 11 findings handled by narrow, explained exceptions. Remaining findings are retained visibly for review rather than suppressed to reach a score.

| Finding type | Before | After |
| --- | ---: | ---: |
| `missing-function-docstring` | 261 | 261 |
| `duplicate-code` | 37 | 37 |
| `wrong-import-position` | 37 | 37 |
| `missing-class-docstring` | 36 | 36 |
| `cell-var-from-loop` | 24 | 24 |
| `too-few-public-methods` | 18 | 18 |
| `use-dict-literal` | 16 | 16 |
| `unused-argument` | 11 | 10 |
| `too-many-positional-arguments` | 9 | 9 |
| `too-many-locals` | 5 | 5 |
| `unidiomatic-typecheck` | 4 | 4 |
| `attribute-defined-outside-init` | 2 | 2 |
| `too-many-boolean-expressions` | 2 | 2 |
| `too-many-return-statements` | 2 | 2 |
| `arguments-differ` | 1 | 1 |
| `protected-access` | 1 | 1 |
| `redefined-outer-name` | 1 | 1 |
| `too-many-arguments` | 1 | 1 |
| `too-many-statements` | 1 | 1 |
| `line-too-long` | 63 | 0 |
| `possibly-used-before-assignment` | 7 | 0 |
| `unused-import` | 7 | 0 |
| `subprocess-run-check` | 6 | 0 |
| `unused-variable` | 4 | 0 |
| `consider-using-with` | 3 | 0 |
| `unspecified-encoding` | 3 | 0 |
| `missing-module-docstring` | 2 | 0 |
| `no-member` | 2 | 0 |
| `used-before-assignment` | 2 | 0 |
| `f-string-without-interpolation` | 1 | 0 |
| `import-error` | 1 | 0 |
| `nested-min-max` | 1 | 0 |
| `no-else-return` | 1 | 0 |
| `wrong-import-order` | 1 | 0 |

Missing function/class documentation accounts for 297 remaining findings: 195 in tests and 102 in source. Existing useful documentation was preserved; this pass did not add repetitive docstrings to every test, fixture and existing helper. New functions/classes continue to follow AGENTS.md. The 37 import-position findings chiefly concern standalone scripts/tests that establish source paths. Duplicate-code findings include similar provider commands, trace schemas and independent test expectations; no shared abstraction was introduced solely to remove them.

Size/complexity findings were reviewed without decomposing coherent code: five local-variable warnings (31–66 versus 30), one statement-count warning (132 versus 120), one observer-signature warning (12 versus 10), nine positional-argument warnings from Pylint 3's new default of five, two boolean-expression warnings and two return-count warnings. No module-length warning was emitted. The 18 too-few-public-methods findings concern small data holders, submitters and test doubles; adding methods would not improve them.

The 24 loop-closure warnings occur in tests whose callbacks are consumed before the next iteration, with observer threads released and joined within each subtest. Ten unused arguments preserve callback/mock keyword contracts. Exact type checks intentionally reject booleans where an integer is required. Keyword-style dict construction, protected test access, fixture attributes, the HTTP log override and the replay helper's check parameter remain as reviewed low-value style/API findings.

Narrow exceptions cover asynchronous Popen submission (a context manager would wait), wait4-owned process reaping/resource collection, unittest-owned temporary-directory cleanup, Astroid's incorrect inference for ModuleNotFoundError.name, the working input.dsl namespace import, and six flow-inference warnings. The latter rely on nonempty prepared forecast examples and parsed Kubernetes worker configurations using cloud/edge modes. They do not introduce fallback values or new supported configurations.

## Suggested lint-policy follow-up

These are suggestions for a separate decision, not configuration changes made in this cleanup. Keep correctness checks and Black's 100-character formatting. Treat docstring rules for self-explanatory tests, too-few-public-methods for records/doubles, and duplicate-code for independent fixtures as candidates for targeted relaxation. With modern Pylint, consider aligning max-positional-arguments with the existing max-args=10. Keep the few larger production-function warnings advisory until a concrete maintenance need justifies refactoring. A mandatory 10/10 score would mostly force documentation boilerplate, additional suppressions and artificial abstractions here.

AGENTS.md describes proportionate cleanup and useful docstrings; its stale milestone link was updated and the ongoing priorities were made explicit. Improve documentation when modifying relevant functions and investigate new correctness findings during future implementation, without a blanket documentation pass or another lint milestone. The old Pylint pin should be considered separately in light of its observed crash and the repository's Python compatibility requirements. Markdown paragraphs remain unwrapped.

## Evidence

The [scope inventory](../../logs/fns-lint-cleanup/20260918T160104Z/scope.json), [baseline findings](../../logs/fns-lint-cleanup/20260918T160104Z/pylint-baseline.json), [final findings](../../logs/fns-lint-cleanup/20260918T160104Z/pylint-final.json), [worker findings](../../logs/fns-lint-cleanup/20260918T160104Z/pylint-worker.json), [image-batch log](../../logs/fns-lint-cleanup/20260918T160104Z/image-batch-final.log), [infrastructure log](../../logs/fns-lint-cleanup/20260918T160104Z/infrastructure-final.log), [Black log](../../logs/fns-lint-cleanup/20260918T160104Z/black-final.log), [AST inventory](../../logs/fns-lint-cleanup/20260918T160104Z/ast-review.json), and [test-before-fix reproduction](../../logs/fns-lint-cleanup/20260918T160104Z/registry-red.log) are stored in a new ignored validation directory. Earlier evidence directories remain intact.

The [pre-commit suite log](../../logs/fns-lint-cleanup/20260918T180827Z-precommit/image-batch-precommit-fixed.log), [five process-suite repetitions](../../logs/fns-lint-cleanup/20260918T180827Z-precommit/process-precommit-repeated.log), [initial race failure](../../logs/fns-lint-cleanup/20260918T180827Z-precommit/image-batch-precommit.log), and [pre-commit lint findings](../../logs/fns-lint-cleanup/20260918T180827Z-precommit/pylint-precommit.json) record the final test correction. Finding counts are unchanged.
