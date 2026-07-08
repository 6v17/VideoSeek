import os
import types
import unittest
import json
from unittest.mock import MagicMock, call, patch


def _get_gui_target():
    from ui.windows.gui_library_indexing import LibraryIndexingGuiMixin
    from ui.windows.gui_runtime import RuntimeGuiMixin
    from ui.windows.gui_settings import SettingsGuiMixin

    class _GuiTarget(RuntimeGuiMixin, SettingsGuiMixin, LibraryIndexingGuiMixin):
        pass

    return _GuiTarget


class GuiSettingsPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Target = _get_gui_target()

    def test_build_runtime_issue_summary_prefers_missing_dll_names(self):
        dummy = types.SimpleNamespace(
            texts={
                "setting_runtime_issue_directx": "DirectML / DirectX 12",
                "setting_runtime_issue_unknown": "DirectML runtime",
            }
        )
        dummy._get_runtime_issue_text = lambda issue: self.Target._get_runtime_issue_text(dummy, issue)

        summary = self.Target._build_runtime_issue_summary(
            dummy,
            {
                "issue": "directx",
                "diagnostics": {"missing_dlls": ["DirectML.dll", "d3d12.dll"]},
            },
        )

        self.assertEqual(summary, "DirectML / DirectX 12: DirectML.dll, d3d12.dll")

    def test_build_runtime_diagnostics_detail_includes_structured_evidence(self):
        dummy = types.SimpleNamespace(
            texts={
                "setting_runtime_issue_probe_timeout": "GPU probe timed out",
                "setting_runtime_issue_unknown": "DirectML runtime",
                "setting_runtime_detail_missing_dlls": "Missing DLLs: {items}",
                "setting_runtime_detail_missing_msvc_dlls": "Missing VC++ DLLs: {items}",
                "setting_runtime_detail_available_providers": "Available providers: {items}",
                "setting_runtime_detail_windows_build": "Windows build: {value}",
                "setting_runtime_detail_probe_stage": "Failure stage: {value}",
                "setting_runtime_detail_probe_exception": "Exception: {value}",
                "setting_runtime_probe_stage_subprocess": "probe subprocess",
            }
        )
        dummy._get_runtime_issue_text = lambda issue: self.Target._get_runtime_issue_text(dummy, issue)
        dummy._build_runtime_issue_summary = lambda status: self.Target._build_runtime_issue_summary(dummy, status)

        detail = self.Target._build_runtime_diagnostics_detail(
            dummy,
            {
                "issue": "probe_timeout",
                "diagnostics": {
                    "available_providers": ["CPUExecutionProvider"],
                    "windows_build": 22631,
                    "probe_stage": "subprocess",
                    "probe_exception_type": "TimeoutExpired",
                    "probe_exception_message": "GPU runtime probe timed out.",
                },
            },
        )

        self.assertIn("GPU probe timed out", detail)
        self.assertIn("Available providers: CPUExecutionProvider", detail)
        self.assertIn("Windows build: 22631", detail)
        self.assertIn("Failure stage: probe subprocess", detail)
        self.assertIn("Exception: TimeoutExpired: GPU runtime probe timed out.", detail)

    def test_build_runtime_diagnostics_payload_includes_summary_and_raw_diagnostics(self):
        dummy = types.SimpleNamespace(
            texts={
                "setting_runtime_issue_directx": "DirectML / DirectX 12",
                "setting_runtime_issue_unknown": "DirectML runtime",
                "setting_runtime_detail_missing_dlls": "Missing DLLs: {items}",
            }
        )
        dummy._get_runtime_issue_text = lambda issue: self.Target._get_runtime_issue_text(dummy, issue)
        dummy._build_runtime_issue_summary = lambda status: self.Target._build_runtime_issue_summary(dummy, status)
        dummy._build_runtime_diagnostics_detail = lambda status: self.Target._build_runtime_diagnostics_detail(dummy, status)

        payload = self.Target._build_runtime_diagnostics_payload(
            dummy,
            {
                "backend": "CPU",
                "initialized": True,
                "prefer_gpu": True,
                "issue": "directx",
                "warning": "fallback",
                "diagnostics": {"missing_dlls": ["DirectML.dll"]},
            },
        )

        self.assertEqual(payload["summary"], "DirectML / DirectX 12: DirectML.dll")
        self.assertIn("Missing DLLs: DirectML.dll", payload["detail"])
        self.assertEqual(payload["diagnostics"], {"missing_dlls": ["DirectML.dll"]})

    def test_copy_runtime_diagnostics_copies_json_and_updates_status(self):
        clipboard = types.SimpleNamespace(setText=MagicMock())
        status_label = MagicMock()
        dummy = types.SimpleNamespace(
            texts={
                "setting_copy_runtime_diagnostics_done": "GPU diagnostics copied to clipboard.",
            },
            settings_page=types.SimpleNamespace(lbl_status=status_label),
        )
        dummy._build_runtime_diagnostics_payload = lambda status: self.Target._build_runtime_diagnostics_payload(dummy, status)
        dummy._build_runtime_issue_summary = lambda status: "DirectML / DirectX 12: DirectML.dll"
        dummy._build_runtime_diagnostics_detail = lambda status: "Missing DLLs: DirectML.dll"

        with (
            patch("ui.windows.gui_runtime.get_engine_runtime_status", return_value={"backend": "CPU", "diagnostics": {"missing_dlls": ["DirectML.dll"]}}),
            patch("ui.windows.gui_runtime.QApplication.clipboard", return_value=clipboard),
        ):
            self.Target.copy_runtime_diagnostics(dummy)

        clipboard.setText.assert_called_once()
        copied_payload = json.loads(clipboard.setText.call_args.args[0])
        self.assertEqual(copied_payload["backend"], "CPU")
        self.assertEqual(copied_payload["diagnostics"], {"missing_dlls": ["DirectML.dll"]})
        status_label.setText.assert_called_once_with("GPU diagnostics copied to clipboard.")

    def test_show_runtime_diagnostics_uses_summary_and_detail_dialog(self):
        dummy = types.SimpleNamespace(
            texts={
                "setting_show_runtime_diagnostics_title": "GPU diagnostics",
                "close": "Close",
                "setting_copy_runtime_diagnostics": "Copy",
            },
            is_dark_mode=False,
            language="zh",
        )
        dummy._build_runtime_diagnostics_payload = lambda status: {
            "summary": "DirectML / DirectX 12: DirectML.dll",
            "detail": "Missing DLLs: DirectML.dll",
            "warning": "GPU execution is unavailable.",
        }

        dialog_inst = MagicMock()
        dialog_inst.exec = MagicMock(return_value=0)
        dialog_inst.confirmed = MagicMock(return_value=False)

        with (
            patch("ui.windows.gui_runtime.get_engine_runtime_status", return_value={"backend": "CPU"}),
            patch("ui.windows.gui_runtime.AppMessageDialog") as mock_dialog,
        ):
            mock_dialog.return_value = dialog_inst
            self.Target.show_runtime_diagnostics(dummy)

        mock_dialog.assert_called_once()
        args, kwargs = mock_dialog.call_args
        self.assertEqual(args[0], "GPU diagnostics")
        self.assertIn("DirectML / DirectX 12: DirectML.dll", args[1])
        self.assertIn("Missing DLLs: DirectML.dll", args[1])
        self.assertIn("GPU execution is unavailable.", args[1])
        self.assertEqual(kwargs.get("kind"), "info")
        self.assertTrue(kwargs.get("confirm"))
        dialog_inst.exec.assert_called_once()

    def test_migrate_data_root_if_needed_requests_confirmation_and_calls_service(self):
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "data_root_move_confirm": "Move to {path}",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(lbl_status=MagicMock()),
            show_confirm_dialog=MagicMock(return_value=True),
        )

        with patch("ui.windows.gui_settings.migrate_app_data_root", return_value={"migrated": True, "new_data_root": "D:/new"}) as mock_migrate:
            result = self.Target._migrate_data_root_if_needed(dummy, "D:/old", "D:/new")

        self.assertEqual(result["new_data_root"], "D:/new")
        dummy.show_confirm_dialog.assert_called_once_with("Confirm", "Move to D:/new")
        mock_migrate.assert_called_once_with("D:/new")

    def test_migrate_data_root_if_needed_stops_when_user_cancels(self):
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "data_root_move_confirm": "Move to {path}",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(lbl_status=MagicMock()),
            show_confirm_dialog=MagicMock(return_value=False),
        )

        with patch("ui.windows.gui_settings.migrate_app_data_root") as mock_migrate:
            result = self.Target._migrate_data_root_if_needed(dummy, "D:/old", "D:/new")

        self.assertFalse(result)
        dummy.show_confirm_dialog.assert_called_once_with("Confirm", "Move to D:/new")
        dummy.settings_page.lbl_status.setText.assert_called_once_with("Settings hint")
        mock_migrate.assert_not_called()

    def test_build_data_root_migration_message_uses_old_and_new_paths(self):
        dummy = types.SimpleNamespace(
            texts={
                "data_root_move_success": "Moved to {path}",
                "data_root_move_success_detail": "Old: {old_path} | New: {new_path} | Manual cleanup later",
            }
        )

        message = self.Target._build_data_root_migration_message(
            dummy,
            {
                "old_data_root": "D:/old",
                "new_data_root": "D:/new",
            },
            "D:/fallback",
        )

        self.assertEqual(message, "Old: D:/old | New: D:/new | Manual cleanup later")

    def test_build_data_storage_status_text_uses_only_data_root(self):
        dummy = types.SimpleNamespace(
            texts={
                "setting_data_active": "Root={data_root}",
            }
        )

        message = self.Target._build_data_storage_status_text(
            dummy,
            {
                "data_root": "D:/store",
                "meta_file": "D:/store/data/meta.json",
            },
        )

        self.assertEqual(message, f"Root={os.path.normpath('D:/store')}")

    def test_start_index_update_refreshes_library_table_after_disabling_toolbar_actions(self):
        dummy = types.SimpleNamespace(
            texts={
                "model_features_disabled": "Disabled",
                "index_start_failed": "Index failed",
            },
            library_page=types.SimpleNamespace(
                lbl_status=MagicMock(),
                btn_sync_db=MagicMock(),
                btn_stop_index=MagicMock(),
                btn_add_lib=MagicMock(),
                btn_cleanup_missing=MagicMock(),
                progress_bar=MagicMock(),
            ),
            ui_state=types.SimpleNamespace(set_indexing_running=MagicMock()),
            check_runtime_resources=MagicMock(return_value=True),
            switch_page=MagicMock(),
            indexing_controller=types.SimpleNamespace(
                is_running=MagicMock(return_value=False),
                start=MagicMock(return_value=True),
            ),
            _apply_index_issue_button_state=MagicMock(),
            refresh_library_table=MagicMock(),
            show_error_dialog=MagicMock(),
            _refresh_search_session_hint=MagicMock(),
            _last_index_issues=["old issue"],
            _last_index_issue_target="old",
        )

        self.Target._start_index_update(dummy, target_lib="D:/videos", rebuild_global_assets=False)

        dummy.library_page.btn_sync_db.setEnabled.assert_called_once_with(False)
        dummy.library_page.btn_add_lib.setEnabled.assert_called_once_with(False)
        dummy.refresh_library_table.assert_called_once_with()
        dummy.indexing_controller.start.assert_called_once_with(
            target_lib="D:/videos",
            force_cleanup_missing_files=False,
            cleanup_missing_entries=None,
            rebuild_global_assets=False,
            index_from_vectors_only=False,
        )

    def test_cleanup_old_data_root_calls_service_and_reports_success(self):
        saved_configs = []
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "cleanup_old_data_root_confirm": "Clean {path}",
                "cleanup_old_data_root_confirm_again": "Clean again {path} active {active_path}",
                "cleanup_old_data_root_done": "Cleaned {path}",
                "cleanup_old_data_root_missing": "Missing {path}",
                "cleanup_old_data_root_failed": "Failed",
                "cleanup_old_data_root_active_error": "Active {path}",
                "cleanup_old_data_root_unavailable": "Unavailable",
                "cleanup_old_data_root_pending": "Pending {path}",
                "success_title": "Done",
                "warning_title": "Warn",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(
                lbl_status=MagicMock(),
                btn_cleanup_old_data_root=types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock()),
            ),
            _normalize_requested_data_root=lambda value: value.replace("\\", "/"),
            _get_pending_cleanup_data_root=lambda config=None: "D:/old",
            _refresh_pending_cleanup_actions=MagicMock(),
            show_confirm_dialog=MagicMock(return_value=True),
            show_info_dialog=MagicMock(),
            show_error_dialog=MagicMock(),
        )

        with (
            patch("ui.windows.gui_settings.load_config", return_value={"data_root": "D:/new", "pending_cleanup_data_root": "D:/old"}),
            patch("ui.windows.gui_settings.save_config", side_effect=saved_configs.append),
            patch("ui.windows.gui_settings.get_configured_data_root", return_value="D:/new"),
            patch("ui.windows.gui_settings.cleanup_old_data_root_service", return_value={"cleaned": True, "old_data_dir": "D:/old/data"}) as mock_cleanup,
        ):
            self.Target.cleanup_old_data_root(dummy)

        self.assertEqual(
            dummy.show_confirm_dialog.call_args_list,
            [
                call("Confirm", "Clean D:/old", kind="warning"),
                call("Confirm", "Clean again D:/old active D:/new", kind="warning"),
            ],
        )
        mock_cleanup.assert_called_once_with("D:/old", active_data_root="D:/new")
        self.assertEqual(saved_configs[-1]["data_root"], "D:/new")
        self.assertNotIn("pending_cleanup_data_root", saved_configs[-1])
        dummy._refresh_pending_cleanup_actions.assert_called_once()
        dummy.settings_page.lbl_status.setText.assert_called_once_with("Cleaned D:/old/data")
        dummy.show_info_dialog.assert_called_once_with("Done", "Cleaned D:/old/data", kind="success")

    def test_cleanup_old_data_root_rejects_active_root_before_service_call(self):
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "cleanup_old_data_root_confirm": "Clean {path}",
                "cleanup_old_data_root_confirm_again": "Clean again {path} active {active_path}",
                "cleanup_old_data_root_done": "Cleaned {path}",
                "cleanup_old_data_root_missing": "Missing {path}",
                "cleanup_old_data_root_failed": "Failed",
                "cleanup_old_data_root_active_error": "Active {path}",
                "cleanup_old_data_root_unavailable": "Unavailable",
                "cleanup_old_data_root_pending": "Pending {path}",
                "success_title": "Done",
                "warning_title": "Warn",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(
                lbl_status=MagicMock(),
                btn_cleanup_old_data_root=types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock()),
            ),
            _normalize_requested_data_root=lambda value: value.replace("\\", "/"),
            _get_pending_cleanup_data_root=lambda config=None: "D:/same",
            _refresh_pending_cleanup_actions=MagicMock(),
            show_confirm_dialog=MagicMock(return_value=True),
            show_info_dialog=MagicMock(),
            show_error_dialog=MagicMock(),
        )

        with (
            patch("ui.windows.gui_settings.load_config", return_value={"data_root": "D:/same", "pending_cleanup_data_root": "D:/same"}),
            patch("ui.windows.gui_settings.get_configured_data_root", return_value="D:/same"),
            patch("ui.windows.gui_settings.cleanup_old_data_root_service") as mock_cleanup,
        ):
            self.Target.cleanup_old_data_root(dummy)

        dummy.show_confirm_dialog.assert_not_called()
        mock_cleanup.assert_not_called()
        dummy.settings_page.lbl_status.setText.assert_called_once_with("Active D:/same")
        dummy.show_info_dialog.assert_called_once_with("Warn", "Active D:/same", kind="warning")

    def test_refresh_pending_cleanup_action_hides_button_without_recorded_old_root(self):
        button = types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock())
        dummy = types.SimpleNamespace(
            texts={"cleanup_old_data_root_pending": "Pending {path}"},
            settings_page=types.SimpleNamespace(btn_cleanup_old_data_root=button),
            _get_pending_cleanup_data_root=lambda config=None: "",
        )

        result = self.Target._refresh_pending_cleanup_action(dummy, {"data_root": "D:/new"})

        self.assertEqual(result, "")
        button.setVisible.assert_called_once_with(False)
        button.setToolTip.assert_called_once_with("")

    def test_refresh_pending_cleanup_action_shows_button_for_recorded_old_root(self):
        button = types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock())
        dummy = types.SimpleNamespace(
            texts={"cleanup_old_data_root_pending": "Pending {path}"},
            settings_page=types.SimpleNamespace(btn_cleanup_old_data_root=button),
            _get_pending_cleanup_data_root=lambda config=None: "D:/old",
        )

        result = self.Target._refresh_pending_cleanup_action(dummy, {"data_root": "D:/new"})

        self.assertEqual(result, "D:/old")
        button.setVisible.assert_called_once_with(True)
        button.setToolTip.assert_called_once_with("Pending D:/old")


if __name__ == "__main__":
    unittest.main()
