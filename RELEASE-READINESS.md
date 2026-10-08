NOT READY

# TheBigDiffer release readiness audit

Audited on 2026-10-07 (America/New_York; execution continued into 2026-10-08 UTC).

The repository installs and builds as a standalone application, and its current validation
passes. Two reproduced correctness defects prevent an unconditional release: Git snapshots can
silently change directory-path identity on a case-insensitive filesystem, and any changed
binary file or symlink aborts patch preparation. These are production boundary defects, not
research questions. No production code, tests, fixtures, configuration, or validated investigator
behavior was changed during this audit.

This report assesses the checked-out commit and the artifacts built from it. It does not claim a
live Bedrock invocation, a vulnerability-free dependency set, or validation on every Python/OS
combination. All investigation probes were offline; real SDK credential-error probes used
isolated, deliberately absent credential/configuration files and disabled metadata lookup.
The historical research repository was not accessed or modified.

## Repository identity

| Item | Verified result |
| --- | --- |
| Requested repository | `/Users/damiancleary/Desktop/TheBigDiffer` |
| Initial `pwd` | `/Users/damiancleary/Desktop/thebigdiffer` |
| Canonical Git root | `/Users/damiancleary/Desktop/TheBigDiffer` |
| Audited commit | `4c10c56fad3d9715ad639ab9b2f6b838fe0f9103` |
| Commit subject | Initial standalone TheBigDiffer v2 production release |
| Branch | `main` |
| Tag | `v2.0.0`, pointing to the audited commit |
| Remote | `origin`: `https://github.com/dacman28/TheBigDiffer.git`, fetch and push |
| Initial status | Clean; local `main` reported up to date with `origin/main` |
| Final working-tree status | Only this new, untracked `RELEASE-READINESS.md`; no tracked-file changes |

The differently cased paths resolve to the same directory/inode on this filesystem; they are not
different repositories. The requested identity commands were run first: `pwd`, `git status`,
`git branch --show-current`, `git log --oneline --decorate -5`, `git tag -n`, and `git remote -v`.
Only the initial standalone commit appears in the local history. No remote fetch, branch,
commit, tag, or remote change was made. “Up to date” describes local remote-tracking state.

**SHOULD FIX BEFORE PUBLIC/TEAM RELEASE — S1:** The tag is `v2.0.0`, but both
`pyproject.toml:7` and `src/thebigdiffer/__init__.py:6` declare `0.2.0`. Distribution metadata
and built filenames consistently use `0.2.0`. Reconcile the release identity before publishing;
the audit does not assume whether the tag or package version should change.

Ignored local `.venv`, caches, build output, and egg metadata exist in the checkout. They are not
tracked production files and were not included in the release artifacts. Existing ignored
material was preserved. Audit environments, probes, and distributions were kept outside the
repository at `/private/tmp/thebigdiffer-release-audit.AZVyEX`.

## Standalone verification

The complete tracked production/test/configuration/documentation tree was inspected. The
requested literal search produced these occurrences in the audited source tree:

| Search term | Occurrences | Classification |
| --- | --- | --- |
| `research-prototype` | None | No dependency |
| `thebigdiffer-research` | None | No dependency |
| `M1`, `M2`, `M3`, `M4` | `ARCHITECTURE.md:154`, one occurrence of each | Documentation explicitly excludes the retired pipeline |
| `ApplicationMap` | `ARCHITECTURE.md:151` | Documentation explicitly excludes it |
| `security.deliberation` | None | No dependency |
| `trace.comprehension` | None | No dependency |
| `witness` | None | No dependency |
| `/Users/damiancleary` | None in tracked files before this audit report | No developer-home dependency |

The architecture occurrences are documentation outside `DESIGN-PROVENANCE.md`, not imports,
paths, or runtime/test dependencies. They describe exclusions; their placement is at most
documentation housekeeping.

A broader research/benchmark/archive/fixture scan was also reviewed:

- `DESIGN-PROVENANCE.md` and the golden fixture manifest contain immutable historical commit,
  tree, and prompt hashes. Tests compare those literal identities without querying another
  repository or resolving Git objects from the research archive.
- The 17 files under `tests/fixtures/autonomous-investigator-v1/` are the local derivative
  compatibility contract. They contain tiny source samples, scripted responses, expected
  requests/results/report, and identity metadata; they are not a research benchmark corpus.
- Provenance docstrings in context rendering, pricing loading, and patch presentation describe
  the frozen benchmark origin. They perform no research imports or file lookups.
- `research-report.md` is the current product's output filename. Its occurrences are active
  report persistence, documentation, and tests, not archived research reports.
- The pricing record's HTTPS URL is provenance text and is never fetched by the runtime.
- Production imports use the current product namespaces and the declared AWS SDK dependencies.
  No runtime lookup references `tests`, fixtures, a checkout-relative prompt, or a research tree.
  The four import-boundary tests pass.

Evidence beyond searches: a non-editable project install and a separate wheel install both
imported from their own `site-packages` while running outside the checkout; the sdist built the
wheel successfully; all 98 tests also passed from the extracted sdist. Nothing required access
to the historical repository.

## Installation and package build

Host: Darwin 25.2.0 arm64, CPython 3.12.10, Git 2.50.1 (Apple Git-155).
Two fresh virtual environments were created with `python3 -m venv` outside the checkout.

The initial `project-venv` verification used:

