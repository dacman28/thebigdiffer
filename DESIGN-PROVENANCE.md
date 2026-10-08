# Design Provenance

TheBigDiffer's production architecture was selected through a larger controlled research program.
That historical repository is intentionally kept separate from this deployable project: production
builds and tests must not depend on research runners, benchmark corpora, transcripts, or reports.

The validated architecture milestone is `v2-autonomous-investigator-opus-4.6` at commit
`1bd47dd6243aaf58d294a76258236506405defa0`. The production Git-input milestone and final archive
source commit are `v2-git-input-ready` and
`ef31421da220fdcc864efbc52657b3dff2e20f3b`. The immutable historical research tree object is
`3848f859d854ba529292848b6227b7f7eb4e1cb8`.

The production primary prompt is byte-identical to the validated prompt. Its SHA-256 is
`f2973b032a0a76e1aed537e2975cc861941f40a7a95bf88d5d0435da3dd347ab`.

`tests/fixtures/autonomous-investigator-v1/` is a minimal derivative compatibility contract. Its
manifest records the source commits, architecture tag, prompt identity, model configuration, tool
definition identity, budgets, pricing identity, and every fixture-file hash. The corresponding
tests exercise the scripted provider conversation, source-tool results, model-visible requests,
accounting, transcript semantics, stop reason, and report entirely offline.

The fixture is not new research evidence and does not replace the archived evidence. It exists so
this standalone production repository can detect behavioral drift without copying or importing the
historical research implementation.
