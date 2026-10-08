# TheBigDiffer

TheBigDiffer is an autonomous software-patch security investigator. It gives Claude Opus 4.6 a
factual application description, the exact BEFORE/AFTER patch, and safe access to the inventoried
source. Claude chooses the investigation path and produces a qualified, source-grounded report.

The runtime does not execute target code, install target dependencies, run target build scripts,
or follow source-tree symlinks.

## Install for development

The project requires Python 3.11 or newer and AWS credentials that can invoke the configured
Bedrock model.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Investigate a patch

Prepare a JSON context file with exactly these fields:

```json
{
  "repository_type": "Python web application framework",
  "application_context": "This source implements framework facilities used by applications.",
  "deployment_context": "Unknown.",
  "provenance": "explicitly supplied by the user"
}
```

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

The output directory must not already exist and must be outside both investigated trees. A
completed investigation writes the exact prompt, application context, patch presentation, tool
definitions, source-preparation provenance, source inventory, manifest, transcript, metrics, and
research report. Incomplete runs preserve their audit trail and return a nonzero CLI status.

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

Directory flags cannot be combined with Git flags. Both directory paths are required in directory
mode, and `--repo`, `--before-ref`, and `--after-ref` are all required in Git mode. No ref defaults
are inferred. This release supports local repositories only; it does not clone or acquire remote
repositories.

AWS authentication uses the normal boto3 credential chain. The production defaults are locked to
the validated Claude Opus 4.6 Bedrock configuration; there is no fallback model or automatic retry.

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

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check --no-cache src tests
.venv/bin/mypy --strict src
```

The standalone golden parity contract in
`tests/fixtures/autonomous-investigator-v1/` protects the model-visible request, source-tool
results, accounting, transcript semantics, and report behavior without requiring the historical
research repository. See [DESIGN-PROVENANCE.md](DESIGN-PROVENANCE.md) for its origin.