```bash
python -m pip install -U pip
python -m pip install .
```

Pip upgraded to 26.2.1. The sandbox initially blocked package-index DNS/network access;
the authorized network-enabled rerun succeeded. This was an audit-environment restriction,
not a package installation failure.

Before any editable installation, an isolated import from the temporary working directory
resolved to:

```text
/private/tmp/thebigdiffer-release-audit.AZVyEX/project-venv/lib/python3.12/site-packages/thebigdiffer/__init__.py
```

`thebigdiffer --help` and `thebigdiffer investigate --help` succeeded. `pip check` found no
broken requirements. Only after that verification, `pip install -e '.[dev]' build` installed
the README's documented development extra and the separate audit build tool. Thus the initial
non-editable installation was actually tested; it was not inferred from an editable install.

Build command, using the temporary environment's interpreter:

```bash
python -m build --outdir /private/tmp/thebigdiffer-release-audit.AZVyEX/dist
```

`build==1.6.1` used isolated `setuptools==84.0.0` environments. Its default workflow built
the sdist and then built the wheel **from that sdist**.

| Artifact | Size | Files | SHA-256 |
| --- | ---: | ---: | --- |
| `thebigdiffer-0.2.0-py3-none-any.whl` | 48,584 bytes (47.45 KiB) | 43 | `9d0b235d43262d1e464917c74b7043bb5d6f0ada2c854730cce0f0aea8e664ec` |
| `thebigdiffer-0.2.0.tar.gz` | 73,352 bytes (71.63 KiB) | 80 | `a4628fa31a3105d0d0a22a97804394bcdc5043a5fd50f291590ee83dca1a84c6` |

The wheel was installed, with its declared dependencies, into the independent clean
`wheel-venv`. From outside the checkout, both ordinary `python -c` and isolated `python -I -c`
imports resolved to:

```text
/private/tmp/thebigdiffer-release-audit.AZVyEX/wheel-venv/lib/python3.12/site-packages/thebigdiffer/__init__.py
```

The wheel's `thebigdiffer --help` passed, as did `pip check`. The wheel-installed CLI and
investigator were used for the offline operator probes below.

Both resources exist and load in that environment:

- `thebigdiffer.investigator.prompts/primary-v1.txt`, loaded with
  `importlib.resources.files` in `investigator/prompt.py`. Its verified SHA-256 is
  `f2973b032a0a76e1aed537e2975cc861941f40a7a95bf88d5d0435da3dd347ab`.
- `thebigdiffer.investigator.pricing/opus-4.6-bedrock-2026-05-12.json`, loaded with
  `importlib.resources.files` in `investigator/accounting.py`. The loader returned the expected
  pricing record for `us.anthropic.claude-opus-4-6-v1`.

Neither resource loader relies on a checkout-relative path. All 38 package files in each
artifact equal the corresponding checkout bytes.

Every file is listed in the artifact inventories at the end of this report. Member-name and
payload inspection found no `.git`, caches, build directories, research reports/corpora,
retired pipeline implementation, scratch scripts, virtual environments, credentials,
developer-home paths, or generated investigation output. The sdist's `.egg-info` and
`setup.cfg` are standard packaging metadata. Its fixture `expected-report.md` is a small
golden test expectation, not an archived research report. The wheel includes only runtime
package files and distribution metadata.

Pattern scans found no AWS access-key identifiers, private-key blocks, GitHub/API token shapes,
or developer-home absolute paths. Manual review found no real-looking sample secrets.
These checks are evidence of absence in the audited material, not a guarantee against every
possible secret encoding.

## Test/static-analysis results

The established README commands were run with the temporary development environment:

| Validation | Result |
| --- | --- |
| `python -m pytest -q` | PASS: all 98 collected tests; no failures or skips |
| `python -m pytest -q tests/test_golden_parity.py` | PASS: 5 golden tests |
| `ruff check --no-cache src tests` | PASS: All checks passed |
| `mypy --strict src` | PASS: no issues in 36 source files |
| Extracted-sdist `python -m pytest -q -o addopts=''` | PASS: 98 passed in 8.25s |
| Initial project install / wheel `pip check` | PASS |

Tool versions: pytest 9.1.1, Ruff 0.16.10, mypy 2.4.0.

The exact count is **98 total, including 5 golden tests**, therefore 93 other tests.
Running golden parity separately reruns those five; it does not make the suite 103 tests.
There were no added/deleted tests or changed assertions. Collected counts by module are:

| Module | Count |
| --- | ---: |
| `test_cli.py` | 14 |
| `test_context_patch.py` | 6 |
| `test_git_input_equivalence.py` | 1 |
| `test_git_repository.py` | 16 |
| `test_golden_parity.py` | 5 |
| `test_import_boundaries.py` | 4 |
| `test_ingest.py` | 12 |
| `test_investigator_accounting.py` | 9 |
| `test_investigator_prompt.py` | 1 |
| `test_investigator_runtime.py` | 4 |
| `test_provenance.py` | 2 |
| `test_source_repository.py` | 24 |

The five golden tests cover fixture identity/hashes; exact prompt, context, patch, and tool
contract; source-tool results; spending admission/accounting; and the complete scripted primary
runtime request/transcript/report contract. Git/directory model-visible equivalence also passes.

