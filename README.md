# TheBigDiffer

TheBigDiffer is an autonomous software-patch security investigator. It gives Claude Opus 4.6 a
factual application description, the exact BEFORE/AFTER patch, and safe access to the inventoried
source. Claude chooses the investigation path and produces a qualified, source-grounded report.

The runtime does not execute target code, install target dependencies, run target build scripts,
or follow source-tree symlinks.

## Installation

From the project directory, create and activate a virtual environment, then install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
thebigdiffer --help
```

Keep this environment activated for the commands below. Without activation, invoke
`.venv/bin/thebigdiffer` directly. A built wheel can also be installed with
`python -m pip install /path/to/thebigdiffer-2.0.0-py3-none-any.whl` in an activated environment.

### Platform requirements

The package declares Python >=3.11. Release validation exercised macOS (Darwin 25.2.0 arm64),
CPython 3.12.10, and Git 2.50.1 (Apple Git-155). This is a tested environment, not a complete
Python/OS compatibility matrix. Linux has not been validated for this release; Windows support
has not been established. The shell/virtual-environment commands here use POSIX conventions.

Safe ingestion requires descriptor-relative filesystem operations, including `O_NOFOLLOW`,
`O_DIRECTORY`, directory-relative open/readlink, and descriptor-based directory scanning.
It fails closed when the required safe-ingest capabilities are unavailable. Git snapshots also
require descriptor-relative mkdir, symlink and unlink operations and file-mode support.

Local Git mode requires an installed Git executable on PATH that supports the product's plumbing
and hardening controls: `rev-parse --end-of-options`, object-format reporting, `ls-tree -z`,
`cat-file`, disabled hooks/config/replacement objects, and `GIT_NO_LAZY_FETCH` to prevent lazy
remote acquisition. Git 2.50.1 is the validated version; compatibility with other versions must
be verified rather than inferred merely from the presence of a `git` command.

### AWS and Bedrock requirements

An investigation requires AWS credentials with permission and model access to invoke Bedrock:

- Production region: `us-east-1`.
- Production model ID: `us.anthropic.claude-opus-4-6-v1` (Claude Opus 4.6).
- Credential resolution is delegated to boto3/botocore. Use their normal supported credential
  and profile mechanisms; for an already configured named profile, for example,
  `export AWS_PROFILE=your-profile` before running TheBigDiffer.
- TheBigDiffer does not store AWS credentials or implement its own credential manager. AWS SDK
  credential providers may manage their own files/caches. Not every credential mechanism has
  been tested with this application.

The CLI explicitly uses the region above; setting an AWS region environment variable does not
override it. There is no CLI model/region override, fallback model, or automatic invocation retry.
Missing profiles and partial credential configuration produce a setup error before investigation.
Errors encountered during an invocation are retained in `transcript.json`; incomplete-run output
points to it. No live Bedrock entitlement or invocation is established by the offline test suite.

## Investigate a patch

Prepare a UTF-8 JSON context file with exactly these four required fields. Copy and edit
[examples/application-context.json](examples/application-context.json), which contains clearly
fictitious example facts:

```json
{
  "repository_type": "Fictitious Python library",
  "application_context": "The fictional Example Notes library formats plain-text notes.",
  "deployment_context": "Unknown.",
  "provenance": "Fictitious documentation example; replace with the origin of your supplied facts."
}
```

Each value must be a string containing non-whitespace text and at most 4,000 characters.
Additional keys are rejected. Use `Unknown.` for deployment facts you cannot establish; a
repository description is not evidence of installation or exposure. TheBigDiffer does not infer
context automatically. The generated output `application-context.json` is an audit record with
identity information, not a reusable four-key input file.

TheBigDiffer supports two explicit, mutually exclusive source-input modes.

### Prepared directory mode

Use existing BEFORE and AFTER source directories:

```bash
thebigdiffer investigate \
  --before /path/to/before \
  --after /path/to/after \
  --context /path/to/context.json \
  --output /path/to/new-output-directory
```

The output directory must not already exist and must not overlap either investigated tree in
either direction. Choose a private output location as described below. Once investigation
initialization succeeds, incomplete runs preserve their audit trail and return a nonzero CLI
status. Local validation and provider setup failures can occur before any output is created.

### Local Git-ref mode

Use two explicit refs from a repository already present on the local filesystem:

```bash
thebigdiffer investigate \
  --repo /path/to/local/repository \
  --before-ref v1.0.0 \
  --after-ref v1.0.1 \
  --context /path/to/context.json \
  --output /path/to/new-output-directory
