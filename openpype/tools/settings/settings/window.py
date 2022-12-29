from qtpy import QtWidgets, QtGui, QtCore

from openpype import style

from openpype.lib import is_admin_password_required
from openpype.lib.events import EventSystem
from openpype.widgets import PasswordDialog

from openpype.settings.lib import (
    get_last_opened_info,
    opened_settings_ui,
    closed_settings_ui,
)

from .dialogs import SettingsUIOpenedElsewhere
from .categories import (
    CategoryState,
    SystemWidget,
    ProjectWidget
)
from .widgets import (
    ShadowWidget,
    RestartDialog,
    SettingsTabWidget
)
from .search_dialog import SearchEntitiesDialog


class SettingsController:
    """Controller for settings tools.

    Added when tool was finished for checks of last opened in settings
    categories and being able communicated with main widget logic.
    """

    def __init__(self, user_role):
        self._user_role = user_role
        self._event_system = EventSystem()

        self._opened_info = None
        self._last_opened_info = None
        self._edit_mode = None

    @property
    def user_role(self):
        return self._user_role

    @property
    def event_system(self):
        return self._event_system

    @property
    def opened_info(self):
        return self._opened_info

    @property
    def last_opened_info(self):
        return self._last_opened_info

    @property
    def edit_mode(self):
        return self._edit_mode

    def ui_closed(self):
        if self._opened_info is not None:
            closed_settings_ui(self._opened_info)

        self._opened_info = None
        self._edit_mode = None

    def set_edit_mode(self, enabled):
        if self._edit_mode is enabled:
            return

        opened_info = None
        if enabled:
            opened_info = opened_settings_ui()
            self._last_opened_info = opened_info

        self._opened_info = opened_info
        self._edit_mode = enabled

        self.event_system.emit(
            "edit.mode.changed",
            {"edit_mode": enabled},
            "controller"
        )

    def update_last_opened_info(self):
        last_opened_info = get_last_opened_info()
        enabled = False
        if (
            last_opened_info is None
            or self._opened_info == last_opened_info
        ):
            enabled = True

        self._last_opened_info = last_opened_info

        self.set_edit_mode(enabled)