The two blockers below are gaps in current regression coverage. Existing Git collision coverage
checks whole file-path collisions, not collisions between directory prefixes. Patch coverage
does not exercise a changed binary or symlink through a complete investigation.

## CLI assessment

Both documented source modes were exercised through the wheel-installed `cli.main` with an
offline provider substituted at the provider-construction boundary. No production defaults,
budgets, tool behavior, or investigator implementation were modified.

Directory and Git modes both returned 0 for an ordinary text patch and wrote all ten expected
artifacts. The Git probe deliberately dirtied a tracked file and added an untracked file;
the resulting patch equaled the prepared-directory patch byte for byte. Real process invocations
also exercised help, import, and SDK credential failures.

| Operator case | Observed result |
| --- | --- |
| Top-level and investigate help | Exit 0; concise flag descriptions |
| No command / missing context or output | Argparse exit 2, names missing arguments, no traceback |
| No source flags | Exit 2, lists both supported modes |
| Partial directory flags | Exit 2, requires both `--before` and `--after` |
| Partial Git flags | Exit 2, names all three required Git flags |
| Mixed source modes | Exit 2, explicitly requires exactly one mode |
| Missing source directory | Exit 2, safe-ingest error, no traceback; does not identify before vs after |
| Nonexistent Git repository | Exit 2, `Git preparation failed` plus path error |
| Directory that is not a repository | Exit 2, `not a usable local Git repository` |
| Nonexistent ref | Exit 2, names the ref that does not resolve to a commit |
| Missing/malformed/invalid context | Exit 2, useful file, JSON-position, key-set, or field error |
| Existing output | Exit 2, `File exists` with path; no overwrite |
| Output inside source, or source inside output | Exit 2, explicit overlap rejection |
| Output inside Git repository | Exit 2, explicit overlap rejection |
| Git executable/object/preparation failure | Existing typed-error tests pass; invalid repository/ref probes are concise |
| Provider exception during Converse | Exit 2, `model_transport_error_no_retry`; one attempt, persisted audit trail |
| Provider `max_tokens` | Exit 2, `model_max_tokens`; partial report retained |
| Provider keeps requesting tools at the model limit | Exit 2 after the default 12 invocations; `budget_exhausted_model_requested_more_tools` |
| No AWS credentials | Exit 2, generic transport-error stop; `NoCredentialsError: Unable to locate credentials` only in transcript |
| Nonexistent `AWS_PROFILE` | **Exit 1 with full `ProfileNotFound` traceback**, before output creation |
| Only an AWS access-key identifier configured | **Exit 1 with full `PartialCredentialsError` traceback**, before output creation |
| Added binary / symlink | **Exit 2 before provider invocation or output creation**; blocker B2 |

Normal parser and input-validation mistakes are mostly understandable without tracebacks.
`--help` does not describe the four context fields, source-mode grouping requirements,
AWS prerequisites, or the output reading order. README provides some of that information.

**SHOULD FIX BEFORE PUBLIC/TEAM RELEASE — S2:** Handle expected SDK construction/configuration
failures at the CLI boundary and show an actionable error. `cli.py:99` constructs the provider,
but `cli.py:109` catches only `IngestionError`, `OSError`, and `ValueError`. Neither
`ProfileNotFound` nor `PartialCredentialsError` is covered. For absent credentials during
Converse, make the persisted error discoverable from the CLI without changing transcript or
provider semantics. Provider construction also precedes ingest/output validation, so AWS
configuration failures can mask local input mistakes.

Git temporary snapshots were verified to be removed after an exception; successful cleanup and
Git/directory equivalence are covered by the current suite. Filesystem failures while creating
the temporary workspace or regular Git snapshot files are not uniformly wrapped as
`GitPreparationError`; the outer Git CLI catch only handles that type. This is an additional
diagnostic gap in the same CLI-boundary work, established by code inspection.

## Context UX assessment

`ApplicationContext.load` in `context/model.py` accepts a UTF-8 JSON object with exactly four
keys. Every key is required in the JSON file, including `provenance`, even though the Python
dataclass constructor supplies a default for that one field.

| Field | Required in JSON | Value |
| --- | --- | --- |
| `repository_type` | Yes | Non-empty string describing the repository |
| `application_context` | Yes | Non-empty string of factual application context |
| `deployment_context` | Yes | Non-empty string; README demonstrates `"Unknown."` |
| `provenance` | Yes | Non-empty string describing the supplied context's provenance |

No additional keys are accepted. Each raw string must be at most 4,000 Python characters
and contain at least one non-whitespace character. Non-string values, blank strings, and
oversized fields are rejected. Leading/trailing whitespace is preserved in the stored values
but stripped from the three factual fields in model-visible rendering. Provenance is recorded
separately and is not added to that rendering. JSON duplicate keys receive the standard
`json.loads` last-value behavior; no special duplicate-key rejection exists.

The README's complete four-field example is sufficient to construct a valid initial file.
There is no dedicated user-facing example context file. A usable input example does exist at
`tests/fixtures/autonomous-investigator-v1/application-context.json`. The identically named
output artifact is a context **record** with wrapper/identity information, not the raw four-key
input object, and cannot simply be passed back as `--context`.

Error probes confirmed useful diagnostics for JSON syntax (line/column), top-level arrays,
missing/extra keys, wrong value types, blank fields, and excessive length. Missing/extra-key
errors list the allowed set but do not identify the specific discrepancy.

