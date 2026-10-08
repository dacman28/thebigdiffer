READY WITH MINOR NON-BLOCKING ITEMS

# Release correctness fix report

B1 and B2 are fixed and regression-tested. The standalone application is ready for internal/team
use within the documented tested environment. Public distribution licensing remains undecided;
no license was selected, no release tag was moved, and no live Bedrock call was made.

## Baseline

- Original audited commit: `4c10c56fad3d9715ad639ab9b2f6b838fe0f9103`.
- Working branch: `fix/release-readiness`.
- At task start, tracked files were clean and the completed audit was the only untracked file.
  It was committed unchanged before implementation.
- `RELEASE-READINESS.md` retains its original `NOT READY` verdict for the original commit.
  Its unchanged SHA-256 is
  `c9f99f5dc285c8562dd4fce9fd105ce96d005d687045f3d195a112e095b273e5`.
- Tested implementation/documentation commit: `a872c5434d10e538273fd967dd882765cd3cb513`.
  This report is added in a separate documentation-only commit.
- The historical research repository was not accessed or modified.

Narrow commits:

| Commit | Change |
| --- | --- |
| `175c392` | Preserve standalone release-readiness audit |
| `104f88f` | Reject Git path-prefix identity collisions |
| `7373443` | Handle non-text patch changes without aborting |
| `fe1d90c` | Improve CLI provider configuration errors |
| `97934c2` | Align v2 package metadata |
| `8f3081b` | Improve investigation completion messaging |
| `a872c54` | Document installation and operational requirements |

The existing annotated `v2.0.0` tag still resolves to the original audited commit. No tags,
remotes, or historical commits were changed; nothing was pushed.

## B1 fix

`repository/git.py::_validate_entry_paths` now registers every raw prefix, including the leaf,
under the existing portable identity `unicodedata.normalize("NFC", prefix).casefold()`.

For `foo/bar/baz.py` it checks `foo`, `foo/bar`, and `foo/bar/baz.py`. A map remembers the
first raw spelling for each portable identity. Encountering the same identity with a different
raw spelling raises `GitPreparationError`. Identical shared directory prefixes remain valid.
The existing duplicate-leaf and non-directory-parent checks remain in place, so exact raw
file/directory conflicts still fail as well.

Ref resolution/tree enumeration now finish for **both** snapshots before `mkdtemp` or any
snapshot-directory/file creation. This is important when BEFORE is valid but AFTER contains
a collision: neither tree is written. Materialization still reads exact immutable Git blobs,
preserves source paths and file modes, refuses traversal, and produces the same manifest schema.
There is no renaming, chosen spelling, normalization of source identity, or directory merging.

`tests/test_git_prefix_identity.py` adds nine regressions:

| Case | Result |
| --- | --- |
| `A/one.py` and `a/two.py` | Rejected |
| `src/Foo/a.py` and `src/foo/b.py` | Rejected |
| `caf\u00e9/one.py` and `cafe\u0301/two.py` (distinct NFC/decomposed spellings) | Rejected |
| `Foo` and `foo/bar.py` | Rejected |
| Each of those four cases in BEFORE and separately in AFTER | Rejected before workspace creation |
| `A/one.py` and `A/two.py` | Both trees succeed; bytes, inventory paths and manifest entries agree |

These fixtures use `hash-object`, `mktree` and `commit-tree` to create actual committed paths,
independently of what the host filesystem can represent. A workspace-creation sentinel fails
the test if materialization starts too early. All eight rejection cases failed against the old
implementation and pass with the fix; the valid shared-prefix case passed throughout.

The audit's exact case-prefix reproduction was also rerun against the installed release wheel
with an invalid AFTER tree. It now reports:

```text
case or Unicode-normalization path collision: 'A' and 'a'
```

The snapshot-creation sentinel was never reached. Existing Git tests and the existing
Git/directory model-visible equivalence test pass unchanged.

## B2 fix

