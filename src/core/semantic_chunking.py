import numpy as np

ACTIVE_CHUNK_CONFIG_KEYS = (
    "similarity_threshold",
    "min_chunk_size",
    "min_chunk_duration",
)


def build_semantic_chunks(
    embeddings,
    timestamps,
    similarity_threshold=0.85,
    min_chunk_size=2,
    min_chunk_duration=0.0,
):
    builder = SemanticChunkStreamBuilder(
        similarity_threshold=similarity_threshold,
        min_chunk_size=min_chunk_size,
        min_chunk_duration=min_chunk_duration,
    )
    builder.extend(embeddings, timestamps)
    return builder.finish()


class SemanticChunkStreamBuilder:
    """Incremental dual-check chunk builder for long videos."""

    def __init__(
        self,
        similarity_threshold=0.85,
        min_chunk_size=2,
        min_chunk_duration=0.0,
    ):
        self.cut_threshold = float(similarity_threshold)
        self.min_size = max(1, int(min_chunk_size))
        self.min_chunk_duration = max(0.0, float(min_chunk_duration))
        self.chunks = []
        self._current_vectors = []
        self._current_times = []

    def extend(self, embeddings, timestamps):
        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.size == 0:
            return
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.ndim != 2:
            raise ValueError("embeddings must be a 2D array")
        times = np.asarray(timestamps, dtype=np.float32).reshape(-1)
        if len(vectors) != len(times):
            raise ValueError("embeddings and timestamps must have the same length")
        for index in range(len(vectors)):
            self._append_frame(vectors[index], float(times[index]))

    def finish(self):
        if self._current_vectors:
            self.chunks.append(_make_chunk_record(self._current_vectors, self._current_times))
            self._current_vectors = []
            self._current_times = []
        records = merge_short_chunks(self.chunks, self.min_chunk_duration)
        return _finalize_chunk_records(records)

    def _append_frame(self, vector, timestamp):
        if not self._current_vectors:
            self._current_vectors = [vector]
            self._current_times = [timestamp]
            return

        if _frame_stays_in_chunk(vector, self._current_vectors, self.cut_threshold):
            self._current_vectors.append(vector)
            self._current_times.append(timestamp)
            return

        if len(self._current_vectors) >= self.min_size:
            self.chunks.append(_make_chunk_record(self._current_vectors, self._current_times))
            self._current_vectors = [vector]
            self._current_times = [timestamp]
            return

        self._current_vectors.append(vector)
        self._current_times.append(timestamp)


def _frame_stays_in_chunk(vector, current_vectors, threshold):
    cut_threshold = float(threshold)
    if cosine_similarity(vector, current_vectors[-1]) >= cut_threshold:
        return True
    return _similarity_to_chunk_mean(vector, current_vectors) >= cut_threshold


def _similarity_to_chunk_mean(vector, current_vectors):
    reference = np.mean(np.asarray(current_vectors, dtype=np.float32), axis=0)
    return cosine_similarity(vector, reference)


def build_semantic_chunks_streaming(vector_batches, timestamps, **kwargs):
    """Build chunks from per-batch frame vectors without materializing a full matrix first."""
    builder = SemanticChunkStreamBuilder(**kwargs)
    if not vector_batches:
        return builder.finish()
    times = np.asarray(timestamps, dtype=np.float32).reshape(-1)
    offset = 0
    for batch in vector_batches:
        batch_vectors = np.asarray(batch, dtype=np.float32)
        if batch_vectors.size == 0:
            continue
        if batch_vectors.ndim == 1:
            batch_vectors = batch_vectors.reshape(1, -1)
        end = offset + batch_vectors.shape[0]
        if end > len(times):
            raise ValueError("streaming chunk timestamps shorter than vector batches")
        builder.extend(batch_vectors, times[offset:end])
        offset = end
    if offset != len(times):
        raise ValueError("streaming chunk timestamps longer than vector batches")
    return builder.finish()


def chunk_config_payload(
    similarity_threshold=0.85,
    min_chunk_size=2,
    min_chunk_duration=0.0,
):
    return {
        "similarity_threshold": float(similarity_threshold),
        "min_chunk_size": int(min_chunk_size),
        "min_chunk_duration": float(min_chunk_duration),
    }


def normalize_chunk_config_snapshot(config):
    """Reduce stored chunk_config blobs to the active segmentation fields."""
    payload = config if isinstance(config, dict) else {}
    return chunk_config_payload(
        similarity_threshold=payload.get("similarity_threshold", 0.85),
        min_chunk_size=payload.get("min_chunk_size", 2),
        min_chunk_duration=payload.get("min_chunk_duration", 0.0),
    )


def merge_short_chunks(chunks, min_duration):
    if not chunks or min_duration <= 0:
        return list(chunks)

    merged = []
    for chunk in chunks:
        duration = float(chunk["end"]) - float(chunk["start"])
        if duration < min_duration and merged:
            previous = merged[-1]
            previous["vectors"].extend(chunk["vectors"])
            previous["times"].extend(chunk["times"])
            previous["end"] = float(chunk["end"])
        else:
            merged.append(_copy_chunk_record(chunk))
    return merged


def _make_chunk_record(vectors, timestamps):
    times = [float(value) for value in timestamps]
    return {
        "start": times[0],
        "end": times[-1],
        "vectors": list(vectors),
        "times": times,
    }


def _copy_chunk_record(chunk):
    return {
        "start": float(chunk["start"]),
        "end": float(chunk["end"]),
        "vectors": list(chunk["vectors"]),
        "times": list(chunk["times"]),
    }


def _finalize_chunk_records(records):
    return [_finalize_chunk(record["vectors"], record["times"]) for record in records]


def _finalize_chunk(vectors, timestamps):
    embedding = np.mean(np.asarray(vectors, dtype=np.float32), axis=0)
    embedding = _normalize_vector(embedding)
    return {
        "start": float(timestamps[0]),
        "end": float(timestamps[-1]),
        "embedding": embedding,
    }


def cosine_similarity(left, right):
    left_vector = _normalize_vector(np.asarray(left, dtype=np.float32))
    right_vector = _normalize_vector(np.asarray(right, dtype=np.float32))
    return float(np.dot(left_vector, right_vector))


def pack_chunks(chunks):
    if not chunks:
        return None

    return {
        "start": np.asarray([chunk["start"] for chunk in chunks], dtype=np.float32),
        "end": np.asarray([chunk["end"] for chunk in chunks], dtype=np.float32),
        "embedding": np.asarray([chunk["embedding"] for chunk in chunks], dtype=np.float32),
    }


def unpack_chunks(payload):
    if not isinstance(payload, dict):
        return []

    starts = np.asarray(payload.get("start", []), dtype=np.float32)
    ends = np.asarray(payload.get("end", []), dtype=np.float32)
    embeddings = np.asarray(payload.get("embedding", []), dtype=np.float32)
    if len(starts) != len(ends) or len(starts) != len(embeddings):
        return []

    return [
        {
            "start": float(starts[index]),
            "end": float(ends[index]),
            "embedding": embeddings[index],
        }
        for index in range(len(starts))
    ]


def _normalize_vector(vector):
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return vector.astype(np.float32, copy=False)
    return (vector / norm).astype(np.float32, copy=False)