```

Git mode resolves each supplied ref to an immutable commit and tree, then reads the committed tree
with Git plumbing into private temporary `before` and `after` directories. Regular files equal
their raw Git blob bytes. Dirty and untracked working-tree files have no effect. TheBigDiffer does
not check out code, apply `.gitattributes` export or checkout transformations, run hooks or target
code, initialize submodules, invoke Git LFS, fetch, clone, or contact a remote.

Symlinks are recreated as symlinks without following their targets and are subsequently refused as
source by the existing safe ingest boundary. Gitlinks are recorded as skipped in the preparation
manifest and are not traversed. The supplied refs, resolved commit IDs, tree IDs, Git version,
entry provenance, counts, and deterministic manifest hash are persisted in
`source-preparation.json`. Temporary snapshots are removed after successful or failed
investigation.

Both committed path sets are validated before either snapshot is created. Distinct path prefixes
that collide under Unicode NFC normalization and case-folding are rejected, including directory
prefixes and file/directory aliases. Paths are never renamed or merged to fit the filesystem.

Directory flags cannot be combined with Git flags. Both directory paths are required in directory
mode, and `--repo`, `--before-ref`, and `--after-ref` are all required in Git mode. No ref defaults
are inferred. This release supports local repositories only; it does not clone or acquire remote
repositories.

Changed binary files and symlinks are represented by deterministic non-text change records with
paths and BEFORE/AFTER hashes. They do not abort an accompanying text investigation. Their bytes
and symlink targets are not presented as textual source, and symlink targets are not followed.

## Output artifacts and completion

Start with **`research-report.md`**, but **always inspect `metrics.json`, especially `stop_reason`,
to determine completion**. A Markdown report existing does not by itself mean the investigation
completed. Incomplete runs can contain partial model prose without an incompleteness banner.

| File | Purpose |
| --- | --- |
| `research-report.md` | Human-readable model report or incomplete fallback |
| `metrics.json` | Stop reason, usage, estimated cost, hashes and finish time |
| `transcript.json` | Full requests/responses, tool exchanges, provider/error detail and final status |
| `investigation-manifest.json` | Model, prompt, configuration, pricing and source identities |
| `application-context.json` | Supplied context record and identity |
| `patch-presentation.txt` | Exact model-visible source comparison |
| `primary-prompt.txt` | Exact primary prompt |
| `tool-definitions.json` | Exact source-tool contract |
| `source-inventory.json` | Source files, hashes, classifications and ingest diagnostics |
| `source-preparation.json` | Directory/Git source preparation and provenance |

The CLI prints the report path, stop reason and metrics path. Successful completion uses exit
status 0 and `model_end_turn`. An incomplete investigation uses a nonzero exit status and also
prints the transcript path. Examples of incomplete stop reasons include
`model_transport_error_no_retry`, `model_max_tokens`, and
`budget_exhausted_model_requested_more_tools`. Transport-error details are in transcript events
of type `model_transport_error` (`error_class`, `error`, and `retry_attempted`).

Completion records the model's stopping state; it is not a guarantee that its security conclusion
is correct. The local estimated spending ceiling is an operational safeguard, not an AWS billing
limit. The recorded pricing identity and usage explain the estimate.

### Confidentiality

Output can contain sensitive material: context, patch/source snippets, provider/model responses,
error strings and complete transcript information are persisted. Source/context is also sent to
the configured Bedrock model as part of investigation. There is **no automatic secret redaction**.

Use a private output parent with appropriate filesystem permissions. For example, on a supported
POSIX system create a private parent before selecting a new child directory:

```bash
mkdir -m 700 /path/to/private-investigations
```

Then use a new path such as `/path/to/private-investigations/run-001` for `--output`.
For an existing parent, inspect and set its permissions appropriately. Artifact permissions
inherit the process umask and parent-directory access; TheBigDiffer does not force private
permissions or encrypt its output. Review artifacts before sharing them.

## Current limitations

Source acquisition is local only. Source tools inspect bounded, hash-verified text without
executing target code; definition and reference lookup currently support Python syntax, with
literal search available for other text. Binary content is not analyzed as source, symlinks are
not followed, and Git submodules are not initialized. Reports may remain inconclusive because
of missing context, unavailable source, provider failure or operational limits. The application
does not automatically retry or resume incomplete runs; use a new output directory for a new run.

No project license has been selected. Licensing for public distribution remains explicitly
undecided; this repository does not declare an open-source license.

## Architecture

```text
Local Git refs -> safe temporary snapshots --+
                                              |
Prepared BEFORE/AFTER directories ------------+
                                              v
ApplicationContext + exact patch + generic security-research instruction
                              |
                              v
                      ClaudeInvestigator
                              ^
                              | raw source tools
                              v
                       SourceRepository
                              |
                              v
                 report + transcript + provenance
```

The four source tools are `read_source`, `search_source`, `find_definition`, and
`find_references`. They retrieve bounded, hash-verified source. They do not rank relevance, infer
security paths, or classify vulnerabilities. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full
responsibility and trust boundaries.

## Validation

For development, use the same activated virtual environment and install the supported extra:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m pytest -q tests/test_golden_parity.py
ruff check --no-cache src tests
mypy --strict src
```

Build release artifacts with an installed build frontend:

```bash
python -m pip install build
python -m build
```

The standalone golden parity contract in
`tests/fixtures/autonomous-investigator-v1/` protects the model-visible request, source-tool
results, accounting, transcript semantics, and report behavior without requiring the historical
research repository. See [DESIGN-PROVENANCE.md](DESIGN-PROVENANCE.md) for its origin.
