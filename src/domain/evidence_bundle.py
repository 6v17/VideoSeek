from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


EVIDENCE_BUNDLE_SCHEMA_VERSION = 1


class EvidenceBundleValidationError(ValueError):
    """Raised when an evidence bundle payload fails schema validation."""


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceBundleValidationError(f"{field_name} must be an object")
    return dict(value)


def _require_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise EvidenceBundleValidationError(f"{field_name} is required")
    return text


def _require_number(value: object, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceBundleValidationError(f"{field_name} must be a number") from exc


def _require_int(value: object, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceBundleValidationError(f"{field_name} must be an integer") from exc


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceBundleValidationError(f"{field_name} must be a boolean")
    return value


def _require_list(value: object, field_name: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise EvidenceBundleValidationError(f"{field_name} must be a list")
    return list(value)


@dataclass(frozen=True)
class EvidenceObject:
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class ChunkSample:
    timestamp_sec: float
    strategy: str


@dataclass(frozen=True)
class ObjectDetectionEvidence:
    source: str
    objects: tuple[EvidenceObject, ...] = ()


@dataclass(frozen=True)
class ImageCaptionEvidence:
    source: str
    text: str


@dataclass(frozen=True)
class VisionEvidence:
    object_detection: ObjectDetectionEvidence | None = None
    image_caption: ImageCaptionEvidence | None = None


@dataclass(frozen=True)
class ChunkEvidence:
    vision: VisionEvidence = field(default_factory=VisionEvidence)
    audio: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_index: int
    start_sec: float
    end_sec: float
    sample: ChunkSample
    evidence: ChunkEvidence
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceVideo:
    video_id: str
    video_path: str
    video_rel_path: str = ""
    library_path: str = ""
    duration_sec: float | None = None
    source_exists: bool | None = None


@dataclass(frozen=True)
class ChunkSourceProvenance:
    search_profile_id: str
    search_provider: str
    search_variant: str


@dataclass(frozen=True)
class EvidenceProvenance:
    understanding_profile_id: str
    components: dict[str, str]
    chunk_source: ChunkSourceProvenance
    keyframe_strategy: str
    generated_at: str


@dataclass(frozen=True)
class VideoSummary:
    text: str
    source: str = "remote_vlm"


@dataclass(frozen=True)
class EvidenceBundle:
    schema_version: int
    video: EvidenceVideo
    provenance: EvidenceProvenance
    chunks: tuple[EvidenceChunk, ...]
    summary: VideoSummary | None = None


def _parse_bbox(raw_bbox: object, field_name: str) -> tuple[float, float, float, float]:
    values = _require_list(raw_bbox, field_name)
    if len(values) != 4:
        raise EvidenceBundleValidationError(f"{field_name} must contain exactly 4 numbers")
    return tuple(_require_number(value, f"{field_name}[{index}]") for index, value in enumerate(values))


def _parse_evidence_object(raw_object: object, field_name: str) -> EvidenceObject:
    payload = _require_mapping(raw_object, field_name)
    return EvidenceObject(
        label=_require_text(payload.get("label"), f"{field_name}.label"),
        confidence=_require_number(payload.get("confidence"), f"{field_name}.confidence"),
        bbox=_parse_bbox(payload.get("bbox"), f"{field_name}.bbox"),
    )


def _parse_object_detection(raw_value: object, field_name: str) -> ObjectDetectionEvidence | None:
    if raw_value is None:
        return None
    payload = _require_mapping(raw_value, field_name)
    raw_objects = payload.get("objects", [])
    objects = tuple(
        _parse_evidence_object(item, f"{field_name}.objects[{index}]")
        for index, item in enumerate(_require_list(raw_objects, f"{field_name}.objects"))
    )
    return ObjectDetectionEvidence(
        source=_require_text(payload.get("source"), f"{field_name}.source"),
        objects=objects,
    )


def _parse_image_caption(raw_value: object, field_name: str) -> ImageCaptionEvidence | None:
    if raw_value is None:
        return None
    payload = _require_mapping(raw_value, field_name)
    return ImageCaptionEvidence(
        source=_require_text(payload.get("source"), f"{field_name}.source"),
        text=_require_text(payload.get("text"), f"{field_name}.text"),
    )


def _parse_vision_evidence(raw_value: object, field_name: str) -> VisionEvidence:
    payload = _require_mapping(raw_value or {}, field_name)
    return VisionEvidence(
        object_detection=_parse_object_detection(payload.get("object_detection"), f"{field_name}.object_detection"),
        image_caption=_parse_image_caption(payload.get("image_caption"), f"{field_name}.image_caption"),
    )


def _parse_chunk_evidence(raw_value: object, field_name: str) -> ChunkEvidence:
    payload = _require_mapping(raw_value or {}, field_name)
    audio_payload = payload.get("audio", {})
    audio = _require_mapping(audio_payload, f"{field_name}.audio") if audio_payload is not None else {}
    return ChunkEvidence(
        vision=_parse_vision_evidence(payload.get("vision"), f"{field_name}.vision"),
        audio=audio,
    )


def _parse_chunk_tags(raw_value: object, field_name: str) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    values = _require_list(raw_value, field_name)
    tags: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(values):
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(text)
        if len(tags) >= 48:
            break
    return tuple(tags)


def _parse_chunk(raw_value: object, field_name: str) -> EvidenceChunk:
    payload = _require_mapping(raw_value, field_name)
    sample_payload = _require_mapping(payload.get("sample"), f"{field_name}.sample")
    return EvidenceChunk(
        chunk_index=_require_int(payload.get("chunk_index"), f"{field_name}.chunk_index"),
        start_sec=_require_number(payload.get("start_sec"), f"{field_name}.start_sec"),
        end_sec=_require_number(payload.get("end_sec"), f"{field_name}.end_sec"),
        sample=ChunkSample(
            timestamp_sec=_require_number(sample_payload.get("timestamp_sec"), f"{field_name}.sample.timestamp_sec"),
            strategy=_require_text(sample_payload.get("strategy"), f"{field_name}.sample.strategy"),
        ),
        evidence=_parse_chunk_evidence(payload.get("evidence"), f"{field_name}.evidence"),
        tags=_parse_chunk_tags(payload.get("tags"), f"{field_name}.tags"),
    )


def _parse_video(raw_value: object) -> EvidenceVideo:
    payload = _require_mapping(raw_value, "video")
    duration_sec = payload.get("duration_sec")
    source_exists = payload.get("source_exists")
    return EvidenceVideo(
        video_id=_require_text(payload.get("video_id"), "video.video_id"),
        video_path=_require_text(payload.get("video_path"), "video.video_path"),
        video_rel_path=str(payload.get("video_rel_path", "") or ""),
        library_path=str(payload.get("library_path", "") or ""),
        duration_sec=_require_number(duration_sec, "video.duration_sec") if duration_sec is not None else None,
        source_exists=_require_bool(source_exists, "video.source_exists") if source_exists is not None else None,
    )


def _parse_summary(raw_value: object) -> VideoSummary | None:
    if raw_value is None:
        return None
    payload = _require_mapping(raw_value, "summary")
    return VideoSummary(
        text=_require_text(payload.get("text"), "summary.text"),
        source=str(payload.get("source", "remote_vlm") or "remote_vlm"),
    )


def _parse_provenance(raw_value: object) -> EvidenceProvenance:
    payload = _require_mapping(raw_value, "provenance")
    components_payload = _require_mapping(payload.get("components"), "provenance.components")
    components = {
        _require_text(key, f"provenance.components[{index}].key"): _require_text(
            value,
            f"provenance.components[{index}]",
        )
        for index, (key, value) in enumerate(components_payload.items())
    }
    chunk_source_payload = _require_mapping(payload.get("chunk_source"), "provenance.chunk_source")
    return EvidenceProvenance(
        understanding_profile_id=_require_text(
            payload.get("understanding_profile_id"),
            "provenance.understanding_profile_id",
        ),
        components=components,
        chunk_source=ChunkSourceProvenance(
            search_profile_id=_require_text(
                chunk_source_payload.get("search_profile_id"),
                "provenance.chunk_source.search_profile_id",
            ),
            search_provider=_require_text(
                chunk_source_payload.get("search_provider"),
                "provenance.chunk_source.search_provider",
            ),
            search_variant=_require_text(
                chunk_source_payload.get("search_variant"),
                "provenance.chunk_source.search_variant",
            ),
        ),
        keyframe_strategy=_require_text(payload.get("keyframe_strategy"), "provenance.keyframe_strategy"),
        generated_at=_require_text(payload.get("generated_at"), "provenance.generated_at"),
    )


def validate_evidence_bundle(payload: Mapping[str, Any]) -> EvidenceBundle:
    data = _require_mapping(payload, "payload")
    schema_version = _require_int(data.get("schema_version"), "schema_version")
    if schema_version != EVIDENCE_BUNDLE_SCHEMA_VERSION:
        raise EvidenceBundleValidationError(
            f"schema_version must be {EVIDENCE_BUNDLE_SCHEMA_VERSION}, got {schema_version}"
        )
    chunks = tuple(
        _parse_chunk(item, f"chunks[{index}]")
        for index, item in enumerate(_require_list(data.get("chunks"), "chunks"))
    )
    return EvidenceBundle(
        schema_version=schema_version,
        video=_parse_video(data.get("video")),
        provenance=_parse_provenance(data.get("provenance")),
        chunks=chunks,
        summary=_parse_summary(data.get("summary")),
    )


def _evidence_object_to_dict(item: EvidenceObject) -> dict[str, Any]:
    return {
        "label": item.label,
        "confidence": item.confidence,
        "bbox": list(item.bbox),
    }


def evidence_bundle_to_dict(bundle: EvidenceBundle) -> dict[str, Any]:
    vision_payload: dict[str, Any] = {}
    chunks: list[dict[str, Any]] = []
    for chunk in bundle.chunks:
        vision_payload = {}
        if chunk.evidence.vision.object_detection is not None:
            detection = chunk.evidence.vision.object_detection
            vision_payload["object_detection"] = {
                "source": detection.source,
                "objects": [_evidence_object_to_dict(item) for item in detection.objects],
            }
        if chunk.evidence.vision.image_caption is not None:
            caption = chunk.evidence.vision.image_caption
            vision_payload["image_caption"] = {
                "source": caption.source,
                "text": caption.text,
            }
        chunks.append(
            {
                "chunk_index": chunk.chunk_index,
                "start_sec": chunk.start_sec,
                "end_sec": chunk.end_sec,
                "sample": asdict(chunk.sample),
                "tags": list(chunk.tags),
                "evidence": {
                    "vision": vision_payload,
                    "audio": dict(chunk.evidence.audio),
                },
            }
        )

    video_payload = asdict(bundle.video)
    provenance_payload = {
        "understanding_profile_id": bundle.provenance.understanding_profile_id,
        "components": dict(bundle.provenance.components),
        "chunk_source": asdict(bundle.provenance.chunk_source),
        "keyframe_strategy": bundle.provenance.keyframe_strategy,
        "generated_at": bundle.provenance.generated_at,
    }
    payload = {
        "schema_version": bundle.schema_version,
        "video": video_payload,
        "provenance": provenance_payload,
        "chunks": chunks,
    }
    if bundle.summary is not None:
        payload["summary"] = {
            "text": bundle.summary.text,
            "source": bundle.summary.source,
        }
    return payload


def chunks_overlapping_time_window(
    bundle: EvidenceBundle,
    start_sec: float | None = None,
    end_sec: float | None = None,
) -> tuple[EvidenceChunk, ...]:
    window_start = float("-inf") if start_sec is None else float(start_sec)
    window_end = float("inf") if end_sec is None else float(end_sec)
    if window_start > window_end:
        raise ValueError("start_sec must be <= end_sec")
    return tuple(
        chunk
        for chunk in bundle.chunks
        if chunk.end_sec >= window_start and chunk.start_sec <= window_end
    )
