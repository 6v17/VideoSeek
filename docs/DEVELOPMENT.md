# Development Notes

## Placement Rules

- Put workflow-heavy UI behavior in `ui/*_controller.py`.
- Keep `ui/gui.py` as the shell layer: page wiring, text refresh, high-level coordination.
- Put business logic and remote parsing in `src/services/`.
- Put multi-step domain workflows in `src/workflows/`.
- Put shared filesystem/process helpers in `src/utils.py`.

## Current Controller Split

- `ui/runtime_resource_controller.py`: runtime resource dialog and download flow
- `ui/app_meta_controller.py`: remote version and notice refresh
- `ui/search_controller.py`: search worker and thumbnail flow
- `ui/indexing_controller.py`: indexing worker lifecycle and progress
- `ui/preview_controller.py`: preview clip generation and playback cleanup

## When Adding New Features

- If the feature owns a worker lifecycle or multi-step UI state, add or extend a controller.
- If the feature parses remote data, prefer a service first, then let a controller consume it.
- Avoid adding new workflow state directly to `MainWindow` unless it is purely shell-level UI state.

## Lightweight Test Targets

- `src/services/*`: pure logic and remote parsing
- `src/utils.py`: config/path sync helpers
- `ui/*_controller.py`: state transitions and worker wiring with mocks/stubs
