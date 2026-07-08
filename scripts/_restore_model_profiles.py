"""One-off helper: rescan model_manifest.json files and restore models.profiles in config."""
import json
import os
import sys

CONFIG_PATH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "VideoSeek", "config.json")
MODEL_ROOT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "VideoSeek", "models")

MANIFESTS = [
    (os.path.join("openai-clip", "vit-base-patch32", "model_manifest.json"), "clip_onnx_default", "clip_onnx"),
    (os.path.join("chinese-clip", "vit-base-patch16", "model_manifest.json"), None, None),
    (os.path.join("siglip2", "base-patch16-224", "model_manifest.json"), None, None),
]


def build_profile(manifest: dict, *, forced_id=None, forced_provider=None, model_root=MODEL_ROOT):
    provider = forced_provider or str(manifest.get("provider", "") or "").strip()
    variant = str(manifest.get("variant", "") or manifest.get("model_variant", "") or "").strip()
    profile_id = forced_id or str(manifest.get("id", "") or "").strip() or f"{provider}_{variant}"
    files_map = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    return {
        "id": profile_id,
        "provider": provider,
        "display_name": str(manifest.get("display_name", "") or f"{provider} / {variant}"),
        "enabled": True,
        "runtime": {
            "prefer_gpu": bool(manifest.get("prefer_gpu", True)),
            "model_dir": model_root,
            "model_variant": variant,
        },
        "files": files_map,
        "capabilities": {
            "text_query": True,
            "image_query": True,
            "video_embedding": True,
            "cross_modal_search": True,
        },
    }


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else CONFIG_PATH
    model_root = sys.argv[2] if len(sys.argv) > 2 else MODEL_ROOT
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    models = config.setdefault("models", {})
    profiles = models.setdefault("profiles", [])
    by_id = {str(item.get("id", "")).strip(): item for item in profiles if isinstance(item, dict) and str(item.get("id", "")).strip()}

    for rel_path, forced_id, forced_provider in MANIFESTS:
        manifest_path = os.path.join(model_root, rel_path)
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        profile = build_profile(manifest, forced_id=forced_id, forced_provider=forced_provider, model_root=model_root)
        by_id[profile["id"]] = profile

    models["profiles"] = list(by_id.values())
    if not str(models.get("active_profile", "") or "").strip():
        models["active_profile"] = "clip_onnx_default"

    with open(config_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=4)
        handle.write("\n")

    print("restored profiles:", [item["id"] for item in models["profiles"]])
    print("active_profile:", models.get("active_profile"))


if __name__ == "__main__":
    main()