Correctness assessment: validation matches the documented example; no context correctness
blocker was found. UX backlog: document limits and unknown deployment facts, provide a plainly
named input example, distinguish input JSON from the persisted context record, and improve
missing/extra-key detail. Do not infer context automatically or alter the model-visible rendering.

## Output artifact assessment

The success, transport-failure, model-output-limit, model-budget-limit, and absent-credential
probes each produced the same ten stable filenames once investigation initialization completed:

| Artifact | Intended reader / purpose |
| --- | --- |
| `research-report.md` | Human first read: model report or incomplete fallback |
| `metrics.json` | Machine status, stop reason, usage, estimated cost, hashes, finish time |
| `transcript.json` | Full machine audit trail, exact requests/responses, tools, errors, final status |
| `investigation-manifest.json` | Model, prompt, configuration, pricing and source identities |
| `application-context.json` | Recorded input context and its identity |
| `patch-presentation.txt` | Exact model-visible source comparison |
| `primary-prompt.txt` | Exact prompt text |
| `tool-definitions.json` | Exact model-visible tool contract |
| `source-inventory.json` | BEFORE/AFTER files, hashes, classifications and diagnostics |
| `source-preparation.json` | Directory/Git preparation mode and manifest identity |

Human reading order should be `research-report.md` **with** `metrics.json.stop_reason`.
`model_end_turn` denotes model completion, not a guarantee of a correct security conclusion.

Completion is explicit in metrics/transcript and the process exit status. Success itself prints
no CLI message or report path. Provider failure is explicit as a nonzero CLI status and fallback
report; the actual exception detail lives in transcript events. Model/prompt identity and full
configuration are recorded in the manifest/transcript, with prompt hashes also in metrics.

Budget exhaustion is explicit in metrics/transcript and CLI stderr. It is **not reliably obvious
from the Markdown report alone**: the 12-call probe wrote only `Partial evidence only.`, while
metrics recorded `budget_exhausted_model_requested_more_tools`. Similarly, a `max_tokens`
response can leave apparently ordinary prose in `research-report.md`. Existing report semantics
preserve that model text; this audit did not change them.

Directory preparation records the mode and deterministic manifest hash; source inventories
supply content identities. Git preparation additionally records canonical repository/Git
directory paths, supplied refs, commits, trees, Git version/object format, entry provenance,
counts, limits, and preparation semantics. This metadata is not added to model messages.
Directory provenance does not record original absolute source-root paths, by current design.

The final report is easy to locate once its filename is known. Filenames are stable and
descriptive, although “research” in `research-report.md` reflects the current report contract.
Writes use temporary files and atomic replacement. Pre-investigation failures (including B2 and
SDK construction failures) do not produce the ten-file directory; process interruption or disk
failure is not a guarantee of a finalized report.

**SHOULD FIX BEFORE PUBLIC/TEAM RELEASE — S5:** Document the artifact names, reading order,
status interpretation, and error-detail location, and provide a CLI completion/status/path
summary without changing report contents. Warn that raw source, context, responses, and errors
are retained. Do not infer completeness from the existence of the Markdown file.

## Security boundary review

| Boundary | Evidence and assessment |
| --- | --- |
| Target code is never executed | Source is read, hashed, parsed with AST/tokenization, searched, and diffed. No target import/eval/exec, shell tool, or test runner exists in production. |
| Target dependencies/build scripts are never run | No target package installation or target build execution path. The audit's pip/build commands built only TheBigDiffer itself. |
| Source-tree symlinks are not followed | Descriptor-relative `O_NOFOLLOW` traversal, root/type checks, symlink inventory records, and source membership/hash validation; symlink/root/escape tests pass. B2 is refusal of a changed symlink, not traversal of its target. |
| Git hooks and external transformations | Git argv sets `core.hooksPath=os.devnull` and `core.fsmonitor=false`. Only version/rev-parse/cat-file/ls-tree operations are used; no checkout, archive, filters, LFS, or submodule initialization. |
| Working-tree source ignored | Dirty/untracked tests and wheel-installed Git-vs-directory patch equality pass. Local Git metadata/configuration still identifies the repository; the claim concerns source bytes. |
| No remote Git acquisition | No clone/fetch command; inherited `GIT_*` variables are removed; `GIT_NO_LAZY_FETCH=1` disables lazy acquisition on the audited Git. The installed Git binary supports that variable. Missing objects fail. Older Git versions were not tested or constrained. |
| Provider tool arguments validated | Explicit name allowlist, exact required/optional keys, type/version/identifier/path/range checks, result limits and cumulative byte charging. Malformed-argument and tool-contract tests pass. |
| Path confinement | Relative paths normalized; traversal/absolute/drive paths rejected; inventoried membership and content hashes checked; reads traverse no-follow descriptors. Existing escape/change tests pass. |
| External URLs | No URL-following source tool or target-controlled network acquisition exists. Pricing URLs are inert metadata. Bedrock and the SDK's trusted operator credential/endpoint configuration are the intended networking boundary. |
| Exact Git path identity | **FAIL, B1:** directory-prefix case collisions are not detected; snapshot paths can silently differ from the Git tree. |
| Complete unsupported-file handling | **FAIL, B2:** changed non-text entries abort the entire patch before their intended omission record. |

No accidental target-code execution surface was found. Trusted installed executables, SDK
configuration, and the user's own credential providers remain outside the target-source trust
boundary. The runtime is not a sandbox for malicious local processes sharing the user's account.

