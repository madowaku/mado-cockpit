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

    def embed_documents(self, texts):
        self.document_calls += 1
        self.document_count += len(texts)
        return super().embed_documents(texts)


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
    assert hits[0]["score"] > 0


def test_cockpit_evidence_is_indexed_as_separate_scope(tmp_path: Path):
    evidence = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "evidence"
        / "MCC-M2.6"
        / "evb_fixture"
        / "files"
    )
    evidence.mkdir(parents=True)
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
    assert records[0]["schema"] == "mado.semantic-index.v1"
    assert len(records[0]["vector"]) == 128
