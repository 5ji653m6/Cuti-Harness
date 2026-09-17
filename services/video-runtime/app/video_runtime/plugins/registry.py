from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import yaml

from .models import LoadedVideoPlugin, PluginContext, VideoPluginManifest
from .sandbox_proxy import SandboxedVideoPlugin


class PluginDependencyError(RuntimeError):
    pass


class VideoPluginRegistry:
    """Lifecycle registry; executable third-party plugins are denied in-process by default."""

    def __init__(self) -> None:
        self._plugins: dict[str, LoadedVideoPlugin] = {}

    @property
    def manifests(self) -> list[VideoPluginManifest]:
        return [loaded.manifest for loaded in self._plugins.values()]

    @property
    def loaded(self) -> tuple[LoadedVideoPlugin, ...]:
        return tuple(self._plugins.values())

    async def register(
        self,
        manifest: VideoPluginManifest,
        implementation: Any,
        *,
        source_path: Path,
    ) -> VideoPluginManifest:
        """Register a host-created adapter through the same lifecycle as file plugins."""
        if manifest.id in self._plugins:
            raise ValueError(f"plugin is already loaded: {manifest.id}")
        missing = [item for item in manifest.dependencies if item not in self._plugins]
        if missing:
            raise PluginDependencyError(f"missing plugin dependencies: {', '.join(missing)}")
        contributed_workflows = set(manifest.contributions.workflows)
        duplicate_workflows = sorted({
            workflow
            for loaded in self._plugins.values()
            for workflow in loaded.manifest.contributions.workflows
            if workflow in contributed_workflows
        })
        if duplicate_workflows:
            raise ValueError(
                f"workflow is already registered: {', '.join(duplicate_workflows)}",
            )
        await implementation.on_load(PluginContext(values={
            "manifest": manifest.model_dump(),
        }))
        self._plugins[manifest.id] = LoadedVideoPlugin(
            manifest, implementation, source_path,
        )
        return manifest

    async def load(self, manifest_path: Path, *, allow_untrusted_in_process: bool = False) -> VideoPluginManifest:
        manifest = VideoPluginManifest.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")))
        if manifest.id in self._plugins:
            raise ValueError(f"plugin is already loaded: {manifest.id}")
        missing = [item for item in manifest.dependencies if item not in self._plugins]
        if missing:
            raise PluginDependencyError(f"missing plugin dependencies: {', '.join(missing)}")
        if not manifest.trusted and not allow_untrusted_in_process:
            if manifest.sandbox_runtime is None:
                raise PermissionError(
                    "untrusted executable plugins require sandbox_runtime",
                )
            implementation: Any = SandboxedVideoPlugin(manifest, manifest_path.parent)
        else:
            if not manifest.runtime_entrypoint:
                raise ValueError("runtime_entrypoint is required for in-process execution")
            module_name, separator, attribute = manifest.runtime_entrypoint.partition(":")
            if not separator:
                raise ValueError("runtime_entrypoint must use module:attribute syntax")
            implementation = getattr(importlib.import_module(module_name), attribute)
            implementation = implementation() if isinstance(implementation, type) else implementation
        return await self.register(
            manifest,
            implementation,
            source_path=manifest_path,
        )

    async def unload(self, plugin_id: str) -> None:
        loaded = self._plugins.get(plugin_id)
        if loaded is None:
            raise LookupError(f"plugin is not loaded: {plugin_id}")
        dependents = [
            item.manifest.id for item in self._plugins.values()
            if plugin_id in item.manifest.dependencies
        ]
        if dependents:
            raise PluginDependencyError(f"plugin is required by: {', '.join(dependents)}")
        await loaded.implementation.on_unload(PluginContext())
        del self._plugins[plugin_id]

    async def migrate(self, plugin_id: str, from_version: int) -> None:
        loaded = self._plugins.get(plugin_id)
        if loaded is None:
            raise LookupError(f"plugin is not loaded: {plugin_id}")
        to_version = loaded.manifest.migration_version
        if from_version > to_version:
            raise ValueError("plugin data cannot migrate backwards")
        if from_version != to_version:
            await loaded.implementation.migrate(PluginContext(), from_version, to_version)

    async def upgrade(self, manifest_path: Path) -> VideoPluginManifest:
        """Replace one loaded plugin only after its migration and load hooks succeed."""
        manifest = VideoPluginManifest.model_validate(
            yaml.safe_load(manifest_path.read_text(encoding="utf-8")),
        )
        previous = self.get(manifest.id)
        missing = [
            item for item in manifest.dependencies
            if item != manifest.id and item not in self._plugins
        ]
        if missing:
            raise PluginDependencyError(f"missing plugin dependencies: {', '.join(missing)}")
        if not manifest.trusted:
            if manifest.sandbox_runtime is None:
                raise PermissionError("untrusted executable plugins require sandbox_runtime")
            implementation: Any = SandboxedVideoPlugin(manifest, manifest_path.parent)
        else:
            assert manifest.runtime_entrypoint is not None
            module_name, _, attribute = manifest.runtime_entrypoint.partition(":")
            implementation = getattr(importlib.import_module(module_name), attribute)
            implementation = implementation() if isinstance(implementation, type) else implementation
        context = PluginContext(values={"manifest": manifest.model_dump()})
        await implementation.migrate(
            context,
            previous.manifest.migration_version,
            manifest.migration_version,
        )
        await implementation.on_load(context)
        try:
            await previous.implementation.on_unload(PluginContext())
        except BaseException:
            await implementation.on_unload(PluginContext())
            raise
        self._plugins[manifest.id] = LoadedVideoPlugin(
            manifest, implementation, manifest_path,
        )
        return manifest

    def get(self, plugin_id: str) -> LoadedVideoPlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise LookupError(f"plugin is not loaded: {plugin_id}") from exc

    async def load_directories(
        self,
        roots: list[Path],
        *,
        allow_untrusted_in_process: bool = False,
    ) -> list[VideoPluginManifest]:
        """Load manifests in dependency order from explicitly configured roots."""
        manifests = [
            manifest
            for root in roots
            if root.is_dir()
            for manifest in sorted(root.glob("*/video-plugin.yaml"))
        ]
        pending = list(manifests)
        loaded: list[VideoPluginManifest] = []
        while pending:
            progress = False
            for path in list(pending):
                raw = VideoPluginManifest.model_validate(
                    yaml.safe_load(path.read_text(encoding="utf-8")),
                )
                if any(item not in self._plugins for item in raw.dependencies):
                    continue
                loaded.append(await self.load(
                    path,
                    allow_untrusted_in_process=allow_untrusted_in_process,
                ))
                pending.remove(path)
                progress = True
            if not progress:
                unresolved = ", ".join(str(path) for path in pending)
                raise PluginDependencyError(
                    f"plugin dependency cycle or missing dependency: {unresolved}",
                )
        return loaded


def configured_plugin_roots() -> list[Path]:
    """Resolve the process-owned plugin roots without scanning arbitrary paths."""
    value = os.getenv("VIDEO_PLUGIN_PATHS", "").strip()
    if value:
        return [Path(item).resolve() for item in value.split(os.pathsep) if item.strip()]
    return [Path(__file__).resolve().parents[3] / "plugins"]
