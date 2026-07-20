import numpy as np

CHUNK_ALGORITHM_VERSION = 7

SPLIT_ADJACENT = "adjacent_below_threshold"
SPLIT_TRANSITION_EXHAUSTED = "transition_exhausted"
SPLIT_MAX_DURATION = "max_duration"
SPLIT_STREAM_END = "stream_end"
SPLIT_MERGED_SHORT = "merged_short"

ACTIVE_CHUNK_CONFIG_KEYS = (
    "similarity_threshold",
    "chunk_edge_threshold",
    "min_chunk_size",
    "min_chunk_duration",
    "max_chunk_duration",
    "algorithm_version",
)

CHUNK_BUILDER_CONFIG_KEYS = (
    "similarity_threshold",
    "chunk_edge_threshold",
    "min_chunk_size",
    "min_chunk_duration",
    "max_chunk_duration",
)


def chunk_builder_kwargs(config=None):
    """Return only runtime chunk-builder fields from a stored chunk_config blob."""
    snapshot = normalize_chunk_config_snapshot(config)
    return {
        key: snapshot[key]
        for key in CHUNK_BUILDER_CONFIG_KEYS
    }


def build_semantic_chunks(
    embeddings,
    timestamps,
    similarity_threshold=0.87,
    chunk_edge_threshold=0.85,
    min_chunk_size=2,
    min_chunk_duration=0.0,
    max_chunk_duration=90.0,
):
    builder = SemanticChunkStreamBuilder(
        similarity_threshold=similarity_threshold,
        chunk_edge_threshold=chunk_edge_threshold,
        min_chunk_size=min_chunk_size,
        min_chunk_duration=min_chunk_duration,
        max_chunk_duration=max_chunk_duration,
    )
    builder.extend(embeddings, timestamps)
    return builder.finish()


class SemanticChunkStreamBuilder:
    """Online chunk partition: every frame belongs to exactly one segment.

    Rules (in order):
    1. Adjacent similarity to the last *core* frame must pass to extend core.
    2. Otherwise one optional *transition* frame may attach via core-mean similarity.
    3. Transition never moves the core anchor; the next frame still compares to core[-1].
    4. Split when rules fail and the open segment is long enough, or max duration fuse fires.
    5. Short segments absorb forced frames into core to avoid orphan fragments.
    """

    def __init__(
        self,
        similarity_threshold=0.87,
        chunk_edge_threshold=0.85,
        min_chunk_size=2,
        min_chunk_duration=0.0,
        max_chunk_duration=90.0,
    ):
        self.best_threshold = float(similarity_threshold)
        edge = float(chunk_edge_threshold)
        self.edge_threshold = min(edge, self.best_threshold - 0.02)
        self.min_size = max(1, int(min_chunk_size))
        self.min_chunk_duration = max(0.0, float(min_chunk_duration))
        self.max_chunk_duration = max(0.0, float(max_chunk_duration))
        self.chunks = []
        self._core_vectors: list[np.ndarray] = []
        self._core_times: list[float] = []
        self._transition_vector: np.ndarray | None = None
        self._transition_time: float | None = None

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
        if self._core_vectors:
            self._flush_segment(SPLIT_STREAM_END)
        records = merge_short_chunks(self.chunks, self.min_chunk_duration)
        return _finalize_chunk_records(records)

    def _segment_frame_count(self) -> int:
        count = len(self._core_vectors)
        if self._transition_vector is not None:
            count += 1
        return count

    def _open_times(self) -> list[float]:
        times = [float(value) for value in self._core_times]
        if self._transition_time is not None:
            times.append(float(self._transition_time))
        return times

    def _segment_duration_through(self, timestamp: float) -> float:
        times = self._open_times()
        if not times:
            return 0.0
        return max(max(times), float(timestamp)) - min(times)

    def _flush_segment(self, split_reason: str):
        if not self._core_vectors:
            return
        vectors = list(self._core_vectors)
        times = [float(value) for value in self._core_times]
        if self._transition_vector is not None and self._transition_time is not None:
            vectors.append(self._transition_vector)
            times.append(float(self._transition_time))
        record = _make_chunk_record(vectors, times, split_reason=split_reason)
        self.chunks.append(record)
        self._reset_open_segment()

    def _reset_open_segment(self):
        self._core_vectors = []
        self._core_times = []
        self._transition_vector = None
        self._transition_time = None

    def _start_segment(self, vector, timestamp):
        self._reset_open_segment()
        self._core_vectors = [vector]
        self._core_times = [float(timestamp)]

    def _append_frame(self, vector, timestamp):
        if not self._core_vectors:
            self._start_segment(vector, timestamp)
            return

        if (
            self.max_chunk_duration > 0
            and self._segment_duration_through(timestamp) >= self.max_chunk_duration
            and self._segment_frame_count() >= self.min_size
        ):
            self._flush_segment(SPLIT_MAX_DURATION)
            self._start_segment(vector, timestamp)
            return

        if cosine_similarity(vector, self._core_vectors[-1]) >= self.best_threshold:
            self._core_vectors.append(vector)
            self._core_times.append(float(timestamp))
            return

        mean_sim = _similarity_to_core_mean(vector, self._core_vectors)
        if self._transition_vector is None and mean_sim >= self.edge_threshold:
            self._transition_vector = vector
            self._transition_time = float(timestamp)
            return

        if self._segment_frame_count() >= self.min_size:
            reason = (
                SPLIT_TRANSITION_EXHAUSTED
                if self._transition_vector is not None
                else SPLIT_ADJACENT
            )
            self._flush_segment(reason)
            self._start_segment(vector, timestamp)
            return

        self._core_vectors.append(vector)
        self._core_times.append(float(timestamp))