`patch/presentation.py` now checks both existing records' `file_kind` before calling `_text`.
Verified text reads run only when every existing side is eligible `source` or `text`.

If either side is non-text, the pre-existing deterministic representation runs unchanged:

```text
<non_text_change>
{'path': <relative path>, 'status': 'non_text',
 'before_sha256': <hash or None>, 'after_sha256': <hash or None>,
 'retrieval': 'source tools do not return binary content'}
</non_text_change>
```

The example above is line-wrapped for explanation; the code's original dictionary serialization,
field order, marker and retrieval wording are unchanged. These records remain in
`patch_records`; no new budget-omission schema or security interpretation was introduced.
A binary/text transition uses that same non-text representation for the pair.

The production code change is only moving the two verified-text-read statements below the
existing classification/`continue` branch. Text-only diffs, hunk ranges, ordering, hashes,
omission logic and initial model input remain byte-identical for the validated cases.
Non-text-only investigations proceed with the same context and deterministic non-text markers;
the runtime does not invent binary contents or a security conclusion.

`tests/test_patch_non_text.py` adds twenty end-to-end investigator regressions: ten scenarios,
each alone and each alongside a normal text change:

- Binary addition, removal and modification.
- Binary-to-text and text-to-binary transitions.
- Symlink addition, removal and target change.
- Unchanged binary and unchanged symlink.

The sixteen changed-entry cases reproduced the old abort; the four unchanged-entry cases were
already successful. All twenty now pass. They check exact non-text records/hashes/markers,
normal text diffs, unchanged-entry omission, provider invocation and final report persistence.
They also check that binary markers, symlink target paths/content, and transition-only text
are absent from model requests. Symlinks are never followed; source-tool behavior is untouched.

The installed wheel's directory and Git smoke investigations each included a modified text file,
an added binary and an added symlink. Both reached the provider and completed, wrote all ten
artifacts, and produced identical model requests and patch bytes. Dirty/untracked Git working-tree
files were excluded. This reruns the audit's B2 trigger through both supported CLI modes.

## Release metadata

Both authoritative production declarations are now `2.0.0`:

- `pyproject.toml`: `project.version`.
- `src/thebigdiffer/__init__.py`: `__version__`.

`tests/test_version.py` checks project metadata, the runtime export and installed distribution
metadata agree at `2.0.0`. The isolated installed wheel also reports `2.0.0` for both identities.

Packaging now declares README as its Markdown long description, useful keywords/classifiers,
and the actual repository URL. The context example is included in the sdist through
`MANIFEST.in`. No license file, SPDX expression, or license classifier was invented.
README explicitly records that public distribution licensing is undecided.

Runtime dependency declarations are unchanged: `boto3>=1.43,<2` and
`botocore[crt]>=1.43,<1.44`. No alternate provider or credential manager was added.

## CLI/AWS diagnostics

Expected SDK errors are caught **only around provider construction** using
`BotoCoreError`/`ClientError`. The CLI returns 2 and prints the error with guidance to check
AWS SDK credentials/profile configuration and Bedrock access in the current region.
Unexpected programming exceptions are not broadly swallowed.

Real subprocess tests with isolated SDK configuration reproduce `ProfileNotFound` and
`PartialCredentialsError`. They now return 2, name the missing profile/credential field, give
actionable guidance, and contain no traceback. No real credentials or live AWS requests were
used for these tests.

Local preflight now validates the context and output existence before Git preparation, and
source-root existence/type/symlink status before provider construction. It detects existing
outputs (including dangling symlinks) and invalid output parents. These are early usability
checks; authoritative no-follow ingestion, hash checks and the artifact writer's no-overwrite
check remain unchanged. Git preparation/cleanup `OSError` failures also receive concise CLI
errors. Eleven new diagnostic/preflight tests cover these paths.

Successful completion prints, to stdout:

```text
Investigation complete.
Report: <output>/research-report.md
Status: model_end_turn
Metrics: <output>/metrics.json
```

