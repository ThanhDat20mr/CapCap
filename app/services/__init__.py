from importlib import import_module

__all__ = [
    "AsrMergeService",
    "ChunkingService",
    "EngineRuntime",
    "F5VoiceService",
    "GUIProjectBridge",
    "ProjectService",
    "ResourceDownloadService",
    "SegmentRegroupService",
    "SegmentService",
    "VoiceCatalogService",
    "WorkflowRuntime",
]

_MODULE_MAP = {
    "AsrMergeService": ".asr_merge_service",
    "ChunkingService": ".chunking_service",
    "EngineRuntime": ".engine_runtime",
    "F5VoiceService": ".f5_voice_service",
    "GUIProjectBridge": ".gui_project_bridge",
    "ProjectService": ".project_service",
    "ResourceDownloadService": ".resource_download_service",
    "SegmentRegroupService": ".segment_regroup_service",
    "SegmentService": ".segment_service",
    "VoiceCatalogService": ".voice_catalog_service",
    "WorkflowRuntime": ".workflow_runtime",
}


def __getattr__(name):
    module_name = _MODULE_MAP.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
