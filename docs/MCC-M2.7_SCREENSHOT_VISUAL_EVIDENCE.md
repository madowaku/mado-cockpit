# MCC-M2.7 Screenshot / Visual Evidence

MCC-M2.7 adds screenshot and image evidence to the local semantic retrieval layer introduced by MCC-M2.6.

The target flow is:

~~~text
text query
   |
   v
EmbeddingGemma 2 text encoder
   |
   +--------- shared vector space ---------+
   |                                       |
repo text/code                       screenshot evidence
MADO evidence text                   visual artifacts
   |                                       |
270M text encoder                    +170M vision encoder
   |                                       |
   +------------ semantic index ------------+
~~~

A text query can retrieve a screenshot directly without first converting the screenshot into a caption.

## Upstream contract

M2.7 follows the EmbeddingGemma 2 multimodal contract:

- model: google/embeddinggemma-2;
- text-only configuration: 270M parameters;
- text + vision configuration: 440M parameters;
- image inputs are encoded without a text prompt;
- text retrieval queries use SearchQuery;
- text documents use Document;
- all modalities project into the same vector space;
- existing text-only vectors do not need to be recomputed when vision is enabled;
- default MADO dimension remains 256 via Matryoshka truncation and normalization.

References:

- https://developers.googleblog.com/en/embeddinggemma-2-the-developer-guide/
- https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2
- https://huggingface.co/google/embeddinggemma-2

## Why visual sync is separate

M2.7 deliberately does not make every semantic operation load the vision encoder.

~~~text
build text/code  -> 270M
query by text    -> 270M
sync-visual      -> 440M
~~~

After an image is embedded, later text queries can compare their 270M text embeddings directly against stored image vectors.

## Commands

Install:

~~~bash
pip install -e ".[semantic]"
~~~

Refresh text/code:

~~~bash
mado-cockpit-semantic --root . --backend embeddinggemma2 --dimension 256 build
~~~

Add or refresh visual evidence:

~~~bash
mado-cockpit-semantic --root . --backend embeddinggemma2 --dimension 256 sync-visual
~~~

Query screenshots with ordinary text:

~~~bash
mado-cockpit-semantic --root . --backend embeddinggemma2 --dimension 256 query "Godot editor showing an Effekseer playback error" --scope evidence --modality image --top-k 5
~~~

The query path does not load the vision encoder.

## Source policy

Visual sync scans image files under:

~~~text
.mado/cockpit/evidence/
~~~

Supported initial suffixes:

~~~text
.png
.jpg
.jpeg
.webp
.bmp
~~~

Repository images outside Cockpit evidence are intentionally not scanned automatically. A game repository may contain thousands of sprites, textures, icons, generated renders, and marketplace assets. Indexing them by default would turn an evidence feature into an accidental asset crawler.

Operators can opt in another project-local source explicitly:

~~~bash
mado-cockpit-semantic --root . --backend embeddinggemma2 sync-visual --no-evidence --path runs/playtest/screenshots
~~~

Explicit paths must stay inside the project root. Symlink files are not followed.

## Evidence-first usage

A worker can submit a screenshot through the existing EvidenceManager. The evidence capture copies it into the evidence bundle, and visual sync discovers that MADO-owned copy.

This keeps semantic retrieval bound to evidence provenance instead of a transient desktop file.

## Storage

The durable format remains:

~~~text
.mado/cockpit/semantic-index/
├─ metadata.json
└─ records.jsonl
~~~

The schema remains mado.semantic-index.v1.

M2.7 adds an explicit modality field. Text records use modality=text. Visual records use modality=image with text=null plus MIME type and byte size.

Both retain source path, source SHA-256, stable semantic record ID, normalized vector, and source scope.

MCC-M2.6 records without a modality field are interpreted as text records for backward compatibility.

## Raw image boundary

The semantic index does not duplicate or base64-encode screenshot pixels.

It stores only:

~~~text
relative provenance path
SHA-256
MIME type
byte size
embedding vector
~~~

The authoritative raw screenshot remains in the evidence bundle.

The initial per-image size ceiling is 32 MiB. Oversized images are reported in skipped_sources.

## Independent partition synchronization

Text and image partitions are synchronized independently.

Text build:
- discovers current text/code;
- reuses unchanged text vectors;
- embeds changed text;
- preserves compatible image records.

Visual sync:
- discovers current visual evidence;
- reuses unchanged image vectors;
- embeds changed/new images;
- removes stale image records;
- preserves text/code records.

This behaves more like a tiny multimodal build system than a one-shot ingestion script.

## Vector-space safety

Image vectors may coexist with text vectors only when schema, model ID, and dimension match.

Visual sync refuses to mix an incompatible existing vector space. Text rebuilds with a changed model or dimension drop incompatible preserved visual records, after which visual sync can recreate them.

Queries continue to fail closed on model or dimension mismatch.

## Why no OCR yet

OCR is useful for exact strings such as stack traces, error codes, file names, and UI labels. It is not the first M2.7 primitive.

Native visual embeddings can retrieve screenshots based on layout, visual state, editor context, charts, rendered output, and other information that a text-extraction-only pipeline loses.

A later hybrid stage can add OCR as another retrieval signal.

## Deterministic fixture backend

The dependency-free hash backend supports structural visual tests. For images it derives fixture vectors from the evidence path, not from pixels.

CI can therefore test discovery, provenance, partition synchronization, vector reuse, stale deletion, result shape, and privacy boundaries without downloading model weights.

It is not a visual retrieval quality benchmark.

## Verification

~~~bash
python scripts/semantic_index_smoke.py
pytest -q tests/test_semantic_index.py
~~~

The smoke verifies text/code indexing, evidence text indexing, visual sync, text-query-to-image plumbing, unchanged image reuse, and image preservation across text rebuilds.

## Security and authority boundary

A retrieved screenshot is evidence, not instruction.

M2.7 does not execute anything visible in a screenshot, trust text shown in an image as instructions, grant capabilities based on visual content, alter persona trust, change Action Policy Gateway outcomes, acquire a Human Control Lease, or upload evidence to a remote embedding API.

## Acceptance target

~~~text
EmbeddingGemma 2 text+vision adapter
440M vision-loaded sync path
270M text-only query path
shared text/image vector space
no text re-embedding required for vision adoption
evidence screenshot discovery
explicit project-local visual intake
repo asset crawl avoided by default
PNG/JPEG/WebP/BMP initial support
32 MiB image ceiling
image SHA-256 provenance
raw image bytes excluded from semantic index
text/image modality records
M2.6 record backward compatibility
independent text and image synchronization
unchanged image vector reuse
stale image removal
compatible visual preservation across text rebuild
vector-space mismatch guard
focused tests
offline multimodal smoke
full Cockpit regression CI
~~~

## Next stage

MCC-M2.8 should extend the same partition model to audio, video, video-frame moments, and time ranges.

The critical requirement is temporal provenance: a semantic hit should return not only a file, but the relevant moment inside it.