Incomplete runs keep a nonzero status and print their exact stop reason, report/metrics paths,
and `Transcript/error detail: <output>/transcript.json` to stderr. Three additional tests cover
success, model output exhaustion and transport failure, comparing printed status with persisted
metrics/transcript state and verifying a single invocation/no retry.

The CLI does not interpret security findings or rewrite any persisted report/transcript.
`providers/bedrock.py` and the investigation runtime remain unchanged, including native Converse
messages, credential resolution, timeouts, retry policy, model defaults, budgets and accounting.

## Documentation changes

README now documents:

- A complete activated-venv `pip install .` path, explicit unactivated executable alternative,
  and wheel installation.
- The normal boto3/botocore credential chain, Bedrock access requirements, fixed `us-east-1`
  region and `us.anthropic.claude-opus-4-6-v1` model ID.
- No application credential store and no claim that every SDK credential mechanism was tested.
- Python >=3.11 as a declaration, distinguished from the exercised macOS/CPython 3.12.10/
  Git 2.50.1 environment. Linux validation and Windows support are not claimed.
- Required descriptor-relative/no-follow filesystem features and Git plumbing/hardening support.
- Both source modes, path collision rejection and non-text change handling.
- All ten stable artifacts, `research-report.md` as the human starting point, and mandatory
  inspection of `metrics.json.stop_reason` for completion.
- Transcript error detail and the fact that Markdown report existence does not imply completion.
- Sensitive raw context/source/responses/errors/transcripts, no automatic secret redaction,
  and a private output parent with appropriate permissions/umask.
- Development validation and build commands, current limitations and undecided licensing.

`examples/application-context.json` contains fictitious facts in the exact existing four-key
schema. The production loader accepts it; README links to it and explains field bounds and the
difference between context input and output record. No inference or rendering change was added.

ARCHITECTURE documents prefix validation of both trees, classify-before-read behavior and the
CLI boundary changes. The original audit and concise research provenance were preserved.

## Golden parity

**0 golden fixture files changed.**

All five existing golden parity tests pass unchanged. The existing Git/directory equivalence
test passes unchanged. The original text-only patch contract, source-tool schemas/results,
model requests, cost admission/accounting, transcript and report expectations remain intact.

The prompt file and its declared SHA are unchanged:

```text
f2973b032a0a76e1aed537e2975cc861941f40a7a95bf88d5d0435da3dd347ab
```

A baseline Git comparison confirms no changes under `tests/fixtures`, `context`, `source`,
`investigator`, `providers`, `reporting` or `ingest`. The deterministic non-text bug fix enables
previously failing inputs; it does not change the validated text-source investigator.

Primary prompt changed: NO

Existing golden fixture changed: NO

Validated text-source investigator behavior changed: NO

## Full validation

Environment: macOS/Darwin 25.2.0 arm64, CPython 3.12.10, Git 2.50.1 (Apple Git-155).
Fresh temporary development and wheel environments were created outside the repository.
Tooling: pip 26.2.1 in the development environment, pytest 9.1.1, Ruff 0.16.10,
mypy 2.4.0, build 1.6.1 and isolated setuptools 84.0.0.

| Check | Result |
| --- | --- |
| Full checkout pytest | **142 passed**, no failures/skips, 11.55s |
| Golden parity separately | **5 passed**, unchanged |
| Existing Git/directory equivalence | PASS in full suite |
| B1 focused regressions | **9 passed**; invalid trees rejected before either snapshot |
| B2 focused regressions | **20 passed**; changed and unchanged non-text scenarios |
| Ruff `check --no-cache src tests` | PASS |
| Mypy `--strict src` | PASS, 36 source files |
| Build | PASS: sdist, then wheel built from sdist |
| Clean wheel install | PASS, non-editable |
| Wheel import/version/resources | PASS from wheel environment's `site-packages` |
| Wheel top-level and investigate help | PASS |
| Development and wheel `pip check` | PASS |
| Extracted-sdist pytest | **142 passed**, no failures/skips, 10.88s |
| Wheel offline directory smoke | PASS, mixed text/binary/symlink patch, ten artifacts |
| Wheel offline Git-ref smoke | PASS, identical model requests; working-tree changes ignored |
| Wheel B1 audit reproduction | PASS: fails closed before workspace creation |
| Wheel B2 audit reproduction | PASS: reaches investigator in both modes |
| Audit SHA / prompt SHA / fixture diff | Unchanged |
| Git whitespace/diff checks | PASS |

