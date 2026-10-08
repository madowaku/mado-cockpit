from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol, Sequence

SCHEMA = "mado.semantic-index.v1"
DEFAULT_DIMENSION = 256
DEFAULT_MODEL_ID = "google/embeddinggemma-2"
DEFAULT_CHUNK_CHARS = 1800
DEFAULT_CHUNK_OVERLAP = 240
MAX_IMAGE_BYTES = 32 * 1024 * 1024

_TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".gd", ".h", ".hpp",
    ".html", ".java", ".js", ".json", ".jsonl", ".jsx", ".kt", ".kts",
    ".md", ".mjs", ".py", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".txt", ".xml", ".yaml", ".yml",
}
_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
}
_EXCLUDED_DIRS = {
    ".git", ".mado", ".pytest_cache", ".ruff_cache", ".venv", "build",
    "dist", "node_modules", "__pycache__",
}
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right, strict=True))


def _record_modality(record: dict[str, object]) -> str:
    # MCC-M2.6 records predate the explicit modality field.
    return str(record.get("modality", "text"))


class EmbeddingBackend(Protocol):
    model_id: str
    dimension: int
    supports_images: bool

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_images(self, paths: Sequence[Path]) -> list[list[float]]:
        ...


class HashEmbeddingBackend:
    """Dependency-free deterministic backend for tests and offline smoke runs.

    Image embeddings intentionally derive from the image path rather than pixels.
    This backend validates orchestration and provenance only; it is not a quality
    substitute for EmbeddingGemma 2.
    """

    model_id = "mado/hash-embedding-v1"
    supports_images = True

    def __init__(self, dimension: int = DEFAULT_DIMENSION) -> None:
        if dimension < 8:
            raise ValueError("dimension must be >= 8")
        self.dimension = dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        return _normalize(vector)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_images(self, paths: Sequence[Path]) -> list[list[float]]:
        return [
            self._embed(
                " ".join(
                    token
                    for part in path.parts[-4:]
                    for token in re.split(r"[^A-Za-z0-9_]+", part)
                    if token
                )
            )
            for path in paths
        ]


class EmbeddingGemma2Backend:
    """Lazy Sentence Transformers adapter for local EmbeddingGemma 2."""

    model_id = DEFAULT_MODEL_ID

    def __init__(
        self,
        *,
        dimension: int = DEFAULT_DIMENSION,
        device: str | None = None,
        enable_vision: bool = False,
    ) -> None:
        if dimension not in {128, 256, 512, 768}:
            raise ValueError(
                "EmbeddingGemma 2 dimension must be 128, 256, 512, or 768"
            )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'EmbeddingGemma 2 requires the semantic extra: '
                'pip install -e ".[semantic]"'
            ) from exc

        config_kwargs: dict[str, object]
        if enable_vision:
            # Text + image only: keep audio weights out of memory.
            config_kwargs = {"audio_config": None}
        else:
            # MCC-M2.6 text-only footprint.
            config_kwargs = {
                "vision_config": None,
                "audio_config": None,
            }

        kwargs: dict[str, object] = {
            "truncate_dim": dimension,
            "config_kwargs": config_kwargs,
        }
        if device:
            kwargs["device"] = device
        self._model = SentenceTransformer(self.model_id, **kwargs)
        self.dimension = dimension
        self.supports_images = enable_vision

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._model.encode(
            list(texts),
            prompt_name="Document",
            normalize_embeddings=True,
            truncate_dim=self.dimension,
            show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in result.tolist()]

    def embed_query(self, text: str) -> list[float]:
        result = self._model.encode(
            text,
            prompt_name="SearchQuery",
            normalize_embeddings=True,
            truncate_dim=self.dimension,
            show_progress_bar=False,
        )
        return [float(value) for value in result.tolist()]

    def embed_images(self, paths: Sequence[Path]) -> list[list[float]]:
        if not self.supports_images:
            raise RuntimeError(
                "image embedding requires a vision-enabled EmbeddingGemma 2 backend"
            )
        vectors: list[list[float]] = []
        for path in paths:
            # Media inputs use no text prompt. This keeps the image in the same
            # vector space as SearchQuery text embeddings.
            result = self._model.encode(
                {"image": str(path)},
                normalize_embeddings=True,
                truncate_dim=self.dimension,
                show_progress_bar=False,
            )
            vectors.append([float(value) for value in result.tolist()])
        return vectors