class MainWidget(QtWidgets.QWidget):
    trigger_restart = QtCore.Signal()

    widget_width = 1000
    widget_height = 600
    window_title = "OpenPype Settings"

    def __init__(self, user_role, parent=None, reset_on_show=True):
        super(MainWidget, self).__init__(parent)

        controller = SettingsController(user_role)

        # Object referencing to this machine and time when UI was opened
        # - is used on close event
        self._main_reset = False
        self._controller = controller

        self._user_passed = False
        self._reset_on_show = reset_on_show

        self._password_dialog = None

        self.setObjectName("SettingsMainWidget")
        self.setWindowTitle(self.window_title)

        self.resize(self.widget_width, self.widget_height)

        stylesheet = style.load_stylesheet()
        self.setStyleSheet(stylesheet)
        self.setWindowIcon(QtGui.QIcon(style.app_icon_path()))

        header_tab_widget = SettingsTabWidget(parent=self)

        studio_widget = SystemWidget(controller, header_tab_widget)
        project_widget = ProjectWidget(controller, header_tab_widget)

        tab_widgets = [
            studio_widget,
            project_widget
        ]

        header_tab_widget.addTab(studio_widget, "System")
        header_tab_widget.addTab(project_widget, "Project")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)
        layout.addWidget(header_tab_widget)

        self.setLayout(layout)

        search_dialog = SearchEntitiesDialog(self)

        self._shadow_widget = ShadowWidget("Working...", self)
        self._shadow_widget.setVisible(False)

        controller.event_system.add_callback(
            "edit.mode.changed",
            self._edit_mode_changed
        )

        header_tab_widget.currentChanged.connect(self._on_tab_changed)
        search_dialog.path_clicked.connect(self._on_search_path_clicked)

        for tab_widget in tab_widgets:
            tab_widget.saved.connect(self._on_tab_save)
            tab_widget.state_changed.connect(self._on_state_change)
            tab_widget.restart_required_trigger.connect(
                self._on_restart_required
            )
            tab_widget.reset_started.connect(self._on_reset_started)
            tab_widget.reset_finished.connect(self._on_reset_finished)
            tab_widget.full_path_requested.connect(self._on_full_path_request)

        header_tab_widget.context_menu_requested.connect(
            self._on_context_menu_request
        )

        self._header_tab_widget = header_tab_widget
        self.tab_widgets = tab_widgets
        self._search_dialog = search_dialog

    def _on_tab_save(self, source_widget):
        for tab_widget in self.tab_widgets:
            tab_widget.on_saved(source_widget)

    def _on_state_change(self):
        any_working = False
        for widget in self.tab_widgets:
            if widget.state is CategoryState.Working:
                any_working = True
                break

        if (
            (any_working and self._shadow_widget.isVisible())
            or (not any_working and not self._shadow_widget.isVisible())
        ):
            return

        self._shadow_widget.setVisible(any_working)

        # Process events to apply shadow widget visibility
        app = QtWidgets.QApplication.instance()
        if app:
            app.processEvents()

    def _on_full_path_request(self, category, path):
        for tab_widget in self.tab_widgets:
            if tab_widget.contain_category_key(category):
                idx = self._header_tab_widget.indexOf(tab_widget)
                self._header_tab_widget.setCurrentIndex(idx)
                tab_widget.set_category_path(category, path)
                break

    def _on_context_menu_request(self, tab_idx):
        widget = self._header_tab_widget.widget(tab_idx)
        if not widget:
            return

        menu = QtWidgets.QMenu(self)
        widget.add_context_actions(menu)
        if menu.actions():
            result = menu.exec_(QtGui.QCursor.pos())
            if result is not None:
                self._header_tab_widget.setCurrentIndex(tab_idx)

    def showEvent(self, event):
        super(MainWidget, self).showEvent(event)

        if self._reset_on_show:
            self._reset_on_show = False
            # Trigger reset with 100ms delay
            QtCore.QTimer.singleShot(100, self.reset)

    def closeEvent(self, event):
        self._controller.ui_closed()

        super(MainWidget, self).closeEvent(event)

    def _check_on_reset(self):
        self._controller.update_last_opened_info()
        if self._controller.edit_mode:
            return

        # if self._edit_mode is False:
        #     return

        dialog = SettingsUIOpenedElsewhere(
            self._controller.last_opened_info, self
        )
        dialog.exec_()
        self._controller.set_edit_mode(dialog.result() == 1)

    def _show_password_dialog(self):
        if self._password_dialog:
            self._password_dialog.open()

    def _on_password_dialog_close(self, password_passed):
        # Store result for future settings reset
        self._user_passed = password_passed
        # Remove reference to password dialog
        self._password_dialog = None
        if password_passed:
            self.reset()
            if not self.isVisible():
                self.show()
        else:
            self.close()

    def reset(self):
        if self._password_dialog:
            return

        if not self._user_passed:
            self._user_passed = not is_admin_password_required()

        self._on_state_change()

        if not self._user_passed:
            # Avoid doubled dialog
            dialog = PasswordDialog(self)
            dialog.setModal(True)
            dialog.finished.connect(self._on_password_dialog_close)

            self._password_dialog = dialog

            QtCore.QTimer.singleShot(100, self._show_password_dialog)

            return

        if self._reset_on_show:
            self._reset_on_show = False

        self._main_reset = True
        for tab_widget in self.tab_widgets:
            tab_widget.reset()
        self._main_reset = False
        self._check_on_reset()

    def _update_search_dialog(self, clear=False):
        if self._search_dialog.isVisible():
            entity = None
            if not clear:
                widget = self._header_tab_widget.currentWidget()
                entity = widget.entity
            self._search_dialog.set_root_entity(entity)

    def _edit_mode_changed(self, event):
        title = self.window_title
        if not event["edit_mode"]:
            title += " [View only]"
        self.setWindowTitle(title)

    def _on_tab_changed(self):
        self._update_search_dialog()

    def _on_search_path_clicked(self, path):
        widget = self._header_tab_widget.currentWidget()
        widget.change_path(path)

    def _on_restart_required(self):
        # Don't show dialog if there are not registered slots for
        #   `trigger_restart` signal.
        # - For example when settings are running as standalone tool
        # - PySide2 and PyQt5 compatible way how to find out
        method_index = self.metaObject().indexOfMethod("trigger_restart()")
        method = self.metaObject().method(method_index)
        if not self.isSignalConnected(method):
            return

        dialog = RestartDialog(self)
        result = dialog.exec_()
        if result == 1:
            self.trigger_restart.emit()

    def _on_reset_started(self):
        widget = self.sender()
        current_widget = self._header_tab_widget.currentWidget()
        if current_widget is widget:
            self._update_search_dialog(True)

    def _on_reset_finished(self):
        widget = self.sender()
        current_widget = self._header_tab_widget.currentWidget()
        if current_widget is widget:
            self._update_search_dialog()

        if not self._main_reset:
            self._check_on_reset()

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.Find):
            # todo: search in all widgets (or in active)?
            widget = self._header_tab_widget.currentWidget()
            self._search_dialog.show()
            self._search_dialog.set_root_entity(widget.entity)
            event.accept()
            return

        return super(MainWidget, self).keyPressEvent(event)
