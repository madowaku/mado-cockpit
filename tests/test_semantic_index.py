import json
from pathlib import Path

import pytest

from mado_cockpit.semantic_index import (
    HashEmbeddingBackend,
    SemanticEvidenceIndex,
)


class CountingHashBackend(HashEmbeddingBackend):
    def __init__(self, dimension: int = 128) -> None:
        super().__init__(dimension)
        self.document_calls = 0
        self.document_count = 0
        self.image_calls = 0
        self.image_count = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        self.document_count += len(texts)
        return super().embed_documents(texts)

    def embed_images(self, paths):
        self.image_calls += 1
        self.image_count += len(paths)
        return super().embed_images(paths)


def evidence_dir(tmp_path: Path) -> Path:
    path = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "evidence"
        / "MCC-M2.7"
        / "evb_fixture"
        / "files"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_repo_build_and_query_returns_relevant_file(tmp_path: Path):
    (tmp_path / "alpha.md").write_text(
        "Godot gameplay capture stores frame evidence and test results.\n",
        encoding="utf-8",
    )
    (tmp_path / "beta.md").write_text(
        "Marketing distribution experiments and revenue notes.\n",
        encoding="utf-8",
    )

    backend = HashEmbeddingBackend(dimension=128)
    index = SemanticEvidenceIndex(tmp_path, backend)
    metadata = index.build(include_evidence=False)

    assert metadata["record_count"] == 2
    hits = index.search("Godot gameplay evidence", top_k=1)

    assert hits[0]["source"] == "alpha.md"
    assert hits[0]["scope"] == "repo"
    assert hits[0]["modality"] == "text"
    assert hits[0]["score"] > 0


def test_cockpit_evidence_is_indexed_as_separate_scope(tmp_path: Path):
    evidence = evidence_dir(tmp_path)
    (evidence / "failure.txt").write_text(
        "Effekseer Godot playback failed because the executable was missing.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Cockpit semantic index fixture.\n",
        encoding="utf-8",
    )

    backend = HashEmbeddingBackend(dimension=128)
    index = SemanticEvidenceIndex(tmp_path, backend)
    metadata = index.build()

    assert metadata["source_count"] == 2
    hits = index.search(
        "Effekseer executable missing",
        top_k=3,
        scope="evidence",
    )

    assert len(hits) == 1
    assert hits[0]["scope"] == "evidence"
    assert hits[0]["source"].endswith("failure.txt")


def test_unchanged_chunks_reuse_existing_vectors(tmp_path: Path):
    source = tmp_path / "notes.md"
    source.write_text(
        "semantic evidence retrieval for local code search\n",
        encoding="utf-8",
    )

    first_backend = CountingHashBackend()
    first = SemanticEvidenceIndex(tmp_path, first_backend)
    first_meta = first.build(include_evidence=False)

    assert first_meta["embedded_count"] == 1
    assert first_meta["reused_count"] == 0
    assert first_backend.document_count == 1

    second_backend = CountingHashBackend()
    second = SemanticEvidenceIndex(tmp_path, second_backend)
    second_meta = second.build(include_evidence=False)

    assert second_meta["embedded_count"] == 0
    assert second_meta["reused_count"] == 1
    assert second_backend.document_count == 0

    source.write_text(
        "semantic evidence retrieval changed for decision memory\n",
        encoding="utf-8",
    )

    third_backend = CountingHashBackend()
    third = SemanticEvidenceIndex(tmp_path, third_backend)
    third_meta = third.build(include_evidence=False)

    assert third_meta["embedded_count"] == 1
    assert third_meta["reused_count"] == 0
    assert third_backend.document_count == 1


def test_query_fails_closed_when_backend_does_not_match_index(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "semantic evidence fixture\n",
        encoding="utf-8",
    )
    index = SemanticEvidenceIndex(
        tmp_path,
        HashEmbeddingBackend(dimension=128),
    )
    index.build(include_evidence=False)

    class OtherBackend(HashEmbeddingBackend):
        model_id = "fixture/other-model"

    mismatched = SemanticEvidenceIndex(
        tmp_path,
        OtherBackend(dimension=128),
    )

    with pytest.raises(RuntimeError, match="index model mismatch"):
        mismatched.search("semantic evidence")


def test_explicit_path_cannot_escape_project_root(tmp_path: Path):
    outside = tmp_path.parent / "outside-semantic.txt"
    outside.write_text("outside\n", encoding="utf-8")

    index = SemanticEvidenceIndex(
        tmp_path,
        HashEmbeddingBackend(dimension=128),
    )

    with pytest.raises(RuntimeError, match="escapes project root"):
        index.build(
            include_repo=False,
            include_evidence=False,
            explicit_paths=[outside],
        )


def test_index_persists_machine_readable_metadata(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "MADO local retrieval\n",
        encoding="utf-8",
    )
    index = SemanticEvidenceIndex(
        tmp_path,
        HashEmbeddingBackend(dimension=128),
    )
    index.build(include_evidence=False)

    metadata_path = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "semantic-index"
        / "metadata.json"
    )
    records_path = metadata_path.with_name("records.jsonl")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
    ]

    assert metadata["schema"] == "mado.semantic-index.v1"
    assert metadata["dimension"] == 128
    assert metadata["record_count"] == 1
    assert metadata["modality_counts"] == {"text": 1}
    assert records[0]["schema"] == "mado.semantic-index.v1"
    assert records[0]["modality"] == "text"
    assert len(records[0]["vector"]) == 128


