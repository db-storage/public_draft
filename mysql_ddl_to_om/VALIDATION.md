# Current validation: Git PR diff / full / security tags

Latest run on 2026-10-27: **116 passed, 1 skipped**, with 117 tests collected.

- Git mode uses real commits in temporary local Git repositories. Coverage includes PR merge-base comparison, direct base/head comparison, forced full generation, multiple databases, file additions/deletions/moves, table and column changes, rename manifests, formatting-only changes, identifiers containing dots/spaces/non-ASCII characters, cyclic foreign keys, COMMENT classifications/tags, and the CI shell entry point.
- The generator performs no OM GET or writes and connects to neither MySQL nor OM. The full SDK is not installed in the current environment, so official generated-model validation is skipped. Earlier model-validation records below are preserved and are not an end-to-end validation of the new service workflow.
- The diff/full CLI shares Git-snapshot reads, the original DDL converter, and `comment_annotations`. Output contains standard API bodies and an ordered CI request manifest; the manifest is not executed.
- Tests for the older `snapshot_sync` mode are also retained and pass. The recommended workflow is `pr_diff_to_om.py`; the older mode is not required.

---

## Earlier validation record

On 2026-10-17, the earlier full suite reported **84 passed**:

- 55 original conversion/API-mock/full-snapshot field-change tests, including the then-current OM 1.12.0.0 official generated-model validation.
- 29 lifecycle-snapshot tests using a stateful test double for creation, modification, deletion, restoration, table/column rename, annotation preservation, cyclic foreign keys, replanning after partial failure, old-table protection, empty snapshots, deletion thresholds, scope, pagination, version/plan changes, and CLI plan/apply.

Local versions: Python 3.12 and SQLGlot 27.29.0. Default installation uses only `requirements.txt`. Without the full SDK, official generated-model validation skips and the other 83 tests run independently.

Official model validation loaded generated.schema models from installed `openmetadata-ingestion` 1.12.0.0. The current compatibility target is OM 1.13.3; `test_om_1_13_3_sdk_models` requires `openmetadata-ingestion==1.13.3.0` when the SDK is installed. To avoid initialization failures from missing ingestion-runtime dependencies, the test process created only the metadata package path and loaded generated models directly. This does not alter production code and does not demonstrate that the entire ingestion runtime passed integration testing.

Source review covered OM 1.13.3-release `EntityRepository.restorePatchAttributes`, `TableRepository`, `TableResource`, and `DatabaseUtil`. PATCHing a table name does not preserve its entity ID as a rename, so the implementation uses explicit annotation migration and soft deletion. The test double also simulates server lowercase normalization of type displays and rejection of duplicate primary-key expressions.

No real MySQL/OM service was connected. MySQL is parsed offline and OM HTTP requests use mocks; server compatibility and permissions require validation in a test environment running the deployed version. No remote user writes were performed.
