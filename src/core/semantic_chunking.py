import numpy as np

DEFAULT_SIMILARITY_MODE = "chunk"
SUPPORTED_SIMILARITY_MODES = {"chunk", "frame"}
DEFAULT_SEGMENTATION_STRATEGY = "legacy"
SUPPORTED_SEGMENTATION_STRATEGIES = {"legacy", "delta_ema"}


def build_semantic_chunks(
    embeddings,
    timestamps,
    similarity_threshold=0.85,
    max_chunk_duration=5.0,
    min_chunk_size=2,
    similarity_mode=DEFAULT_SIMILARITY_MODE,
    segmentation_strategy=DEFAULT_SEGMENTATION_STRATEGY,
    delta_ema_alpha=0.35,
    delta_high_threshold=0.15,
    delta_low_threshold=0.08,
    delta_rise_frames=2,
    delta_stable_frames=2,
):
    builder = SemanticChunkStreamBuilder(
        similarity_threshold=similarity_threshold,
        max_chunk_duration=max_chunk_duration,
        min_chunk_size=min_chunk_size,
        similarity_mode=similarity_mode,
        segmentation_strategy=segmentation_strategy,
        delta_ema_alpha=delta_ema_alpha,
        delta_high_threshold=delta_high_threshold,
        delta_low_threshold=delta_low_threshold,
        delta_rise_frames=delta_rise_frames,
        delta_stable_frames=delta_stable_frames,
    )
    builder.extend(embeddings, timestamps)
    return builder.finish()


