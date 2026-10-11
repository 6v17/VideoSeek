# VideoSeek Widgets design system (quick ref)

Source of truth: this file + `docs/pyside6_ui_architecture.md` (Widgets shell), `ui/widgets/styles.py`, `ui/widgets/layout.py`, `ui/widgets/scaffold.py`.

## App chrome

| Piece | Implementation |
|-------|----------------|
| Root | `QMainWindow` → horizontal `AppRoot` |
| Sidebar | `NavigationSidebar`, width `COMPONENT_SIZES["sidebar_width"]` (248) |
| Content | `ContentArea` + `QStackedWidget` |
| Nav order | search → library → understanding → (Pro: clone) → link → settings |
| Scroll | Search/library/link/understanding in `QScrollArea`; settings usually not |

## Page building blocks

| Component | File | Notes |
|-----------|------|-------|
| `PageScaffold` | `scaffold.py` | header + `content_layout` |
| `PageHeader` | `scaffold.py` | title, subtitle, `#RuntimeBanner` |
| `VSCard` | `scaffold.py` | `PanelCard` / `SubPanelCard` / `NoticeCard` / dialog |
| `VSProgressStatusRow` | `scaffold.py` | progress + status |
| `SearchPanel` / `PreviewPanel` | `search_panel.py` / `preview_panel.py` | search page split |
| `ResultView` | `result_view.py` | table host, thumbs, busy/empty |
| `SettingsPage` | `widgets/settings/page.py` | five `VSCard` groups |

## Button objectNames

Every main-window `QPushButton` uses one action role via `ui.widgets.button_roles.set_button_role`.

| Role | objectName |
|------|------------|
| Primary | `PrimaryButton` |
| Accent secondary | `AccentGhostButton` |
| Neutral secondary | `GhostButton` |
| Danger | `DangerGhostButton` |
| Success/add | `SuccessGhostButton` |

Special chrome (nav, wizard steps, mode segments, toggles) keeps the role objectName and sets Qt property `chrome` for QSS overrides, e.g. `#GhostButton[chrome="nav"]`, `#GhostButton[chrome="wizardStep"]`, `#GhostButton[chrome="mobileToggle"]`.

| Chrome | Typical role | Notes |
|--------|--------------|-------|
| `nav` | GhostButton | Sidebar page switch (checkable) |
| `wizardStep` | GhostButton | Understanding step chips |
| `modeSegment` | GhostButton | Library / results view segment |
| `sidebarFooter` / `sidebarFooterGhost` | GhostButton | Sidebar bottom text actions |
| `mobileToggle` / `mobileQr` | Ghost / AccentGhost | Settings mobile bridge |
| Settings Save | PrimaryButton | Stays primary when clean; dirty only enables it |
| Understanding model test/save | Ghost / Primary | Inside the select-step card, not beside 下一步 |
| Sidebar icon tools | `SidebarIconButton` / `SidebarDonateButton` | `QToolButton`, not a QPushButton role |
| Line-edit clear | `FieldClearButton` | Qt clear `QToolButton` after `setClearButtonEnabled` |
| Table corner | `TableCornerButton` | Bare `QAbstractButton` on `QTableWidget` |
| Horizontal chip scroll | `ScrollLeftButton` / `ScrollRightButton` | Tag/chip strip arrows |

## Key layout constants (`layout.py`)

- Main window preferred ~1360×850, min ~1080×680  
- `search_compare_baseline_height` 540  
- `result_table_min_height` 420  
- `settings_input_width` 116, `settings_path_input_width` 520  

## Theme

- Global QSS only via `MainWindow.apply_theme()` → `QApplication.setStyleSheet`  
- Tokens in `STYLE_TEMPLATE` + dark/light color maps  
- Optional JSON tokens: `resources/tokens_*.json` → `theme_tokens.py`  
- After dynamic property changes: `repolish_widget()`

## Results UX

- Local search: 7-column `ResultTable` (thumb in col 2)  
- Network/link: `LinkResultTable`  
- Do not unify into card masonry without an explicit product decision  

## State surfaces

| State | Mechanism |
|-------|-----------|
| Resources missing | one `RuntimeInlineTip` above the page stack |
| Understanding model test/save | inside the select-step card, not beside 下一步 |
| Indexing | search-page notice + library progress |
| Inference/GPU text | settings via `gui_runtime` / `ui_state` |

## Copy

- Keys in `src/app/i18n.py`  
- Team client label: **用户机** (EN: user machine / User PC)