Source tools enforce returned-source limits, but these are not general CPU/memory/time limits
for all parsing and diff preparation. Git subprocesses have no explicit timeout. The declared
ingest/Git size limits remain unchanged; resource-stress coverage is a product backlog item.

The documented claim that case/Unicode collisions are rejected is broader than the actual path
validation. B1 must be resolved with regression coverage while preserving exact snapshot
semantics. Full-path collision tests alone are insufficient.

## Configuration/credential handling

Production CLI configuration comes directly from `InvestigationConfig()`:

| Configuration | Current behavior |
| --- | --- |
| Model ID | `us.anthropic.claude-opus-4-6-v1`; the configuration rejects other model IDs |
| AWS region | Explicit `us-east-1` passed to the client; no CLI region flag |
| Model/tool limits | 12 invocations, 30 tool requests, 200 lines/response |
| Source/evidence limits | 128 KiB retrieved source; 256 KiB initial evidence setting |
| Model response | 4,096 output-token setting, temperature 0 |
| Local estimated spending ceiling | USD 2.00; explicitly not an AWS billing guarantee |
| Search | 20 matches, 2 context lines |
| Provider transport | 10-second connection / 600-second read timeout; one total attempt |
| Pricing | Frozen packaged pricing record, with effective/verification dates and provenance |

These are observations, not proposed changes. No model/budget/accounting/provider defaults were
modified. Region is an explicit programmatic field; the CLI uses the fixed default rather than
taking region from normal AWS region environment settings.

Authentication uses `boto3.client` and the SDK's normal credential resolution chain. The
application supplies no access-key/secret fields, stores no custom credential files, and has no
credential manager. Standard SDK profiles, environment, role/SSO/login providers, and their
trusted configuration belong to the SDK, not a custom TheBigDiffer scheme.

No committed credentials or real-looking samples were found in the complete tracked tree or
artifacts. SDK client/credential objects, signing headers, and environment-variable contents are
not serialized by the application. The missing-credential probe made no authenticated service
call and recorded `NoCredentialsError` without retry; S2 covers its poor terminal diagnostic
and the construction-time tracebacks.

A blanket statement that artifacts “cannot contain secrets” would be incorrect. The application
intentionally persists raw context, patch/source snippets, provider responses, and `str(error)`;
it has no redaction layer. A synthetic error marker was reproduced verbatim in the transcript.
Secrets supplied in those inputs or included in an upstream exception could therefore be
retained. On the audited umask, output directories/files were 0755/0644 inside the audit's private
temporary parent. A normal output location inherits the operator's parent permissions/umask;
TheBigDiffer does not force private permissions. S5 includes documenting this boundary and using
a private output parent. Changing transcript/redaction semantics is outside this audit.

Actual AWS account permissions, Bedrock model entitlement, live transport, and current billing
were not tested. No real AWS credentials were inspected or used. The frozen pricing record was
verified for packaging/parity, not re-priced or replaced.

## Dependency inventory

| Declaration | Actual production consumer | Classification |
| --- | --- | --- |
| `boto3>=1.43,<2` | `providers/bedrock.py:7,16` creates the Bedrock Runtime client and calls Converse | Required runtime |
| `botocore[crt]>=1.43,<1.44` | `providers/bedrock.py:8,19` uses `Config` for transport/retry settings; boto3 depends on botocore | Required runtime |
| `crt` extra within botocore | Installs `awscrt`; the SDK login credential provider explicitly requires CRT EC support | Conditional runtime capability, intentionally installed by the required dependency; not proven unnecessary |
| `mypy>=1.11` in `dev` | Strict static checking | Development only |
| `pytest>=8` in `dev` | Production and golden tests | Development only |
| `ruff>=0.7` in `dev` | Linting/import/style checks | Development only |
| `setuptools>=75` | PEP 517 build backend | Build only |

The resolved runtime set was boto3 1.43.109, botocore 1.43.109, awscrt 0.36.0,
jmespath 1.1.0, s3transfer 0.19.2, python-dateutil 2.9.0.post0, urllib3 2.8.0, and six 1.17.0.
The last six are transitive dependencies, not additional direct project declarations.
There is no optional alternate-provider dependency and no direct runtime dependency proven
unused. No dependency was removed.

The CRT consumer was confirmed in the installed `botocore/credentials.py`
`LoginProvider.load`, which raises `MissingDependencyException` for a configured login session
without CRT support. Absence of an `import awscrt` in project code is therefore insufficient
reason to remove that extra.

`requires-python = ">=3.11"` agrees with the README, Ruff's `py311` target, strict mypy's
`python_version = "3.11"`, and the use of `datetime.UTC`/modern typing. Resolved boto3/botocore
require Python >=3.10 and awscrt >=3.8, so there is no metadata contradiction with the project's
floor. The resolved development tools also allow Python 3.11. Only Python 3.12.10 was executed
in this audit; the open-ended Python range is not a tested compatibility matrix.

The boto3 lower bound is broader than the explicitly bounded botocore series, but the resolver
found a compatible pair and `pip check` passed. A lock/constraints policy and automated update
checks are useful release-process backlog; no vulnerability advisory audit was performed.

## Documentation assessment

All of `README.md`, `ARCHITECTURE.md`, and `DESIGN-PROVENANCE.md` were read.