def _similarity_to_core_mean(vector, core_vectors):
    reference = np.mean(np.asarray(core_vectors, dtype=np.float32), axis=0)
    return cosine_similarity(vector, reference)


def build_semantic_chunks_streaming(vector_batches, timestamps, **kwargs):
    """Build chunks from per-batch frame vectors without materializing a full matrix first."""
    builder = SemanticChunkStreamBuilder(**chunk_builder_kwargs(kwargs))
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
    similarity_threshold=0.87,
    chunk_edge_threshold=0.85,
    min_chunk_size=2,
    min_chunk_duration=0.0,
    max_chunk_duration=90.0,
    algorithm_version=CHUNK_ALGORITHM_VERSION,
):
    best = float(similarity_threshold)
    edge = float(chunk_edge_threshold)
    return {
        "similarity_threshold": best,
        "chunk_edge_threshold": min(edge, best - 0.02),
        "min_chunk_size": int(min_chunk_size),
        "min_chunk_duration": float(min_chunk_duration),
        "max_chunk_duration": max(0.0, float(max_chunk_duration)),
        "algorithm_version": int(algorithm_version),
    }


def normalize_chunk_config_snapshot(config):
    """Reduce stored chunk_config blobs to the active segmentation fields."""
    payload = config if isinstance(config, dict) else {}
    return chunk_config_payload(
        similarity_threshold=payload.get("similarity_threshold", 0.87),
        chunk_edge_threshold=payload.get("chunk_edge_threshold", 0.85),
        min_chunk_size=payload.get("min_chunk_size", 2),
        min_chunk_duration=payload.get("min_chunk_duration", 0.0),
        max_chunk_duration=payload.get("max_chunk_duration", 90.0),
        algorithm_version=payload.get("algorithm_version", 0),
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
            previous["split_reason"] = SPLIT_MERGED_SHORT
            _refresh_chunk_record_bounds(previous)
        else:
            merged.append(_copy_chunk_record(chunk))
    return merged


def _sort_vectors_by_time(vectors, timestamps):
    pairs = sorted(
        zip(timestamps, vectors),
        key=lambda item: float(item[0]),
    )
    if not pairs:
        return [], []
    times, ordered_vectors = zip(*pairs)
    return list(ordered_vectors), [float(value) for value in times]


def _refresh_chunk_record_bounds(record):
    times = [float(value) for value in record.get("times") or []]
    if not times:
        return
    record["start"] = min(times)
    record["end"] = max(times)


def _make_chunk_record(vectors, timestamps, *, split_reason=SPLIT_STREAM_END):
    ordered_vectors, times = _sort_vectors_by_time(list(vectors), list(timestamps))
    return {
        "start": times[0],
        "end": times[-1],
        "vectors": ordered_vectors,
        "times": times,
        "split_reason": str(split_reason),
    }


def _copy_chunk_record(chunk):
    return {
        "start": float(chunk["start"]),
        "end": float(chunk["end"]),
        "vectors": list(chunk["vectors"]),
        "times": list(chunk["times"]),
        "split_reason": str(chunk.get("split_reason", SPLIT_STREAM_END)),
    }


def _finalize_chunk_records(records):
    return [_finalize_chunk(record) for record in records]


def _finalize_chunk(record):
    ordered_vectors, times = _sort_vectors_by_time(record["vectors"], record["times"])
    stacked = np.asarray(ordered_vectors, dtype=np.float32)
    embedding = np.median(stacked, axis=0)
    embedding = _normalize_vector(embedding)
    return {
        "start": float(times[0]),
        "end": float(times[-1]),
        "embedding": embedding,
        "split_reason": str(record.get("split_reason", SPLIT_STREAM_END)),
        "frame_count": len(times),
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
