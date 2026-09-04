"""Thin optional plugin registry for VideoSeek.

OSS ships an empty registry by default. Call ``load_plugins`` before creating
``MainWindow``. Private plugins (e.g. clone) can live in a sibling repo, be
``pip install``-ed, or be pointed at with ``VIDEOSEEK_PLUGIN_PATHS`` when the
checkout is not next to VideoSeek; they are never required for the open-source app.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class PageSpec:
    page_id: str
    label_key: str
    factory: Callable[[], Any]
    insert_after: str = "understanding"
    scrollable: bool = True


@dataclass
class PackageKindSpec:
    kind: str
    detect_fn: Callable[[str], bool]
    import_fn: Callable[..., Dict[str, Any]]
    aggregate_imported_key: str = ""
    aggregate_updated_key: str = ""


class FeatureHooks:
    """Lifecycle callbacks for an optional feature module."""

    def on_init(self, window: Any) -> None:
        return None

    def wire_signals(self, window: Any) -> None:
        return None

    def apply_texts(self, window: Any) -> None:
        return None

    def on_page_shown(self, window: Any, page_id: str) -> None:
        return None

    def shutdown(self, window: Any) -> None:
        return None

    def is_busy(self, window: Any) -> bool:
        return False


@dataclass
class PluginRegistry:
    pages: List[PageSpec] = field(default_factory=list)
    features: List[FeatureHooks] = field(default_factory=list)
    package_kinds: Dict[str, PackageKindSpec] = field(default_factory=dict)
    i18n_overlays: List[tuple[Dict[str, Any], Dict[str, Any]]] = field(default_factory=list)
    loaded_modules: List[str] = field(default_factory=list)

    def register_page(
        self,
        page_id: str,
        *,
        label_key: str,
        factory: Callable[[], Any],
        insert_after: str = "understanding",
        scrollable: bool = True,
    ) -> None:
        page_id = str(page_id or "").strip()
        if not page_id:
            raise ValueError("page_id is required")
        if any(spec.page_id == page_id for spec in self.pages):
            raise ValueError(f"page_id already registered: {page_id}")
        self.pages.append(
            PageSpec(
                page_id=page_id,
                label_key=str(label_key or page_id),
                factory=factory,
                insert_after=str(insert_after or "understanding"),
                scrollable=bool(scrollable),
            )
        )

    def register_feature(self, feature: FeatureHooks) -> None:
        if feature is None:
            raise ValueError("feature is required")
        self.features.append(feature)

    def register_package_kind(
        self,
        kind: str,
        *,
        detect_fn: Callable[[str], bool],
        import_fn: Callable[..., Dict[str, Any]],
        aggregate_imported_key: str = "",
        aggregate_updated_key: str = "",
    ) -> None:
        kind = str(kind or "").strip()
        if not kind:
            raise ValueError("kind is required")
        if kind in self.package_kinds:
            raise ValueError(f"package kind already registered: {kind}")
        if kind in {"understanding", "search", "unknown"}:
            raise ValueError(f"package kind reserved: {kind}")
        self.package_kinds[kind] = PackageKindSpec(
            kind=kind,
            detect_fn=detect_fn,
            import_fn=import_fn,
            aggregate_imported_key=str(aggregate_imported_key or f"{kind}_imported"),
            aggregate_updated_key=str(aggregate_updated_key or f"{kind}_updated"),
        )

    def register_i18n(
        self,
        texts_zh: Optional[Dict[str, Any]] = None,
        texts_en: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.i18n_overlays.append((dict(texts_zh or {}), dict(texts_en or {})))


_REGISTRY = PluginRegistry()

# Sibling checkout names next to the VideoSeek app repo.
_SIBLING_PLUGIN_ROOTS = (
    "videoseek-plugin-clone",
    "VideoSeek-plugin-clone",
)
_DEFAULT_PRIVATE_PLUGIN = "videoseek_plugin_clone"


def get_registry() -> PluginRegistry:
    return _REGISTRY


def reset_registry_for_tests() -> PluginRegistry:
    """Clear registry state (unit tests only)."""
    global _REGISTRY
    _REGISTRY = PluginRegistry()
    return _REGISTRY


def resolve_nav_page_order(
    builtin_order: Sequence[str] = ("search", "library", "understanding", "link", "settings"),
    registry: Optional[PluginRegistry] = None,
) -> tuple[str, ...]:
    """Insert registered plugin pages after their ``insert_after`` anchors."""
    order = [str(name) for name in builtin_order]
    reg = registry if registry is not None else get_registry()
    for spec in reg.pages:
        if spec.page_id in order:
            continue
        anchor = spec.insert_after
        if anchor in order:
            idx = order.index(anchor) + 1
        elif "settings" in order:
            idx = order.index("settings")
        else:
            idx = len(order)
        order.insert(idx, spec.page_id)
    return tuple(order)


def _app_repo_root() -> str:
    # Packaged builds must use the exe directory, not a compiled module path.
    from src.infra.paths import get_app_install_dir

    return get_app_install_dir()


def _profile_plugins_path() -> str:
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        candidate = os.path.join(local, "VideoSeek", "profile", "plugins.json")
        if os.path.isfile(candidate):
            return candidate
    candidate = os.path.join(_app_repo_root(), "profile", "plugins.json")
    return candidate if os.path.isfile(candidate) else ""


def ensure_plugin_search_paths() -> List[str]:
    """Put sibling plugin checkouts / explicit paths on ``sys.path``.

    Returns paths that were newly inserted.
    """
    added: List[str] = []
    seen: set[str] = {os.path.normcase(os.path.abspath(p)) for p in sys.path if p}

    def _add_path(raw: str) -> None:
        path = os.path.abspath(os.path.expanduser(str(raw or "").strip()))
        if not path or not os.path.isdir(path):
            return
        key = os.path.normcase(path)
        if key in seen:
            return
        sys.path.insert(0, path)
        seen.add(key)
        added.append(path)

    for part in str(os.environ.get("VIDEOSEEK_PLUGIN_PATHS", "") or "").replace(";", ",").split(","):
        _add_path(part)

    parent = os.path.dirname(_app_repo_root())
    for sibling in _SIBLING_PLUGIN_ROOTS:
        root = os.path.join(parent, sibling)
        if os.path.isdir(os.path.join(root, "videoseek_plugin_clone")):
            _add_path(root)

    # Legacy in-tree path (VideoSeek-Pro transitional checkout).
    legacy = os.path.join(_app_repo_root(), "plugins", "clone")
    if os.path.isdir(os.path.join(legacy, "videoseek_plugin_clone")):
        _add_path(legacy)

    return added


def _module_importable(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def discover_plugin_module_names() -> List[str]:
    """Resolve plugin module names from env, profile, and local installs."""
    ensure_plugin_search_paths()
    names: List[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        for part in str(raw or "").replace(";", ",").split(","):
            name = part.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)

    _add(os.environ.get("VIDEOSEEK_PLUGINS", ""))

    path = _profile_plugins_path()
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                items = payload.get("plugins") or payload.get("modules") or []
            elif isinstance(payload, list):
                items = payload
            else:
                items = []
            if isinstance(items, str):
                _add(items)
            else:
                for item in items:
                    _add(str(item))
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    # Private clone plugin: load only when installed or checked out beside the app.
    if _DEFAULT_PRIVATE_PLUGIN not in seen and _module_importable(_DEFAULT_PRIVATE_PLUGIN):
        _add(_DEFAULT_PRIVATE_PLUGIN)

    return names


def load_plugins(module_names: Optional[Sequence[str]] = None) -> PluginRegistry:
    """Import plugin modules and call ``register(registry)`` on each.

    ``module_names`` overrides discovery. Duplicate loads of the same module
    name in one process are skipped.
    """
    ensure_plugin_search_paths()
    registry = get_registry()
    names = list(module_names) if module_names is not None else discover_plugin_module_names()
    for name in names:
        module_name = str(name or "").strip()
        if not module_name or module_name in registry.loaded_modules:
            continue
        module = importlib.import_module(module_name)
        register = getattr(module, "register", None)
        if not callable(register):
            raise RuntimeError(f"Plugin {module_name!r} has no register(registry) function")
        register(registry)
        registry.loaded_modules.append(module_name)
    return registry