class SemanticChunkStreamBuilder:
    """Incremental chunk builder for long videos (legacy similarity or delta+EMA experiment)."""

    def __init__(
        self,
        similarity_threshold=0.85,
        max_chunk_duration=5.0,
        min_chunk_size=2,
        similarity_mode=DEFAULT_SIMILARITY_MODE,
        segmentation_strategy=DEFAULT_SEGMENTATION_STRATEGY,
        delta_ema_alpha=0.35,
        delta_high_threshold=0.15,
        delta_low_threshold=0.08,
        delta_rise_frames=2,
        delta_stable_frames=2,
    ):
        if similarity_mode not in SUPPORTED_SIMILARITY_MODES:
            raise ValueError(f"Unsupported similarity_mode: {similarity_mode}")
        strategy = str(segmentation_strategy or DEFAULT_SEGMENTATION_STRATEGY).strip().lower()
        if strategy not in SUPPORTED_SEGMENTATION_STRATEGIES:
            raise ValueError(f"Unsupported segmentation_strategy: {segmentation_strategy}")
        self.threshold = float(similarity_threshold)
        self.max_duration = float(max_chunk_duration)
        self.min_size = max(1, int(min_chunk_size))
        self.similarity_mode = similarity_mode
        self.segmentation_strategy = strategy
        self.delta_ema_alpha = float(delta_ema_alpha)
        self.delta_high_threshold = float(delta_high_threshold)
        self.delta_low_threshold = float(delta_low_threshold)
        self.delta_rise_frames = max(1, int(delta_rise_frames))
        self.delta_stable_frames = max(1, int(delta_stable_frames))
        self.chunks = []
        self._current_vectors = []
        self._current_times = []
        self._prev_vector = None
        self._delta_ema = None
        self._high_run = 0

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
            self.chunks.append(_finalize_chunk(self._current_vectors, self._current_times))
            self._current_vectors = []
            self._current_times = []
        return list(self.chunks)

    def _append_frame(self, vector, timestamp):
        if self.segmentation_strategy == "delta_ema":
            self._append_frame_delta_ema(vector, timestamp)
            return
        self._append_frame_legacy(vector, timestamp)

    def _append_frame_legacy(self, vector, timestamp):
        if not self._current_vectors:
            self._current_vectors = [vector]
            self._current_times = [timestamp]
            return

        similarity = _similarity_to_reference(
            vector,
            self._current_vectors,
            similarity_mode=self.similarity_mode,
        )
        duration = timestamp - self._current_times[0]
        should_split = similarity < self.threshold or duration > self.max_duration

        if should_split and len(self._current_vectors) >= self.min_size:
            self.chunks.append(_finalize_chunk(self._current_vectors, self._current_times))
            self._current_vectors = [vector]
            self._current_times = [timestamp]
            return

        self._current_vectors.append(vector)
        self._current_times.append(timestamp)

    def _append_frame_delta_ema(self, vector, timestamp):
        if not self._current_vectors:
            self._current_vectors = [vector]
            self._current_times = [timestamp]
            self._prev_vector = vector
            return

        delta = cosine_distance(vector, self._prev_vector)
        self._prev_vector = vector
        self._delta_ema = _update_ema(self._delta_ema, delta, self.delta_ema_alpha)

        duration = timestamp - self._current_times[0]
        if duration > self.max_duration and len(self._current_vectors) >= self.min_size:
            self._start_new_chunk([vector], [timestamp])
            self._reset_delta_state()
            return

        if self._delta_ema >= self.delta_high_threshold:
            self._high_run += 1
        else:
            self._high_run = 0

        self._current_vectors.append(vector)
        self._current_times.append(timestamp)

        if self._high_run < self.delta_rise_frames:
            return

        cut = len(self._current_vectors) - self.delta_rise_frames
        if cut < self.min_size:
            return

        head_vectors = self._current_vectors[:cut]
        head_times = self._current_times[:cut]
        tail_vectors = self._current_vectors[cut:]
        tail_times = self._current_times[cut:]
        self.chunks.append(_finalize_chunk(head_vectors, head_times))
        self._current_vectors = tail_vectors
        self._current_times = tail_times
        self._high_run = 0

    def _start_new_chunk(self, vectors, timestamps):
        if self._current_vectors:
            self.chunks.append(_finalize_chunk(self._current_vectors, self._current_times))
        self._current_vectors = list(vectors)
        self._current_times = list(timestamps)

    def _reset_delta_state(self):
        self._high_run = 0


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
    max_chunk_duration=5.0,
    min_chunk_size=2,
    similarity_mode=DEFAULT_SIMILARITY_MODE,
    segmentation_strategy=DEFAULT_SEGMENTATION_STRATEGY,
    delta_ema_alpha=0.35,
    delta_high_threshold=0.15,
    delta_low_threshold=0.08,
    delta_rise_frames=2,
    delta_stable_frames=2,
):
    strategy = str(segmentation_strategy or DEFAULT_SEGMENTATION_STRATEGY).strip().lower()
    if strategy not in SUPPORTED_SEGMENTATION_STRATEGIES:
        strategy = DEFAULT_SEGMENTATION_STRATEGY
    return {
        "similarity_threshold": float(similarity_threshold),
        "max_chunk_duration": float(max_chunk_duration),
        "min_chunk_size": int(min_chunk_size),
        "similarity_mode": str(similarity_mode),
        "segmentation_strategy": strategy,
        "delta_ema_alpha": float(delta_ema_alpha),
        "delta_high_threshold": float(delta_high_threshold),
        "delta_low_threshold": float(delta_low_threshold),
        "delta_rise_frames": int(delta_rise_frames),
        "delta_stable_frames": int(delta_stable_frames),
    }


def _similarity_to_reference(vector, current_vectors, similarity_mode):
    if similarity_mode == "frame":
        reference = current_vectors[-1]
    else:
        reference = np.mean(np.asarray(current_vectors, dtype=np.float32), axis=0)
    return cosine_similarity(vector, reference)


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


def cosine_distance(left, right):
    return 1.0 - cosine_similarity(left, right)


def _update_ema(previous, value, alpha):
    current = float(value)
    if previous is None:
        return current
    weight = float(alpha)
    return weight * current + (1.0 - weight) * float(previous)


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
