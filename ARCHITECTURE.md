# TheBigDiffer Architecture

TheBigDiffer investigates an exact software patch with Claude Opus 4.6 and a small set of safe,
authoritative source-inspection tools. Inputs may be prepared BEFORE/AFTER directories or two
explicit refs in an existing local Git repository. Git inputs end at the same directory boundary;
the investigator does not have a Git-specific path. The deterministic runtime establishes source
facts and operational boundaries. Claude chooses what matters, what source to inspect, how the
behavior works, and whether the change has security significance.

```text
Local Git repository + explicit refs
        |
        v
Raw committed-object snapshot preparation
        |
        +-----------------------------+
                                      |
Prepared BEFORE/AFTER directories ----+
                                      v
Factual ApplicationContext
        +
Generic security-research instruction
        +
Exact BEFORE/AFTER patch
        |
        v
ClaudeInvestigator (Claude Opus 4.6)
        ^
        | read_source / search_source / find_definition / find_references
        v
Hash-verified SourceRepository
        |
        v
Qualified research report + complete auditable transcript
```

## Production packages

The live package has one product architecture:

- `context` validates, hashes, records, and renders factual application context supplied by the
  caller. It does not convert repository descriptions into deployment facts.
- `ingest` inventories BEFORE and AFTER directories without following symlinks or executing target
  code. It normalizes paths, classifies files, hashes bytes, and records unsupported inputs.
- `patch` constructs the exact model-visible patch and records explicit omissions if its input
  bound is reached.
- `provenance` owns architecture-neutral content identities and source provenance.
- `repository` resolves local Git refs and safely materializes exact committed objects into
  short-lived snapshot directories. It is upstream of, and independent from, the investigator.
- `source` exposes the four bounded source tools over inventoried, hash-verified snapshots.
- `investigator` owns the frozen primary prompt, tool contract, budgets, accounting, and bounded
  iterative investigation loop.
- `providers` contains the narrow AWS Bedrock Converse transport. There is no model router,
  fallback provider, or automatic retry.
- `reporting` records the full transcript, manifests, inputs, usage, costs, stop reasons, and final
  report with atomic file replacement.

`cli.py` exposes only the `investigate` command.

## Responsibility boundary

Deterministic code owns:

- optional local Git ref resolution and raw committed-object materialization;
- exact source ingestion and inventory;
- exact diff presentation;
- path confinement and symlink protection;
- source hashing and provenance;
- local tool-argument validation and execution;
- model, tool, source-byte, output, and estimated-cost limits;
- prompt/tool/configuration identity;
- complete transcript and report persistence.

Claude owns:

- relevance decisions;
- investigative paths and source requests;
- hypotheses and mechanism interpretation;
- security and benign explanations;
- deployment qualifications, assumptions, and unresolved questions.

Source and tool results are untrusted data, never instructions. TheBigDiffer never executes
repository code, installs repository dependencies, runs repository build scripts, or follows
arbitrary external URLs.

## Input preparation

Directory mode passes two caller-prepared roots directly to safe ingestion and records preparation
mode `directory`.

Git mode invokes the installed Git executable without a shell and uses only object/plumbing
operations: `rev-parse`, `cat-file`, and `ls-tree`. It resolves each user-supplied ref to an exact
commit and tree. It never uses the working tree as source truth. Raw blob bytes are written through
descriptor-relative, no-follow filesystem operations into a private temporary root with separate
`before` and `after` directories.

Before writing, every UTF-8 Git path is normalized and checked for traversal, absolute/drive
paths, backslash ambiguity, duplicates, file/parent collisions, and case or Unicode-normalization
collisions. Entries are processed in deterministic path order. Supported modes are regular blobs
(`100644`, `100755`) and symlink blobs (`120000`). Executable mode is retained as filesystem
metadata. Symlink targets are recreated byte-for-byte but never followed. Gitlinks (`160000`) are
recorded and skipped; submodules are never initialized. Unknown modes are recorded as unsupported,
while malformed types, paths, or object reads fail closed.

Git commands run with hooks disabled, optional locks disabled, replacement objects disabled,
lazy remote object fetching disabled, terminal prompting disabled, and system/global Git config
disabled. No checkout/archive attributes, clean/smudge filters, LFS downloads, fetches, or remote
acquisition are used. Temporary source snapshots are removed after the investigation on both
success and failure.

The deterministic source-preparation artifact records the canonical repository path identity,
Git version/object format, supplied refs, resolved commits, tree IDs, entries, counts, limits,
materialization status, exact preparation semantics, and a canonical manifest SHA-256. The
existing ingest layer independently hashes the materialized bytes; Git metadata supplements and
does not replace source provenance. Preparation metadata is never added to model messages.

## Source tools

All tools operate independently on the inventoried `before` or `after` snapshot:

- `read_source(version, path, start_line, end_line)` returns an exact bounded line range.
- `search_source(version, query, path?)` performs bounded literal source search.
- `find_definition(version, identifier, path?)` locates supported local definitions and reports
  ambiguity or unsupported behavior explicitly.
- `find_references(version, identifier, path?)` returns bounded lexical/syntactic identifier
  references in stable order. Matches are not automatically semantically related.

Every successful result carries version, repository-relative path, line, and content-hash
provenance as applicable. Reads are reverified against the inventory. Traversal, symlink escapes,
unsafe arguments, cumulative source-byte excess, and unsupported files fail explicitly.

## Investigation runtime

`ClaudeInvestigator` performs one primary autonomous investigation:

1. Obtain two source directories directly or from the Git preparation boundary.
2. Inventory both source directories.
3. Build and persist the factual context, exact patch, prompt identity, tool definitions, source
   inventory, and investigation manifest.
4. Send the prompt, context, and patch to Bedrock using native tool use at temperature zero.
5. Validate and execute any source requests, append exact results, and continue the conversation.
6. Stop on model completion, a provider error, or an operational limit.
7. Persist the report, transcript, usage, estimated cost, hashes, and stop reasons.

The local cost ceiling is an admission and termination safeguard, not an AWS billing guarantee.
Provider errors are recorded and stop cleanly; the runtime does not silently retry or switch
models.

## Deliberate exclusions

The production runtime has no ApplicationMap, normalized semantic evidence package, deterministic
relevance ranking, call graph, dependency graph, taint analysis, symbolic execution, automatic
source/sink discovery, challenger, reconciliation, or mandatory cross-examination. It does not
contain the retired M1/M2/M3/M4 product pipeline.

Those approaches are not active runtime dependencies. The separate historical research archive
preserves the experiments that led to this boundary.

## Reproducibility and parity

The production primary prompt is versioned and its SHA-256 is recorded with every investigation.
The production path is protected by a small immutable offline golden contract derived from the
validated benchmark primary path. It covers prompt bytes, context and patch presentation, tool
schemas/results, ordering, provenance, budget admission, accounting, transcript events, and stop
reasons without requiring the historical research tree at test time.
