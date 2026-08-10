---
name: pyside6-ui-design
description: >-
  Design or audit VideoSeek PySide6 Widgets UI against the project design system
  (sidebar + stacked pages, VSCard/PageScaffold, QSS tokens, result tables).
  Use when creating screens, redesigning pages, auditing UX layout, aligning to
  Figma/tokens, or when the user mentions PySide6 UI design / Widgets chrome.
---

# VideoSeek PySide6 UI Design

Implement or audit desktop UI **inside the existing Widgets design system**. Do not propose QML rewrites or generic “AI dashboard” layouts.

## Before designing

1. Read `docs/pyside6_ui_architecture.md`.
2. Read [design-system.md](design-system.md).
3. Confirm: which page/dialog, light+dark both matter, zh/en copy needed.

Small tweaks (“move this button”, “rename label”) skip the full checklist — still respect objectNames and theme tokens.

## Hard rules (VideoSeek)

1. **Shell:** Left `NavigationSidebar` (~248px) + right `QStackedWidget` content. No top-tab app chrome.
2. **Page structure:** `PageScaffold` → `PageHeader` (title/subtitle/runtime banner) → `VSCard` sections.
3. **Cards:** Use `VSCard` variants (`PanelCard` / `SubPanelCard` / `NoticeCard` / dialog `Card`). Do not invent nested card soup or hero media cards.
4. **Search results:** Local/link results stay **tables** (`ResultView` / `#ResultTable`), not masonry/card grids.
5. **Library lists:** Keep grouped tree/card patterns already in `LibraryGroupedVideoTree` / library rows — do not replace with a random `QListWidget` gallery.
6. **Styling:** Colors/spacing via `ui/widgets/styles.py` tokens + `objectName`. No one-off pastel gradient themes, purple glow stacks, or Inter-default marketing landing patterns.
7. **Both themes:** Any new chrome must work in dark **and** light (`THEME_COLORS_*`).
8. **Actions:** One primary CTA per toolbar group (`PrimaryButton`); secondary = `AccentGhostButton` / `GhostButton`; destructive = `DangerGhostButton`.
9. **Async UX:** >400ms work shows progress/status (`VSProgressStatusRow` / page `lbl_status`); never freeze the window.
10. **i18n:** No hard-coded-only UI strings; add zh+en keys.

## Workflow

### A. New screen / redesign

```
Design Progress:
- [ ] 1. Place in nav + stack (or dialog)
- [ ] 2. Scaffold with PageScaffold / VSCard
- [ ] 3. Reuse ResultView / trees / settings form patterns
- [ ] 4. Wire objectNames + layout.py sizes
- [ ] 5. apply_texts + i18n
- [ ] 6. Verify dark/light mentally or via theme toggle path
```

Prefer extracting widgets under `ui/widgets/` over growing `components.py` further when adding sizable UI.

### B. Audit existing UI

Report only concrete violations of the hard rules / design-system.md:

```markdown
## UI design audit
### Issues
- **D1.** … (`path`) — violation / fix
### Preserved correctly
- …
### Suggested next polish (optional)
- …
```

## Anti-patterns (reject)

- Dashboard KPI strips, pill clouds, floating badge stickers on media
- Replacing result tables with Pinterest-style cards
- Per-widget `setStyleSheet("background: #…")` rainbow
- Modal dialogs without `AppMessageDialog` / existing dialog patterns for simple confirms
- Blocking file dialogs + heavy work on the same click without progress

## When implementing code

- Follow `pyside6-review` threading rules for any new actions.
- Keep controllers/services out of pure layout widgets when possible.
- Match existing spacing idioms in `PageScaffold` / `VSCard` margins.
