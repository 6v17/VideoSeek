---
name: pyside6-review
description: >-
  Review VideoSeek PySide6 / Qt Widgets UI and desktop code for thread safety,
  signal-slot correctness, main-thread blocking, widget ownership, QSS/objectName
  misuse, and mixin boundaries. Use when the user asks for a PySide6 review,
  UI code review, Widgets audit, or Qt desktop sanity check on this repo.
---

# VideoSeek PySide6 Code Review

Read-only review. Do not edit code unless the user explicitly asks to fix findings.

## Before starting

1. Read `docs/pyside6_ui_architecture.md` (project UI map).
2. Read [checklist.md](checklist.md) and keep it as the review rubric.
3. Confirm scope with the user if unclear:
   - recent diff / branch changes, or
   - a path (e.g. `ui/windows/`, `ui/workers.py`), or
   - full `ui/` pass (expensive — prefer focused first).

## Workflow

```
Review Progress:
- [ ] 1. Map scope (files + entry points)
- [ ] 2. Threads & main-thread blocking
- [ ] 3. Signals, slots, QObject lifetime
- [ ] 4. UI state & controller boundaries
- [ ] 5. Widgets / QSS / i18n
- [ ] 6. Report (high-confidence only)
```

### 1. Map scope

- Prefer `ui/windows/gui_*.py` mixins, `ui/controllers/`, `ui/workers.py`, `ui/widgets/`, `ui/dialogs/`.
- Note whether changes touch `MainWindow.apply_theme` / `apply_texts` / `AppUiState`.

### 2. Threads & main-thread blocking

**Fail if** GUI code does heavy disk/network/ONNX/ffmpeg work on the GUI thread.

Project patterns (correct):

- Long work in `ui/workers.py` `QThread` subclasses (`SearchWorker`, `IndexUpdateWorker`, `ThumbLoader`, …).
- Controllers own workers; progress/errors via `Signal` back to the GUI thread.
- Stop paths call worker `stop` / `request_stop` and do not `terminate()` casually.

**Red flags:**

- `os.walk` / large DB / model load inside clicked handlers without a worker.
- Creating many `QThread`s without join/cleanup / `deleteLater`.
- Touching widgets directly from worker `run()`.

### 3. Signals, slots, lifetime

- Cross-thread UI updates must go through signals (queued connections), not raw widget calls from workers.
- Parent widgets own child dialogs/widgets; avoid parentless dialogs that leak.
- Disconnect or guard slots when the target may be destroyed mid-run.
- Prefer `finished` / explicit cleanup helpers already used in library indexing mixins.

### 4. UI state & boundaries

- Cross-page status (indexing / resources / inference) should go through `AppUiState` + `push_*` (`ui/state/app_ui_state.py`, `gui_ui_state.py`), not scatter-updates across many labels.
- Business logic stays in `src/services/` / controllers; widgets stay presentation.
- New MainWindow logic belongs in a focused `gui_*.py` mixin, not an ever-growing `gui.py`.

### 5. Widgets / QSS / i18n

- Style via `objectName` + global QSS from `ui/widgets/styles.py` / `apply_theme()`. Avoid ad-hoc `setStyleSheet` on random controls.
- New durable strings need `src/app/i18n.py` (zh + en) and wiring in `apply_texts` (or the page's text applicator).
- Prefer existing shells: `VSCard`, `PageScaffold`, `PageHeader`, `ResultView`, `NoWheel*`.
- Sizes from `ui/widgets/layout.py` (`COMPONENT_SIZES` / `WINDOW_SIZES`) instead of magic numbers.

### 6. Report format

Only report findings with confidence **≥ 80**. Cap investigation notes (60–79) at 10 total.

```markdown
## PySide6 review summary
One or two sentences.

## Findings
### F1. <title> (confidence NN)
- **Where:** `path` / symbol
- **Why it matters:** …
- **Evidence:** …
- **Mitigation:** …

## Investigation targets
- …

## Out of scope / not reviewed
- …
```

Do **not** nitpick style that already matches local conventions. Do **not** suggest rewriting the app to QML.

## Optional deep pass

For large scopes, split into parallel read-only passes (one agent each):

1. Threading & workers  
2. Controllers / AppUiState  
3. Widgets & QSS  
4. Dialogs & ownership  

Merge into a single deduplicated report.
