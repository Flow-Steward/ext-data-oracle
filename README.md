# Oracle for Flow Steward

Flow Steward extension `flowsteward.oracle`, version **1.1.7**.

Connect Oracle records to Flow Steward for database lookups, reusable datasets and workflow updates. The extension provides a SELECT action with positional bind values and a separate write action for INSERT, UPDATE, DELETE and MERGE. Use these steps to look up a customer before routing a request, record the outcome of a workflow, or merge incoming records into an existing application table without inserting values into SQL text.

The read-only Dataset connector adds connection testing, schema discovery, query validation, previews, saved-query execution and output-schema inference. Saved Dataset queries select explicit columns from one allowed SCHEMA.TABLE, with comparison or null filters and ordering. Selected table and column permissions constrain the query, while Oracle user grants determine the underlying access.

Configure one Oracle service per project connection and enable writes explicitly when needed. Query results contain at most 100 rows. Dataset SQL excludes joins, subqueries, expressions and star projections; workflow SQL has a separate, restricted statement contract. Schema administration, PL/SQL, scripts, database links and cluster routing are outside the extension’s scope.

Create a project Oracle connection with host, port, service name, TLS settings and secret username/password; enable allow_writes for mutation steps. Public endpoints require verified TLS, and private endpoints require host administrator permission.

Project connection settings: `host`, `port` (1521), `service_name`, `tls` (true),
`allow_writes` (false), `request_timeout_seconds` (15, maximum 30). Secrets:
`username`, `password`. Public endpoints require verified TLS. Private endpoints
require the host administrator's `FS_ALLOW_PRIVATE_REMOTE_URLS` permission; TLS
may be disabled only for private addresses. Use a least-privilege Oracle user.
Listener redirects to a different host or port are rejected. DNS is resolved by
the host SDK and pinned to the original authority without changing the TLS name.

Inputs: `connection_ref`, `statement`, optional positional scalar `parameters`
(array; Oracle binds `:1`, `:2`, ...), and `max_rows` (query only, 1–100).
`SELECT :1 AS value FROM dual` with `["a literal value"]` demonstrates binding;
values never interpolate into SQL. SQL comments, alternate quoting, DB links,
locking and unapproved function calls are rejected. SELECT is intentionally
restricted; this is not a general SQL console. Parameters support null, strings,
signed 64-bit integers and finite floats; booleans/objects/arrays are rejected.
Reads are capped in SQL and iteration at 100 rows and an inline byte budget.
Writes require both connection opt-in and a durable host effect claim, are
suppressed in test mode, and are never retried automatically. An uncertain
post-dispatch write is reported as `timeout_unknown`, nonretryable.

Linux AMD64 and ARM64 packages each contain exactly one actual pure-Go ELF
Toolbox binary. Rebuild with `scripts/build_toolbox.sh` (Docker required), then
package each architecture using `python3 scripts/package_extension.py
--runtime-target linux-amd64` (or `linux-arm64`). Pinned source, patches and
binary checksums appear in `toolbox-provenance.json`.

Validation covers standalone contracts, safe SQL/binding, host effect phases,
network policy, native ELF/provenance and installer packaging. **No Oracle
credentials were supplied: a live Oracle connection, server SQL execution and
server TLS negotiation have not been verified.** Compile and contract evidence
must not be read as live integration evidence. The live test reports a skip.

Primary implementation references:
- [Google Toolbox Oracle source at the pinned commit](https://github.com/googleapis/mcp-toolbox/blob/06ea49d9a487a72c22419b5a8d5c22c11f0d7485/internal/sources/oracle/oracle.go)
- [go-ora v2.9.0 connector](https://github.com/sijms/go-ora/blob/v2.9.0/v2/connection.go)
- [go-ora TLS network implementation](https://github.com/sijms/go-ora/blob/v2.9.0/v2/network/session.go)

Dataset/Data Query support (1.1.0): the `oracle` dataset connector accepts the
host's resolved `connection_config` and `secret_refs` with the existing connection
schema. It supports connection testing, schema discovery, validation, preview,
saved-template execution and output-schema inference. The host authorizes and
resolves connection credentials before dispatch. Read-only Dataset/admin actions
accept its null execution scope without workflow account/project fields. Existing
workflow query/DML operations still require runtime account and project scope.
Dataset queries require matching saved-template and dataset IDs and an explicit resource allowlist of unquoted `SCHEMA.TABLE` names.
Column allowlists apply to every projected, filtered and ordered column; omitted
column lists permit all explicit columns for that resource.

The saved SQL subset is deliberately conservative: `SELECT ID, VALUE FROM
APP.THINGS WHERE ID=:id ORDER BY VALUE DESC`. One qualified table, explicit plain
columns, scalar comparison predicates combined with AND/OR, IS [NOT] NULL and
ORDER BY are supported. Aliases, expressions/functions/casts, quoted identifiers,
star projections, joins, subqueries, unions, comments and scripts are refused.
Named parameters declared as string/integer/number/null in `param_schema_jsonb`
are compiled into native positional Oracle binds without substituting values.
Boolean binds are not supported by this Oracle profile. Existing positional
workflow query and opted-in DML operations retain their original contracts.

Dataset execution is bounded to 100 rows, 400 KiB result data and the smaller of
the requested deadline and the connection timeout (maximum 30 seconds). Results
at a row cap are conservatively marked truncated. Empty results preserve the
saved output schema, or return explicit projected columns with null types when
no saved schema exists. Schema discovery reads at most 100 metadata columns and
32 selected tables under one deadline; cap hits are marked truncated (even when
the final metadata row happens to equal the cap). Initial discovery without a
dataset lists only the authenticated user's owner schema; subsequent discovery
uses only selected resources and columns. Oracle access remains governed by the
database user's grants. No live Oracle account was available for this change;
provider-fake contract tests do not prove live server behavior.

## Automated releases

CI runs on pull requests and pushes to `main`. Official releases run through the
pinned shared GitHub Actions workflow using `.github/release-config.json` to test,
package both Linux runtime targets, and publish the release assets automatically.
Manual ZIP uploads are not part of the release process.

After merging the version **1.1.7** update into `main`, create and push its tag:

```sh
git switch main
git pull --ff-only
git tag -a v1.1.7 -m "Release v1.1.7"
git push origin v1.1.7
```

To rerun the workflow for an existing tag without moving it:

```sh
gh workflow run release.yml --ref main -f tag=v1.1.7
```

The manifest remains the source for release identity and catalog descriptions.
The shared workflow installs the verified first-party SDK wheel before test
dependencies. Where native payloads are absent from source, the recipe restores
only the listed missing files from checksum-pinned published archives; the source
packager still verifies their provenance before packaging.

## Workflow action setup and examples

See [Workflow actions](docs/workflow-actions.md) for choosing Dataset reads versus explicit writes, connection requirements and copyable field examples.