| A new user needs to know | Assessment |
| --- | --- |
| What it does | Clear: autonomous source-grounded patch security investigation |
| What it does not do | Strong architecture/exclusion/security description |
| Installation requirements | Python floor and development install exist; normal non-editable install and executable activation are missing |
| AWS/Bedrock requirements | Credential-chain statement exists; exact region/model ID and operational setup are insufficient |
| Context format | Complete valid example; length/type rules and reusable standalone example are missing |
| Directory usage | Complete example and output separation requirement |
| Git-ref usage | Complete local-only example; explicit refs, raw object semantics, cleanup described |
| Output location/artifacts | Output flag and categories described; exact filenames, status checks, and first-read file are missing |
| Security boundaries | Clearly described; collision claim needs B1 correction, and raw artifact confidentiality needs explanation |
| Current limitations | Local-only Git/no fallback/no retries described; platform requirements, Python-only definition/reference tools, binary-change failure, and status-reading limitations need explicit treatment |

**SHOULD FIX BEFORE PUBLIC/TEAM RELEASE — S3:** The install section invokes `.venv/bin/pip`,
but later examples invoke bare `thebigdiffer` without activating the virtual environment or
using `.venv/bin/thebigdiffer`. A user following the commands literally in a fresh shell need
not have the executable on PATH. Add a normal install path and a consistent executable path.
Explain the current AWS region/model/profile and access prerequisites without changing them.

**SHOULD FIX BEFORE PUBLIC/TEAM RELEASE — S4:** Document the required filesystem capabilities
and Git availability/version policy. Python >=3.11 alone does not establish that safe ingest
is supported. Git hardening depends on supported plumbing/options/environment controls.

For public distribution, no license file or `project.license` is present, and `project.readme`
is not declared (the sdist has README, while wheel metadata lacks the long description).
Deciding public distribution metadata/license is S6, separate from runtime correctness.

`DESIGN-PROVENANCE.md` is concise, records the lineage and immutable identities, and correctly
keeps the research archive outside the deployable project. There is no reason to expand README
into a research history.

## Portability findings

- **B1, reproduced on this case-insensitive macOS filesystem:** prefix collisions such as
  `A/one.py` and `a/two.py` merge into one directory. Whole-path normalization/casefold checking
  misses the prefixes. This is a bug, not an intentional platform requirement.
- Safe ingestion intentionally requires `O_NOFOLLOW`, `O_DIRECTORY`, directory-relative
  `open/readlink`, and descriptor-based `scandir`. `_secure_traversal_supported` fails closed
  if they are unavailable. This is a security requirement, but the support policy is undocumented.
- Git snapshot materialization uses descriptor-relative mkdir/open/symlink/unlink and `fchmod`.
  There is no early Git-specific platform capability check; unsupported operation errors can
  occur before the later safe-ingest check. macOS was exercised; Linux and Windows were not.
- Tests use temporary directories rather than a fixed scratch root. Production uses `tempfile`;
  there is no hard-coded `/tmp` storage requirement. The `/tmp/secret.py` and `C:/x.py` strings
  in source-tool tests are intentionally rejected unsafe paths.
- `/etc/passwd` in the Git symlink test is inert link-target text; its contents are not read.
  `/dev/null` in a unified diff is a format marker. Git hardening uses portable `os.devnull`.
  `#!/bin/sh` fixtures and shebang detection are text/metadata, not shell execution.
- `expanduser` operates on caller-supplied paths. There is no developer-home lookup or
  hard-coded home path in runtime/tests/configuration. Standard AWS provider home/config
  resolution is intentionally delegated to the SDK.
- Runtime subprocesses use argv lists, not a shell. Git is found through `shutil.which`;
  no developer-local Git executable is hard-coded. Source labels use normalized slash paths;
  backslash and drive handling are deliberate confinement checks.
- Import-boundary tests use `Path(__file__)` and `PYTHONPATH` relative to this project's own
  `src` tree. Golden tests locate their own packaged fixture directory. These are local test
  dependencies, never runtime resource dependencies.
- Git tests create local repositories using the host Git. Their fixture setup does not isolate
  every global Git setting (for example signing/template/hooks defaults), even though production
  Git commands disable global/system config. Making test setup hermetic is product backlog.
- No fixed Linux-only runtime path was found. README's `.venv/bin` commands assume a POSIX shell/
  venv layout. Document that intentional operational requirement and test the supported matrix.

## Release blockers

**BLOCKER — B1: Git snapshot directory-prefix collisions silently change source identity.**

Location: `src/thebigdiffer/repository/git.py:527` (`_validate_entry_paths`) and `:560`
(`_open_parent`).

Reproduction used only a temporary local repository and Git object plumbing. Two different
subtrees were constructed with `hash-object`, `mktree`, and `commit-tree` so the commit contained
both `A/one.py` and `a/two.py` despite the host's case-insensitive working filesystem.
`GitRepositoryPreparer(repo, commit, commit).prepare()` returned successfully.

| View | Paths |
| --- | --- |
| Committed Git tree / preparation entries | `A/one.py`, `a/two.py` |
| Materialized files / ingest inventory | `A/one.py`, `A/two.py` |
| Preparation result | `materialization_status: complete` |