The count increased from 98 to 142: 9 Git identity tests, 20 non-text tests, 11 CLI diagnostic
tests, 3 CLI status tests and 1 version test. The five golden tests are included in 142; their
separate run does not add five new tests. Existing safety assertions were not loosened.

The validation commands used the corresponding temporary environment's executables:

```bash
python -m pip install -e '.[dev]' build
python -m pytest -q -o addopts=''
python -m pytest -q -o addopts='' tests/test_golden_parity.py
ruff check --no-cache src tests
mypy --strict src
python -m build --outdir <temporary-dist>
python -m pip check
```

The wheel was then installed into another clean venv. Import/help/resource checks and the
offline smoke ran outside the checkout with that environment's executable; the smoke used
`python -I` and asserted the import path is inside the wheel environment. Extracted-sdist tests
used the sdist's own source/tests/fixtures. No editable install was used for the wheel checks.

| Artifact | Size | Files | SHA-256 |
| --- | ---: | ---: | --- |
| `thebigdiffer-2.0.0-py3-none-any.whl` | 54,514 bytes | 43 | `01e11023e9ccad219ca5ec3e519cc06d948ac25e888af5cdcd8653a5c7c58475` |
| `thebigdiffer-2.0.0.tar.gz` | 86,959 bytes | 84 | `9d3437b871c5e004626cba683c5c9d79d176b04c9b0f6af7a159445fb0459ed4` |

Both artifacts include the prompt and pricing resources. Package bytes match the validated
checkout; wheel metadata includes the exact README long description. The sdist includes the new
context example and all regression tests. Inspection found no Git metadata, build/cache/venv
trees, developer-home paths or credential/private-key patterns. The wheel contains runtime
files and distribution metadata; the sdist adds production documentation, examples and tests.
The audit/fix reports remain repository documents, not runtime resources.

Artifacts, file inventories, the installed-wheel smoke script and representative output remain
at `/private/tmp/thebigdiffer-release-fix.4t9cGv`. The build directory is `dist` beneath that
temporary root. These files are local validation evidence, not a publication or deployment.

## Remaining release issues

| Classification | Remaining item |
| --- | --- |
| BLOCKER | None from this release-correctness task. B1/B2 no longer reproduce. |
| SHOULD FIX | Select an appropriate license before public distribution; no license was chosen on the user's behalf. This does not block the requested internal/team readiness verdict. |
| SHOULD FIX | Maintainer release administration: the existing `v2.0.0` tag still refers to the audited old commit. Any final tag recreation is reserved to the user, as requested. |
| BACKLOG | Broader Python/OS/Git compatibility matrix and automated wheel/sdist validation; current tested scope is explicit. |
| BACKLOG | Live Bedrock/account-access and additional SDK credential-mechanism validation in an authorized environment; this task's investigations were offline. |
| BACKLOG | Dependency reproducibility/update policy, resource-stress coverage and isolation of remaining older Git test fixtures from developer configuration. |
| RESEARCH | None needed for these corrections. Future changes to validated investigator semantics require a separate controlled evaluation. |

No architecture, prompt, model defaults, context rendering, source tools, budgets/accounting,
provider transport, report/transcript meaning or exact committed-source semantics were redesigned.
All requested release fixes are committed on the existing fix branch; the preserved audit remains
a truthful record of the original release state.

Primary prompt changed: NO

Existing golden fixture changed: NO

Validated text-source investigator behavior changed: NO
