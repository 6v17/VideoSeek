# PySide6 review checklist (VideoSeek)

IDs are stable; cite them in findings when helpful (e.g. `THR-02`).

## Threading (`THR`)

| ID | Rule |
|----|------|
| THR-01 | No heavy I/O, hashing walks, model load, or ffmpeg on GUI thread in event handlers |
| THR-02 | Background work uses existing `ui/workers.py` `QThread` patterns (or equivalent) |
| THR-03 | Workers never call widget methods directly; only emit signals |
| THR-04 | Start/stop/cleanup is defined; no orphan threads after dialog close / page switch |
| THR-05 | Progress updates are throttled when high-frequency (indexing / thumbs) |
| THR-06 | Avoid `QThread.terminate()` except last-resort documented cases |

## Signals & lifetime (`SIG`)

| ID | Rule |
|----|------|
| SIG-01 | Signal arguments are immutable / plain data across threads (dict/list/str/int), not live widgets |
| SIG-02 | Dialogs have a proper parent; modality matches UX (blocking vs non-blocking) |
| SIG-03 | Slots tolerate re-entry or disable the triggering action while running |
| SIG-04 | `deleteLater` / finished handlers clear Python refs that could keep QThreads alive incorrectly |

## State & architecture (`ARC`)

| ID | Rule |
|----|------|
| ARC-01 | Indexing / resources / inference chrome updates go through `AppUiState` `push_*` when cross-page |
| ARC-02 | Controllers own orchestration; pages/mixins bind UI only |
| ARC-03 | New MainWindow behavior lands in `gui_*.py` mixin, not dumped into `gui.py` |
| ARC-04 | Team client / server mode gates mutating actions (add library, sync, index) |
| ARC-05 | Do not import Pro-only clone UI into OSS paths |

## Widgets & styling (`UI`)

| ID | Rule |
|----|------|
| UI-01 | Prefer `VSCard` / `PageScaffold` / `PageHeader` over bare `QFrame` + hand-rolled chrome |
| UI-02 | Buttons use known objectNames: `PrimaryButton`, `AccentGhostButton`, `GhostButton`, `DangerGhostButton`, `SuccessGhostButton` |
| UI-03 | No new global `setStyleSheet` except via `apply_theme` / `styles.py` tokens |
| UI-04 | Dynamic QSS properties call `repolish_widget` after change |
| UI-05 | Use `NoWheelComboBox` / spin boxes where scroll-stealing is a risk |
| UI-06 | Sizes from `layout.py` constants |

## i18n & copy (`I18N`)

| ID | Rule |
|----|------|
| I18N-01 | User-visible strings in `src/app/i18n.py` (zh + en) |
| I18N-02 | Fallback Chinese/English in `.get()` is OK; primary path still uses `texts` |
| I18N-03 | Team wording: 用户机 / 服务机 (not 员工机) |

## Performance UX (`PERF`)

| ID | Rule |
|----|------|
| PERF-01 | Large library tree refresh is not per-file during indexing |
| PERF-02 | Thumbnail loader can be stopped on new search |
| PERF-03 | Result empty-state does not flash during in-flight search (`ResultView.set_busy`) |