@dataclass(frozen=True)
class SourceChunk:
    source: str
    scope: str
    chunk_index: int
    text: str
    source_sha256: str
    chunk_sha256: str

    @property
    def id(self) -> str:
        payload = (
            f"{self.scope}\0{self.source}\0{self.chunk_index}\0"
            f"{self.chunk_sha256}"
        )
        return "sem_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class ImageSource:
    source: str
    scope: str
    path: Path
    source_sha256: str
    size_bytes: int
    mime_type: str

    @property
    def id(self) -> str:
        # Keep the same logical identity recipe as text chunks so the schema
        # remains backward-compatible with MCC-M2.6.
        payload = f"{self.scope}\0{self.source}\00\0{self.source_sha256}"
        return "sem_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


class SemanticEvidenceIndex:
    def __init__(
        self,
        root: Path | str,
        backend: EmbeddingBackend,
        *,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self.root = Path(root).resolve()
        self.backend = backend
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap
        if chunk_chars < 256:
            raise ValueError("chunk_chars must be >= 256")
        if chunk_overlap < 0 or chunk_overlap >= chunk_chars:
            raise ValueError(
                "chunk_overlap must be >= 0 and smaller than chunk_chars"
            )

        self.index_dir = self.root / ".mado" / "cockpit" / "semantic-index"
        self.metadata_path = self.index_dir / "metadata.json"
        self.records_path = self.index_dir / "records.jsonl"

    def build(
        self,
        *,
        include_repo: bool = True,
        include_evidence: bool = True,
        explicit_paths: Iterable[Path | str] = (),
    ) -> dict[str, object]:
        """Synchronize the text/code partition while preserving visual records."""

        sources = self._discover_text_sources(
            include_repo=include_repo,
            include_evidence=include_evidence,
            explicit_paths=explicit_paths,
        )
        chunks: list[SourceChunk] = []
        skipped: list[str] = []
        for path, scope in sources:
            try:
                chunks.extend(self._chunks_for_path(path, scope))
            except (UnicodeDecodeError, OSError):
                skipped.append(self._relative(path))

        previous = self._load_records()
        can_reuse = self._metadata_matches_backend()
        previous_text = [
            record
            for record in previous
            if _record_modality(record) == "text"
        ]
        preserved_visual = [
            record
            for record in previous
            if _record_modality(record) != "text"
        ]

        previous_by_key = {
            (
                str(record.get("scope", "")),
                str(record.get("source", "")),
                int(record.get("chunk_index", -1)),
                str(record.get("chunk_sha256", "")),
            ): record
            for record in previous_text
        } if can_reuse else {}

        records: list[dict[str, object]] = list(preserved_visual)
        pending: list[SourceChunk] = []
        reused = 0
        for chunk in chunks:
            key = (
                chunk.scope,
                chunk.source,
                chunk.chunk_index,
                chunk.chunk_sha256,
            )
            old = previous_by_key.get(key)
            if old is not None:
                records.append(old)
                reused += 1
            else:
                pending.append(chunk)

        vectors = self.backend.embed_documents(
            [chunk.text for chunk in pending]
        )
        if len(vectors) != len(pending):
            raise RuntimeError(
                "embedding backend returned an unexpected vector count"
            )
        for chunk, vector in zip(pending, vectors, strict=True):
            normalized = _normalize(vector)
            self._require_dimension(normalized)
            records.append(self._text_record(chunk, normalized))

        records = self._sort_records(records)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._write_records(records)

        metadata = self._metadata_payload(
            records,
            operation="text_sync",
            embedded_count=len(pending),
            reused_count=reused,
            skipped_sources=skipped,
            previous=self._load_metadata(),
        )
        self._write_json_atomic(self.metadata_path, metadata)
        return metadata

    def sync_images(
        self,
        *,
        include_evidence: bool = True,
        explicit_paths: Iterable[Path | str] = (),
    ) -> dict[str, object]:
        """Synchronize image evidence while preserving text/code vectors.

        Repository images are intentionally not scanned by default. M2.7 targets
        visual evidence, not arbitrary game art or generated asset trees.
        """

        if not self.backend.supports_images:
            raise RuntimeError(
                "visual sync requires an image-capable embedding backend"
            )

        images, skipped = self._discover_image_sources(
            include_evidence=include_evidence,
            explicit_paths=explicit_paths,
        )
        previous = self._load_records()
        can_reuse = self._metadata_matches_backend()

        preserved = [
            record
            for record in previous
            if _record_modality(record) != "image"
        ]
        previous_images = [
            record
            for record in previous
            if _record_modality(record) == "image"
        ]
        previous_by_key = {
            (
                str(record.get("scope", "")),
                str(record.get("source", "")),
                str(record.get("source_sha256", "")),
            ): record
            for record in previous_images
        } if can_reuse else {}

        records: list[dict[str, object]] = list(preserved)
        pending: list[ImageSource] = []
        reused = 0
        for image in images:
            key = (
                image.scope,
                image.source,
                image.source_sha256,
            )
            old = previous_by_key.get(key)
            if old is not None:
                records.append(old)
                reused += 1
            else:
                pending.append(image)

        vectors = self.backend.embed_images(
            [image.path for image in pending]
        )
        if len(vectors) != len(pending):
            raise RuntimeError(
                "image embedding backend returned an unexpected vector count"
            )
        for image, vector in zip(pending, vectors, strict=True):
            normalized = _normalize(vector)
            self._require_dimension(normalized)
            records.append(self._image_record(image, normalized))

        records = self._sort_records(records)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._write_records(records)

        metadata = self._metadata_payload(
            records,
            operation="image_sync",
            embedded_count=len(pending),
            reused_count=reused,
            skipped_sources=skipped,
            previous=self._load_metadata(),
        )
        self._write_json_atomic(self.metadata_path, metadata)
        return metadata

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        scope: str | None = None,
        modality: str | None = None,
    ) -> list[dict[str, object]]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if modality not in {None, "text", "image"}:
            raise ValueError("modality must be text, image, or None")

        records = self._load_records()
        if not records:
            raise RuntimeError("semantic index is empty; run build first")
        self._require_compatible_metadata()

        query_vector = _normalize(self.backend.embed_query(query))
        self._require_dimension(query_vector)

        hits: list[dict[str, object]] = []
        for record in records:
            record_modality = _record_modality(record)
            if scope and record.get("scope") != scope:
                continue
            if modality and record_modality != modality:
                continue
            vector = record.get("vector")
            if not isinstance(vector, list):
                continue
            hit = {
                "id": record["id"],
                "score": _dot(
                    query_vector,
                    [float(value) for value in vector],
                ),
                "scope": record["scope"],
                "modality": record_modality,
                "source": record["source"],
                "chunk_index": record.get("chunk_index", 0),
                "source_sha256": record["source_sha256"],
                "chunk_sha256": record.get(
                    "chunk_sha256",
                    record["source_sha256"],
                ),
                "mime_type": record.get("mime_type"),
                "size_bytes": record.get("size_bytes"),
                "text": record.get("text"),
            }
            hits.append(hit)

        hits.sort(
            key=lambda item: (
                -float(item["score"]),
                str(item["source"]),
                int(item["chunk_index"]),
            )
        )
        return hits[:top_k]

    def status(self) -> dict[str, object]:
        if not self.metadata_path.exists():
            return {
                "schema": SCHEMA,
                "status": "missing",
                "index_dir": self._relative(self.index_dir),
            }
        metadata = json.loads(
            self.metadata_path.read_text(encoding="utf-8")
        )
        metadata["status"] = (
            "ready" if self.records_path.exists() else "incomplete"
        )
        metadata["index_dir"] = self._relative(self.index_dir)
        return metadata

    def _discover_text_sources(
        self,
        *,
        include_repo: bool,
        include_evidence: bool,
        explicit_paths: Iterable[Path | str],
    ) -> list[tuple[Path, str]]:
        discovered: dict[Path, str] = {}

        if include_repo:
            for path in self.root.rglob("*"):
                if self._is_repo_text_source(path):
                    discovered[path.resolve()] = "repo"

        if include_evidence:
            evidence_root = self.root / ".mado" / "cockpit" / "evidence"
            if evidence_root.exists():
                for path in evidence_root.rglob("*"):
                    if self._is_text_file(path):
                        discovered[path.resolve()] = "evidence"

        for raw in explicit_paths:
            path = self._resolve_explicit(raw)
            if path.is_dir():
                for child in path.rglob("*"):
                    if self._is_text_file(child):
                        discovered[child.resolve()] = "explicit"
            elif self._is_text_file(path):
                discovered[path] = "explicit"
            elif self._is_image_file(path):
                # Visual files are handled by sync_images.
                continue
            else:
                raise RuntimeError(f"unsupported semantic source: {path}")

        return sorted(
            discovered.items(),
            key=lambda item: self._relative(item[0]),
        )

    def _discover_image_sources(
        self,
        *,
        include_evidence: bool,
        explicit_paths: Iterable[Path | str],
    ) -> tuple[list[ImageSource], list[str]]:
        discovered: dict[Path, str] = {}
        skipped: list[str] = []

        if include_evidence:
            evidence_root = self.root / ".mado" / "cockpit" / "evidence"
            if evidence_root.exists():
                for path in evidence_root.rglob("*"):
                    if self._is_image_file(path):
                        discovered[path.resolve()] = "evidence"

        for raw in explicit_paths:
            path = self._resolve_explicit(raw)
            if path.is_dir():
                for child in path.rglob("*"):
                    if self._is_image_file(child):
                        discovered[child.resolve()] = "explicit"
            elif self._is_image_file(path):
                discovered[path] = "explicit"
            elif self._is_text_file(path):
                continue
            else:
                raise RuntimeError(f"unsupported visual source: {path}")

        images: list[ImageSource] = []
        for path, scope in sorted(
            discovered.items(),
            key=lambda item: self._relative(item[0]),
        ):
            try:
                size = path.stat().st_size
                if size > MAX_IMAGE_BYTES:
                    skipped.append(
                        f"{self._relative(path)}: image exceeds "
                        f"{MAX_IMAGE_BYTES} bytes"
                    )
                    continue
                data = path.read_bytes()
            except OSError:
                skipped.append(
                    f"{self._relative(path)}: unreadable"
                )
                continue

            mime_type, _ = mimetypes.guess_type(path.name)
            images.append(
                ImageSource(
                    source=self._relative(path),
                    scope=scope,
                    path=path,
                    source_sha256=_sha256(data),
                    size_bytes=size,
                    mime_type=mime_type or "application/octet-stream",
                )
            )
        return images, skipped

    def _resolve_explicit(self, raw: Path | str) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        self._require_inside_root(path)
        return path

    def _is_repo_text_source(self, path: Path) -> bool:
        if not self._is_text_file(path):
            return False
        relative = path.relative_to(self.root)
        if any(part in _EXCLUDED_DIRS for part in relative.parts[:-1]):
            return False
        return True

    def _is_text_file(self, path: Path) -> bool:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in _TEXT_SUFFIXES
        )

    def _is_image_file(self, path: Path) -> bool:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in _IMAGE_SUFFIXES
        )

    def _chunks_for_path(self, path: Path, scope: str) -> list[SourceChunk]:
        self._require_inside_root(path.resolve())
        data = path.read_bytes()
        text = data.decode("utf-8")
        source_sha = _sha256(data)
        relative = self._relative(path)

        pieces = _chunk_text(
            text,
            max_chars=self.chunk_chars,
            overlap=self.chunk_overlap,
        )
        return [
            SourceChunk(
                source=relative,
                scope=scope,
                chunk_index=index,
                text=piece,
                source_sha256=source_sha,
                chunk_sha256=_sha256(piece.encode("utf-8")),
            )
            for index, piece in enumerate(pieces)
        ]

    def _text_record(
        self,
        chunk: SourceChunk,
        vector: list[float],
    ) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "id": chunk.id,
            "scope": chunk.scope,
            "modality": "text",
            "source": chunk.source,
            "chunk_index": chunk.chunk_index,
            "source_sha256": chunk.source_sha256,
            "chunk_sha256": chunk.chunk_sha256,
            "text": chunk.text,
            "vector": vector,
        }

    def _image_record(
        self,
        image: ImageSource,
        vector: list[float],
    ) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "id": image.id,
            "scope": image.scope,
            "modality": "image",
            "source": image.source,
            "chunk_index": 0,
            "source_sha256": image.source_sha256,
            "chunk_sha256": image.source_sha256,
            "mime_type": image.mime_type,
            "size_bytes": image.size_bytes,
            "text": None,
            "vector": vector,
        }

    def _metadata_payload(
        self,
        records: Sequence[dict[str, object]],
        *,
        operation: str,
        embedded_count: int,
        reused_count: int,
        skipped_sources: Sequence[str],
        previous: dict[str, object] | None,
    ) -> dict[str, object]:
        counts: dict[str, int] = {}
        scopes: dict[str, int] = {}
        for record in records:
            modality = _record_modality(record)
            counts[modality] = counts.get(modality, 0) + 1
            scope = str(record.get("scope", "unknown"))
            scopes[scope] = scopes.get(scope, 0) + 1

        now = _now()
        metadata: dict[str, object] = {
            "schema": SCHEMA,
            "model_id": self.backend.model_id,
            "dimension": self.backend.dimension,
            "chunk_chars": self.chunk_chars,
            "chunk_overlap": self.chunk_overlap,
            "record_count": len(records),
            "source_count": len(
                {
                    (
                        str(record.get("scope", "")),
                        str(record.get("source", "")),
                    )
                    for record in records
                }
            ),
            "modality_counts": counts,
            "scope_counts": scopes,
            "last_operation": operation,
            "embedded_count": embedded_count,
            "reused_count": reused_count,
            "skipped_sources": list(skipped_sources),
            "built_at": now,
        }
        if previous:
            for key in ("last_text_sync", "last_image_sync"):
                if key in previous:
                    metadata[key] = previous[key]
        if operation == "text_sync":
            metadata["last_text_sync"] = now
        if operation == "image_sync":
            metadata["last_image_sync"] = now
        return metadata

    def _metadata_matches_backend(self) -> bool:
        metadata = self._load_metadata()
        if metadata is None:
            return False
        return (
            metadata.get("schema") == SCHEMA
            and metadata.get("model_id") == self.backend.model_id
            and metadata.get("dimension") == self.backend.dimension
            and metadata.get("chunk_chars") == self.chunk_chars
            and metadata.get("chunk_overlap") == self.chunk_overlap
        )

    def _require_compatible_metadata(self) -> None:
        metadata = self._load_metadata()
        if metadata is None:
            raise RuntimeError(
                "semantic index metadata is missing; run build first"
            )
        if metadata.get("schema") != SCHEMA:
            raise RuntimeError("unsupported semantic index schema")
        if metadata.get("model_id") != self.backend.model_id:
            raise RuntimeError(
                f"index model mismatch: {metadata.get('model_id')} "
                f"!= {self.backend.model_id}"
            )
        if metadata.get("dimension") != self.backend.dimension:
            raise RuntimeError(
                "index dimension does not match embedding backend"
            )

    def _require_dimension(self, vector: Sequence[float]) -> None:
        if len(vector) != self.backend.dimension:
            raise RuntimeError(
                f"embedding dimension mismatch: expected "
                f"{self.backend.dimension}, got {len(vector)}"
            )

    def _load_metadata(self) -> dict[str, object] | None:
        if not self.metadata_path.exists():
            return None
        try:
            payload = json.loads(
                self.metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _load_records(self) -> list[dict[str, object]]:
        if not self.records_path.exists():
            return []
        records: list[dict[str, object]] = []
        for line in self.records_path.read_text(
            encoding="utf-8"
        ).splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def _sort_records(
        self,
        records: Sequence[dict[str, object]],
    ) -> list[dict[str, object]]:
        return sorted(
            records,
            key=lambda item: (
                str(item.get("scope", "")),
                str(item.get("source", "")),
                _record_modality(item),
                int(item.get("chunk_index", 0)),
            ),
        )

    def _write_records(
        self,
        records: Sequence[dict[str, object]],
    ) -> None:
        temp = self.records_path.with_suffix(".jsonl.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                handle.write("\n")
        os.replace(temp, self.records_path)

    def _write_json_atomic(
        self,
        path: Path,
        payload: dict[str, object],
    ) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)

    def _require_inside_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeError(
                f"semantic source escapes project root: {path}"
            ) from exc

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()


def _chunk_text(
    text: str,
    *,
    max_chars: int,
    overlap: int,
) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[str] = []
    start = 0
    length = len(stripped)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            newline = stripped.rfind(
                "\n",
                start + max_chars // 2,
                end,
            )
            if newline > start:
                end = newline
        piece = stripped[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        next_start = max(end - overlap, start + 1)
        start = next_start
    return chunks


def _backend(
    name: str,
    *,
    dimension: int,
    device: str | None,
    enable_vision: bool = False,
) -> EmbeddingBackend:
    if name == "hash":
        return HashEmbeddingBackend(dimension=dimension)
    if name == "embeddinggemma2":
        return EmbeddingGemma2Backend(
            dimension=dimension,
            device=device,
            enable_vision=enable_vision,
        )
    raise RuntimeError(f"unknown semantic backend: {name}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MADO local semantic evidence index"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--backend",
        choices=["hash", "embeddinggemma2"],
        default="embeddinggemma2",
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=DEFAULT_DIMENSION,
        choices=[128, 256, 512, 768],
    )
    parser.add_argument("--device", default=None)
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    build = sub.add_parser(
        "build",
        help="Synchronize repository and Cockpit evidence text",
    )
    build.add_argument(
        "--repo",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    build.add_argument(
        "--evidence",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    build.add_argument(
        "--path",
        action="append",
        default=[],
    )

    visual = sub.add_parser(
        "sync-visual",
        help="Synchronize screenshot/image evidence without re-embedding text",
    )
    visual.add_argument(
        "--evidence",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    visual.add_argument(
        "--path",
        action="append",
        default=[],
    )

    query = sub.add_parser(
        "query",
        help="Search the local semantic index",
    )
    query.add_argument("text")
    query.add_argument("--top-k", type=int, default=8)
    query.add_argument(
        "--scope",
        choices=["repo", "evidence", "explicit"],
        default=None,
    )
    query.add_argument(
        "--modality",
        choices=["text", "image"],
        default=None,
    )
    query.add_argument("--json", action="store_true")

    sub.add_parser(
        "status",
        help="Show semantic index metadata",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root)

    if args.command == "status":
        probe = SemanticEvidenceIndex(
            root,
            HashEmbeddingBackend(dimension=args.dimension),
        )
        print(
            json.dumps(
                probe.status(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    enable_vision = args.command == "sync-visual"
    backend = _backend(
        args.backend,
        dimension=args.dimension,
        device=args.device,
        enable_vision=enable_vision,
    )
    index = SemanticEvidenceIndex(root, backend)

    if args.command == "build":
        result = index.build(
            include_repo=args.repo,
            include_evidence=args.evidence,
            explicit_paths=args.path,
        )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "sync-visual":
        result = index.sync_images(
            include_evidence=args.evidence,
            explicit_paths=args.path,
        )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    hits = index.search(
        args.text,
        top_k=args.top_k,
        scope=args.scope,
        modality=args.modality,
    )
    if args.json:
        print(
            json.dumps(
                hits,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    for hit in hits:
        if hit["modality"] == "image":
            preview = (
                f'{hit.get("mime_type") or "image"} '
                f'{hit.get("size_bytes") or 0}B'
            )
        else:
            preview = " ".join(
                str(hit.get("text") or "").split()
            )[:180]
        print(
            f'{float(hit["score"]):.4f}\t'
            f'{hit["scope"]}\t'
            f'{hit["modality"]}\t'
            f'{hit["source"]}#{hit["chunk_index"]}\t'
            f'{preview}'
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
