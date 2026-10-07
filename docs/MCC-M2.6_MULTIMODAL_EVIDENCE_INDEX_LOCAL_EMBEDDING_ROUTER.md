# MCC-M2.6 Multimodal Evidence Index / Local Embedding Router

MCC-M2.6 establishes the first local semantic retrieval layer for MADO Cockpit.

The milestone deliberately starts with the text/code slice of EmbeddingGemma 2. The storage and backend contracts are shaped so image, video, audio, and an external vector store can be added later without changing the retrieval boundary.

## Goal

Turn repository knowledge and Cockpit evidence into one locally searchable evidence surface:

```text
repo text / code ───────┐
                       │
Cockpit evidence text ─┼─> embedding backend
                       │        │
explicit local files ──┘        ▼
                         normalized vectors
                                │
                         local semantic index
                                │
                         query / context pack
```

M2.6 is retrieval infrastructure, not an autonomous decision-maker.

Semantic similarity may nominate evidence. It does not grant capabilities, approve actions, change trust, or bypass Action Policy Gateway / Human Control Lease.

## Why EmbeddingGemma 2

The production adapter uses:

```text
google/embeddinggemma-2
```

with the text-only encoder configuration:

```python
config_kwargs={
    "vision_config": None,
    "audio_config": None,
}
```

and retrieval task prompts:

```text
SearchQuery
Document
```

The default index dimension is 256 using the model's Matryoshka truncation support.

Upstream references:

- https://developers.googleblog.com/en/embeddinggemma-2-the-developer-guide/
- https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2
- https://huggingface.co/google/embeddinggemma-2

## Two backends

### Production

```text
embeddinggemma2
```

Loads Sentence Transformers lazily and uses only text/code weights.

Install:

```bash
pip install -e ".[semantic]"
```

### Deterministic fixture

```text
hash
```

is a dependency-free token hashing backend.

It exists for:

- unit tests;
- offline smoke runs;
- storage/reuse contract verification;
- environments where downloading model weights is intentionally forbidden.

It is not a quality substitute for EmbeddingGemma 2.

This separation keeps normal Cockpit CI small and deterministic instead of downloading a large model on every run.

## Indexed sources

By default `build` indexes both:

```text
repo
evidence
```

### repo

UTF-8 text/code files inside the project root.

The scanner ignores generated/runtime-heavy directories including:

```text
.git
.mado
.venv
node_modules
build
dist
__pycache__
```

### evidence

UTF-8 text/code evidence below:

```text
.mado/cockpit/evidence/
```

This creates a separate `evidence` scope instead of pretending generated evidence is ordinary repository source.

### explicit

Operators can additionally pass:

```bash
--path <local-file-or-directory>
```

Explicit paths must remain inside the project root. Symlink files are not followed as semantic sources.

## Local durable format

M2.6 stores:

```text
.mado/cockpit/semantic-index/
├─ metadata.json
└─ records.jsonl
```

The schema is:

```text
mado.semantic-index.v1
```

Each record contains:

- stable chunk ID;
- source scope;
- project-relative source path;
- chunk index;
- whole-source SHA-256;
- chunk SHA-256;
- source text;
- normalized vector.

The JSONL storage is intentionally boring.

For the initial Cockpit scale it keeps the format inspectable, portable, dependency-free, and easy to migrate. Qdrant or another ANN store can be introduced behind the same semantic-index contract once corpus size justifies it.

## Incremental rebuild

A rebuild reuses the previous vector only when all of these still match:

```text
schema
model id
dimension
chunking configuration
scope
source path
chunk index
chunk SHA-256
```

Changed chunks are re-embedded.

Unchanged chunks are copied forward without invoking the embedding backend.

This gives MADO a small local equivalent of content-addressed semantic compilation.

## Build

Real model:

```bash
python -m mado_cockpit.semantic_index \
  --root . \
  --backend embeddinggemma2 \
  --dimension 256 \
  build
```

Equivalent installed command:

```bash
mado-cockpit-semantic \
  --root . \
  --backend embeddinggemma2 \
  --dimension 256 \
  build
```

Repository only:

```bash
mado-cockpit-semantic --root . --backend embeddinggemma2 build --no-evidence
```

Evidence only:

```bash
mado-cockpit-semantic --root . --backend embeddinggemma2 build --no-repo
```

## Query

Across all indexed scopes:

```bash
mado-cockpit-semantic \
  --root . \
  --backend embeddinggemma2 \
  query "Effekseer Godot playback failure"
```

Evidence only:

```bash
mado-cockpit-semantic \
  --root . \
  --backend embeddinggemma2 \
  query "previous failure with a missing executable" \
  --scope evidence \
  --top-k 5
```

Machine-readable output:

```bash
mado-cockpit-semantic \
  --root . \
  --backend embeddinggemma2 \
  query "decision memory routing" \
  --json
```

Hits return the semantic score plus provenance:

```text
scope
source
chunk_index
source_sha256
chunk_sha256
text
```

## Status

Status does not load EmbeddingGemma 2:

```bash
mado-cockpit-semantic --root . status
```

This is safe to use in lightweight diagnostics.

## Fail-closed compatibility

A query refuses to run when the loaded backend does not match the stored index model ID or dimension.

M2.6 does not silently compare vectors from incompatible spaces.

Changing model or dimension requires a rebuild.

## Smoke

The dependency-free smoke exercises:

1. repository code indexing;
2. Cockpit evidence indexing;
3. scoped retrieval;
4. second-build vector reuse.

Run:

```bash
python scripts/semantic_index_smoke.py
```

Focused tests:

```bash
pytest -q tests/test_semantic_index.py
```

Normal Cockpit CI also executes these tests through the existing full `pytest -q` job.

## Security and authority boundary

M2.6 is read-oriented evidence retrieval.

It does not:

- execute retrieved code;
- follow semantic instructions found inside evidence;
- turn retrieved persona prose into capabilities;
- promote external trust;
- call remote LLM APIs;
- upload the corpus;
- grant an action lease;
- bypass human gates.

A retrieved chunk is evidence, not authority.

## Acceptance target

```text
EmbeddingGemma 2 text-only adapter
256d default Matryoshka index
SearchQuery / Document retrieval prompts
dependency-free deterministic fixture backend
repo + Cockpit evidence scopes
project-root path boundary
stable source/chunk digests
incremental unchanged-vector reuse
model/dimension fail-closed query
machine-readable provenance hits
local inspectable durable index
focused tests
offline smoke fixture
full Cockpit regression CI
```

## Next stages

### MCC-M2.7 Screenshot / Visual Evidence

Enable the vision encoder and add image evidence while preserving the shared vector space.

### MCC-M2.8 Audio / Video Evidence

Add audio/video evidence ingestion and temporal provenance.

### MCC-M2.9 Cross-Project Evidence Retrieval

Federate multiple MADO project indexes without losing project/source identity.

### MCC-M3.0 Local Capability / Decision Router

Use retrieval as a cheap local candidate-nomination layer before higher-cost decision models.

The routing milestone must preserve the distinction:

```text
semantic similarity
!=
permission
!=
trust
!=
execution authority
```