The validator casefolds complete leaf paths, which differ, but never checks normalized
directory-prefix identity. `_open_parent` accepts the existing directory when creating the
differently cased parent. File bytes survive, but paths and therefore source provenance do not.
This violates raw committed-tree semantics and the architecture's collision-rejection promise.
The same validation gap warrants Unicode-normalized prefix and file/parent-alias regression
cases; only the case-prefix example above was reproduced dynamically.

Before release, reject conflicting normalized prefixes before any materialization and add
focused regression coverage. Do not silently rename paths, relax the source trust boundary, or
change Git snapshot semantics. No fix was applied in this audit.

**BLOCKER — B2: Changed binary files and symlinks prevent investigation of an otherwise valid patch.**

Location: `src/thebigdiffer/patch/presentation.py:50`, particularly the text reads at `:53`
before the eligibility check at `:55`.

Reproduction: BEFORE contains `app.py` with `value = 1`; AFTER contains `app.py` with
`value = 2` and an added `image.bin` containing bytes `00 ff 10`. The wheel-installed directory
CLI, using a fake provider, returned:

```text
thebigdiffer: path is not inventoried text source: image.bin (binary)
exit status: 2
provider calls: 0
output directory created: false
```

An added `app-link.py -> app.py` likewise returned `path is not inventoried text source:
app-link.py (symlink)`. An unchanged identical binary in both trees allowed the text patch to
complete, confirming the trigger is the changed entry.

The function calls `_text`/`_verified_text` before deciding whether a change is text-eligible.
Those reads reject non-text records, so the intended `non_text_change` branch is unreachable
for the cases it is meant to handle. The issue applies to either source mode because they share
the same patch boundary. Added/modified/removed binary or symlink cases need regression tests,
along with mixed text/non-text changes.

No fix was applied: changing this path affects the explicitly protected patch presentation,
and this audit does not approve a new model-visible representation. A follow-up can preserve
the already defined non-text record while proving existing golden parity unchanged.

**SHOULD FIX BEFORE PUBLIC/TEAM RELEASE** (distinct from the two correctness blockers):

| ID | Item |
| --- | --- |
| S1 | Reconcile `v2.0.0` tag with `0.2.0` package metadata |
| S2 | Friendly provider-startup/credential and Git filesystem diagnostics; actionable error location |
| S3 | Normal installation/venv executable instructions and concrete existing AWS setup requirements |
| S4 | Explicit OS/filesystem and Git prerequisites/support policy |
| S5 | Artifact index, completion/status reading instructions, raw-data confidentiality and private-output guidance |
| S6 | Decide public distribution license/metadata; declare package README before public package publication |

These findings do not justify changing the primary prompt, context rendering, source-tool
schemas/behavior, Claude defaults, budgets/accounting, provider behavior, or transcript/report/
Git semantics. No speculative fixes were made.

## Recommended product backlog

**PRODUCT BACKLOG**, after the release blockers and should-fix items:

1. Add a clearly named user input context example; document field bounds and distinguish input
   JSON from output context records; improve missing/extra-field detail without changing rendering.
2. Automate wheel/sdist builds, isolated wheel imports/resource checks, and existing validation
   across the declared supported Python/OS matrix.
3. Isolate Git fixture setup from developer global configuration and add the two missing boundary
   regression families described above when implementing their approved fixes.
4. Establish dependency/build-tool constraints or update validation so future releases record
   the resolved environment; document the CRT credential-chain consumer.
5. Add resource-stress coverage for large patches/trees and hung Git subprocesses before proposing
   any operational-limit changes. Preserve current budgets and model-visible behavior.
6. Consolidate retired architecture names into provenance documentation if desired; no research
   code or corpus removal is needed in this standalone repository.

**RESEARCH QUESTION:** No new research question must be answered to decide this audit's verdict.
The two blockers concern deterministic product correctness. Any future change to validated
investigator decisions, model-visible evidence, prompts, tools, budgets/accounting, or report/
transcript meaning requires a separate controlled evaluation; it is not part of this backlog.

The audit deliverable is this report only. Existing tracked files and golden fixtures remain
unchanged. Local audit evidence (probe scripts/results, sample output directories, artifacts, and
complete file lists) remains in the temporary audit directory identified above and can be removed
later without affecting the repository.

## Complete release artifact inventories

The following lists contain every regular file in the audited artifacts. Archive directory
entries are structural containers. This report was created after the audited artifacts and is
not part of them.

Wheel — 43 files:

```text
thebigdiffer-0.2.0.dist-info/METADATA
thebigdiffer-0.2.0.dist-info/RECORD
thebigdiffer-0.2.0.dist-info/WHEEL
thebigdiffer-0.2.0.dist-info/entry_points.txt
thebigdiffer-0.2.0.dist-info/top_level.txt
thebigdiffer/__init__.py
thebigdiffer/__main__.py
thebigdiffer/cli.py
thebigdiffer/context/__init__.py
thebigdiffer/context/model.py
thebigdiffer/context/rendering.py
thebigdiffer/ingest/__init__.py
thebigdiffer/ingest/tree.py
thebigdiffer/investigator/__init__.py
thebigdiffer/investigator/accounting.py
thebigdiffer/investigator/budget.py
thebigdiffer/investigator/config.py
thebigdiffer/investigator/pricing/__init__.py
thebigdiffer/investigator/pricing/opus-4.6-bedrock-2026-05-12.json
thebigdiffer/investigator/prompt.py
thebigdiffer/investigator/prompts/__init__.py
thebigdiffer/investigator/prompts/primary-v1.txt
thebigdiffer/investigator/runtime.py
thebigdiffer/investigator/tool_contract.py
thebigdiffer/patch/__init__.py
thebigdiffer/patch/model.py
thebigdiffer/patch/presentation.py
thebigdiffer/provenance/__init__.py
thebigdiffer/provenance/model.py
thebigdiffer/providers/__init__.py
thebigdiffer/providers/base.py
thebigdiffer/providers/bedrock.py
thebigdiffer/reporting/__init__.py
thebigdiffer/reporting/model.py
thebigdiffer/reporting/persistence.py
thebigdiffer/reporting/serialization.py
thebigdiffer/repository/__init__.py
thebigdiffer/repository/git.py
thebigdiffer/repository/model.py
thebigdiffer/source/__init__.py
thebigdiffer/source/model.py
thebigdiffer/source/repository.py
thebigdiffer/source/tools.py
```