def test_visual_sync_adds_image_without_reembedding_text(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "Godot visual evidence project.\n",
        encoding="utf-8",
    )
    image = evidence_dir(tmp_path) / "godot-error-console.png"
    image.write_bytes(b"fixture-png-bytes")

    text_backend = CountingHashBackend()
    text_index = SemanticEvidenceIndex(tmp_path, text_backend)
    text_index.build()
    assert text_backend.document_count == 1

    visual_backend = CountingHashBackend()
    visual_index = SemanticEvidenceIndex(tmp_path, visual_backend)
    metadata = visual_index.sync_images()

    assert visual_backend.document_count == 0
    assert visual_backend.image_count == 1
    assert metadata["modality_counts"] == {
        "image": 1,
        "text": 1,
    }

    hits = visual_index.search(
        "godot error console",
        top_k=1,
        modality="image",
    )
    assert hits[0]["source"].endswith("godot-error-console.png")
    assert hits[0]["modality"] == "image"
    assert hits[0]["mime_type"] == "image/png"
    assert hits[0]["text"] is None


def test_visual_sync_reuses_unchanged_image_vectors(tmp_path: Path):
    image = evidence_dir(tmp_path) / "godot-crash.png"
    image.write_bytes(b"same-image")

    first_backend = CountingHashBackend()
    first = SemanticEvidenceIndex(tmp_path, first_backend)
    first_meta = first.sync_images()
    assert first_meta["embedded_count"] == 1
    assert first_backend.image_count == 1

    second_backend = CountingHashBackend()
    second = SemanticEvidenceIndex(tmp_path, second_backend)
    second_meta = second.sync_images()
    assert second_meta["embedded_count"] == 0
    assert second_meta["reused_count"] == 1
    assert second_backend.image_count == 0

    image.write_bytes(b"changed-image")

    third_backend = CountingHashBackend()
    third = SemanticEvidenceIndex(tmp_path, third_backend)
    third_meta = third.sync_images()
    assert third_meta["embedded_count"] == 1
    assert third_meta["reused_count"] == 0
    assert third_backend.image_count == 1


def test_text_rebuild_preserves_visual_partition(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "visual partition preservation\n",
        encoding="utf-8",
    )
    image = evidence_dir(tmp_path) / "godot-editor-warning.png"
    image.write_bytes(b"warning-image")

    backend = HashEmbeddingBackend(dimension=128)
    index = SemanticEvidenceIndex(tmp_path, backend)
    index.build()
    visual_meta = index.sync_images()
    assert visual_meta["modality_counts"]["image"] == 1

    (tmp_path / "README.md").write_text(
        "visual partition preservation changed\n",
        encoding="utf-8",
    )
    text_meta = index.build()

    assert text_meta["modality_counts"] == {
        "image": 1,
        "text": 1,
    }
    image_hits = index.search(
        "godot editor warning",
        top_k=1,
        modality="image",
    )
    assert image_hits[0]["source"].endswith("godot-editor-warning.png")


def test_visual_sync_removes_stale_images_but_keeps_text(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "text must survive image cleanup\n",
        encoding="utf-8",
    )
    image = evidence_dir(tmp_path) / "stale-screenshot.png"
    image.write_bytes(b"stale")

    index = SemanticEvidenceIndex(
        tmp_path,
        HashEmbeddingBackend(dimension=128),
    )
    index.build()
    index.sync_images()
    image.unlink()

    metadata = index.sync_images()

    assert metadata["modality_counts"] == {"text": 1}
    text_hits = index.search(
        "text survive cleanup",
        modality="text",
    )
    assert text_hits[0]["source"] == "README.md"


def test_visual_records_do_not_store_raw_image_bytes(tmp_path: Path):
    image = evidence_dir(tmp_path) / "private-screen.png"
    raw = b"super-secret-pixel-payload"
    image.write_bytes(raw)

    index = SemanticEvidenceIndex(
        tmp_path,
        HashEmbeddingBackend(dimension=128),
    )
    index.sync_images()

    records_path = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "semantic-index"
        / "records.jsonl"
    )
    text = records_path.read_text(encoding="utf-8")
    record = json.loads(text.splitlines()[0])

    assert raw.decode("utf-8") not in text
    assert record["modality"] == "image"
    assert record["text"] is None
    assert record["source"].endswith("private-screen.png")
    assert record["size_bytes"] == len(raw)


def test_visual_sync_requires_image_capable_backend(tmp_path: Path):
    image = evidence_dir(tmp_path) / "godot.png"
    image.write_bytes(b"image")

    class TextOnlyBackend(HashEmbeddingBackend):
        supports_images = False

        def embed_images(self, paths):
            raise AssertionError("must not be called")

    index = SemanticEvidenceIndex(
        tmp_path,
        TextOnlyBackend(dimension=128),
    )

    with pytest.raises(RuntimeError, match="image-capable"):
        index.sync_images()


def test_visual_explicit_path_cannot_escape_project_root(tmp_path: Path):
    outside = tmp_path.parent / "outside-visual.png"
    outside.write_bytes(b"outside")

    index = SemanticEvidenceIndex(
        tmp_path,
        HashEmbeddingBackend(dimension=128),
    )

    with pytest.raises(RuntimeError, match="escapes project root"):
        index.sync_images(
            include_evidence=False,
            explicit_paths=[outside],
        )


def test_m26_records_without_modality_remain_searchable(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "backward compatible semantic evidence\n",
        encoding="utf-8",
    )
    index = SemanticEvidenceIndex(
        tmp_path,
        HashEmbeddingBackend(dimension=128),
    )
    index.build(include_evidence=False)

    records_path = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "semantic-index"
        / "records.jsonl"
    )
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
    ]
    records[0].pop("modality")
    records_path.write_text(
        json.dumps(records[0], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    hits = index.search(
        "backward compatible semantic evidence",
        top_k=1,
    )

    assert hits[0]["modality"] == "text"
    assert hits[0]["source"] == "README.md"