Sdist — 80 files:

```text
thebigdiffer-0.2.0/ARCHITECTURE.md
thebigdiffer-0.2.0/DESIGN-PROVENANCE.md
thebigdiffer-0.2.0/MANIFEST.in
thebigdiffer-0.2.0/PKG-INFO
thebigdiffer-0.2.0/README.md
thebigdiffer-0.2.0/pyproject.toml
thebigdiffer-0.2.0/setup.cfg
thebigdiffer-0.2.0/src/thebigdiffer.egg-info/PKG-INFO
thebigdiffer-0.2.0/src/thebigdiffer.egg-info/SOURCES.txt
thebigdiffer-0.2.0/src/thebigdiffer.egg-info/dependency_links.txt
thebigdiffer-0.2.0/src/thebigdiffer.egg-info/entry_points.txt
thebigdiffer-0.2.0/src/thebigdiffer.egg-info/requires.txt
thebigdiffer-0.2.0/src/thebigdiffer.egg-info/top_level.txt
thebigdiffer-0.2.0/src/thebigdiffer/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/__main__.py
thebigdiffer-0.2.0/src/thebigdiffer/cli.py
thebigdiffer-0.2.0/src/thebigdiffer/context/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/context/model.py
thebigdiffer-0.2.0/src/thebigdiffer/context/rendering.py
thebigdiffer-0.2.0/src/thebigdiffer/ingest/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/ingest/tree.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/accounting.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/budget.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/config.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/pricing/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/pricing/opus-4.6-bedrock-2026-05-12.json
thebigdiffer-0.2.0/src/thebigdiffer/investigator/prompt.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/prompts/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/prompts/primary-v1.txt
thebigdiffer-0.2.0/src/thebigdiffer/investigator/runtime.py
thebigdiffer-0.2.0/src/thebigdiffer/investigator/tool_contract.py
thebigdiffer-0.2.0/src/thebigdiffer/patch/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/patch/model.py
thebigdiffer-0.2.0/src/thebigdiffer/patch/presentation.py
thebigdiffer-0.2.0/src/thebigdiffer/provenance/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/provenance/model.py
thebigdiffer-0.2.0/src/thebigdiffer/providers/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/providers/base.py
thebigdiffer-0.2.0/src/thebigdiffer/providers/bedrock.py
thebigdiffer-0.2.0/src/thebigdiffer/reporting/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/reporting/model.py
thebigdiffer-0.2.0/src/thebigdiffer/reporting/persistence.py
thebigdiffer-0.2.0/src/thebigdiffer/reporting/serialization.py
thebigdiffer-0.2.0/src/thebigdiffer/repository/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/repository/git.py
thebigdiffer-0.2.0/src/thebigdiffer/repository/model.py
thebigdiffer-0.2.0/src/thebigdiffer/source/__init__.py
thebigdiffer-0.2.0/src/thebigdiffer/source/model.py
thebigdiffer-0.2.0/src/thebigdiffer/source/repository.py
thebigdiffer-0.2.0/src/thebigdiffer/source/tools.py
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/application-context-record.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/application-context.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/budget-probe.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/expected-model-requests.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/expected-patch.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/expected-report.md
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/expected-runtime.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/expected-tool-results.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/expected-transcript.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/manifest.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/patch.txt
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/primary-prompt.txt
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/rendered-context.txt
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/scripted-provider-responses.json
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/source/after/sample.py
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/source/before/sample.py
thebigdiffer-0.2.0/tests/fixtures/autonomous-investigator-v1/tool-config.json
thebigdiffer-0.2.0/tests/test_cli.py
thebigdiffer-0.2.0/tests/test_context_patch.py
thebigdiffer-0.2.0/tests/test_git_input_equivalence.py
thebigdiffer-0.2.0/tests/test_git_repository.py
thebigdiffer-0.2.0/tests/test_golden_parity.py
thebigdiffer-0.2.0/tests/test_import_boundaries.py
thebigdiffer-0.2.0/tests/test_ingest.py
thebigdiffer-0.2.0/tests/test_investigator_accounting.py
thebigdiffer-0.2.0/tests/test_investigator_prompt.py
thebigdiffer-0.2.0/tests/test_investigator_runtime.py
thebigdiffer-0.2.0/tests/test_provenance.py
thebigdiffer-0.2.0/tests/test_source_repository.py
```

Validated investigator behavior changed: NO
