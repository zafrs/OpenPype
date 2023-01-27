import os
import datetime
import copy
from qtpy import QtCore, QtWidgets, QtGui

from openpype.client import (
    get_asset_by_name,
    get_workfile_info,
)
from openpype.client.operations import (
    OperationsSession,
    new_workfile_info_doc,
    prepare_workfile_info_update_data,
)
from openpype import style
from openpype import resources
from openpype.pipeline import Anatomy
from openpype.pipeline import legacy_io
from openpype.tools.utils.assets_widget import SingleSelectAssetsWidget
from openpype.tools.utils.tasks_widget import TasksWidget

from .files_widget import FilesWidget


def file_size_to_string(file_size):
    size = 0
    size_ending_mapping = {
        "KB": 1024 ** 1,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3
    }
    ending = "B"
    for _ending, _size in size_ending_mapping.items():
        if file_size < _size:
            break
        size = file_size / _size
        ending = _ending
    return "{:.2f} {}".format(size, ending)


class SidePanelWidget(QtWidgets.QWidget):
    save_clicked = QtCore.Signal()
    published_workfile_message = (
        "<b>INFO</b>: Opened published workfiles will be stored in"
        " temp directory on your machine. Current temp size: <b>{}</b>."
    )

    def __init__(self, parent=None):
        super(SidePanelWidget, self).__init__(parent)

        details_label = QtWidgets.QLabel("Details", self)
        details_input = QtWidgets.QPlainTextEdit(self)
        details_input.setReadOnly(True)

        artist_note_widget = QtWidgets.QWidget(self)
        note_label = QtWidgets.QLabel("Artist note", artist_note_widget)
        note_input = QtWidgets.QPlainTextEdit(artist_note_widget)
        btn_note_save = QtWidgets.QPushButton("Save note", artist_note_widget)

        artist_note_layout = QtWidgets.QVBoxLayout(artist_note_widget)
        artist_note_layout.setContentsMargins(0, 0, 0, 0)
        artist_note_layout.addWidget(note_label, 0)
        artist_note_layout.addWidget(note_input, 1)
        artist_note_layout.addWidget(
            btn_note_save, 0, alignment=QtCore.Qt.AlignRight
        )

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(details_label, 0)
        main_layout.addWidget(details_input, 1)
        main_layout.addWidget(artist_note_widget, 1)

        note_input.textChanged.connect(self._on_note_change)
        btn_note_save.clicked.connect(self._on_save_click)

        self._details_input = details_input
        self._artist_note_widget = artist_note_widget
        self._note_input = note_input
        self._btn_note_save = btn_note_save

        self._orig_note = ""
        self._workfile_doc = None

    def set_published_visible(self, published_visible):
        self._artist_note_widget.setVisible(not published_visible)

    def _on_note_change(self):
        text = self._note_input.toPlainText()
        self._btn_note_save.setEnabled(self._orig_note != text)

    def _on_save_click(self):
        self._orig_note = self._note_input.toPlainText()
        self._on_note_change()
        self.save_clicked.emit()

    def set_context(self, asset_id, task_name, filepath, workfile_doc):
        # Check if asset, task and file are selected
        # NOTE workfile document is not requirement
        enabled = bool(asset_id) and bool(task_name) and bool(filepath)

        self._details_input.setEnabled(enabled)
        self._note_input.setEnabled(enabled)
        self._btn_note_save.setEnabled(enabled)

        # Make sure workfile doc is overridden
        self._workfile_doc = workfile_doc
        # Disable inputs and remove texts if any required arguments are missing
        if not enabled:
            self._orig_note = ""
            self._details_input.setPlainText("")
            self._note_input.setPlainText("")
            return

        orig_note = ""
        if workfile_doc:
            orig_note = workfile_doc["data"].get("note") or orig_note

        self._orig_note = orig_note
        self._note_input.setPlainText(orig_note)
        # Set as empty string
        self._details_input.setPlainText("")

        filestat = os.stat(filepath)
        size_value = file_size_to_string(filestat.st_size)

        # Append html string
        datetime_format = "%b %d %Y %H:%M:%S"
        creation_time = datetime.datetime.fromtimestamp(filestat.st_ctime)
        modification_time = datetime.datetime.fromtimestamp(filestat.st_mtime)
        lines = (
            "<b>Size:</b>",
            size_value,
            "<b>Created:</b>",
            creation_time.strftime(datetime_format),
            "<b>Modified:</b>",
            modification_time.strftime(datetime_format)
        )
        self._details_input.appendHtml("<br>".join(lines))

    def get_workfile_data(self):
        data = {
            "note": self._note_input.toPlainText()
        }
        return self._workfile_doc, data


class Window(QtWidgets.QWidget):
    """Work Files Window"""
    title = "Work Files"

    def __init__(self, parent=None):
        super(Window, self).__init__(parent=parent)
        self.setWindowTitle(self.title)
        icon = QtGui.QIcon(resources.get_openpype_icon_filepath())
        self.setWindowIcon(icon)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)

        # Create pages widget and set it as central widget
        pages_widget = QtWidgets.QStackedWidget(self)

        home_page_widget = QtWidgets.QWidget(pages_widget)
        home_body_widget = QtWidgets.QWidget(home_page_widget)

        assets_widget = SingleSelectAssetsWidget(
            legacy_io, parent=home_body_widget
        )
        assets_widget.set_current_asset_btn_visibility(True)

        tasks_widget = TasksWidget(legacy_io, home_body_widget)
        files_widget = FilesWidget(home_body_widget)
        side_panel = SidePanelWidget(home_body_widget)

        pages_widget.addWidget(home_page_widget)

        # Build home
        home_page_layout = QtWidgets.QVBoxLayout(home_page_widget)
        home_page_layout.addWidget(home_body_widget)

        # Build home - body
        body_layout = QtWidgets.QVBoxLayout(home_body_widget)
        split_widget = QtWidgets.QSplitter(home_body_widget)
        split_widget.addWidget(assets_widget)
        split_widget.addWidget(tasks_widget)
        split_widget.addWidget(files_widget)
        split_widget.addWidget(side_panel)
        split_widget.setSizes([255, 160, 455, 175])

        body_layout.addWidget(split_widget)

        # Add top margin for tasks to align it visually with files as
        # the files widget has a filter field which tasks does not.
        tasks_widget.setContentsMargins(0, 32, 0, 0)

        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.addWidget(pages_widget, 1)

        # Set context after asset widget is refreshed
        # - to do so it is necessary to wait until refresh is done
        set_context_timer = QtCore.QTimer()
        set_context_timer.setInterval(100)

        # Connect signals
        set_context_timer.timeout.connect(self._on_context_set_timeout)
        assets_widget.selection_changed.connect(self._on_asset_changed)
        tasks_widget.task_changed.connect(self._on_task_changed)
        files_widget.file_selected.connect(self.on_file_select)
        files_widget.workfile_created.connect(self.on_workfile_create)
        files_widget.file_opened.connect(self._on_file_opened)
        files_widget.published_visible_changed.connect(
            self._on_published_change
        )
        side_panel.save_clicked.connect(self.on_side_panel_save)

        self._set_context_timer = set_context_timer
        self.home_page_widget = home_page_widget
        self.pages_widget = pages_widget
        self.home_body_widget = home_body_widget
        self.split_widget = split_widget

        self.assets_widget = assets_widget
        self.tasks_widget = tasks_widget
        self.files_widget = files_widget
        self.side_panel = side_panel

        # Force focus on the open button by default, required for Houdini.
        files_widget.setFocus()

        self.resize(1200, 600)

        self._first_show = True
        self._context_to_set = None

    def ensure_visible(
        self, use_context=None, save=None, on_top=None
    ):
        if save is None:
            save = True

        self.set_save_enabled(save)

        if self.isVisible():
            use_context = False
        elif use_context is None:
            use_context = True

        if on_top is None and self._first_show:
            on_top = self.parent() is None

        window_flags = self.windowFlags()
        new_window_flags = window_flags
        if on_top is True:
            new_window_flags = window_flags | QtCore.Qt.WindowStaysOnTopHint
        elif on_top is False:
            new_window_flags = window_flags & ~QtCore.Qt.WindowStaysOnTopHint

        if new_window_flags != window_flags:
            # Note this is not propagated after initialization of widget in
            #   some Qt builds
            self.setWindowFlags(new_window_flags)
            self.show()

        elif not self.isVisible():
            self.show()

        if use_context is None or use_context is True:
            context = {
                "asset": legacy_io.Session["AVALON_ASSET"],
                "task": legacy_io.Session["AVALON_TASK"]
            }
            self.set_context(context)

        # Pull window to the front.
        self.raise_()
        self.activateWindow()

    @property
    def project_name(self):
        return legacy_io.Session["AVALON_PROJECT"]

    def showEvent(self, event):
        super(Window, self).showEvent(event)
        if self._first_show:
            self._first_show = False
            self.refresh()
            self.setStyleSheet(style.load_stylesheet())

    def keyPressEvent(self, event):
        """Custom keyPressEvent.

        Override keyPressEvent to do nothing so that Maya's panels won't
        take focus when pressing "SHIFT" whilst mouse is over viewport or
        outliner. This way users don't accidentally perform Maya commands
        whilst trying to name an instance.

        """

    def set_save_enabled(self, enabled):
        self.files_widget.set_save_enabled(enabled)

    def on_file_select(self, filepath):
        asset_id = self.assets_widget.get_selected_asset_id()
        task_name = self.tasks_widget.get_selected_task_name()

        workfile_doc = None
        if asset_id and task_name and filepath:
            filename = os.path.split(filepath)[1]
            project_name = legacy_io.active_project()
            workfile_doc = get_workfile_info(
                project_name, asset_id, task_name, filename
            )
        self.side_panel.set_context(
            asset_id, task_name, filepath, workfile_doc
        )

    def on_workfile_create(self, filepath):
        self._create_workfile_doc(filepath)

    def _on_file_opened(self):
        self.close()

    def _on_published_change(self, visible):
        self.side_panel.set_published_visible(visible)

    def on_side_panel_save(self):
        workfile_doc, data = self.side_panel.get_workfile_data()
        if not workfile_doc:
            filepath = self.files_widget._get_selected_filepath()
            workfile_doc = self._create_workfile_doc(filepath)

        new_workfile_doc = copy.deepcopy(workfile_doc)
        new_workfile_doc["data"] = data
        update_data = prepare_workfile_info_update_data(
            workfile_doc, new_workfile_doc
        )
        if not update_data:
            return

        project_name = legacy_io.active_project()

        session = OperationsSession()
        session.update_entity(
            project_name, "workfile", workfile_doc["_id"], update_data
        )
        session.commit()

    def _get_current_workfile_doc(self, filepath=None):
        if filepath is None:
            filepath = self.files_widget._get_selected_filepath()
        task_name = self.tasks_widget.get_selected_task_name()
        asset_id = self.assets_widget.get_selected_asset_id()
        if not task_name or not asset_id or not filepath:
            return

        filename = os.path.split(filepath)[1]
        project_name = legacy_io.active_project()
        return get_workfile_info(
            project_name, asset_id, task_name, filename
        )

    def _create_workfile_doc(self, filepath):
        workfile_doc = self._get_current_workfile_doc(filepath)
        if workfile_doc:
            return workfile_doc

        workdir, filename = os.path.split(filepath)

        project_name = legacy_io.active_project()
        asset_id = self.assets_widget.get_selected_asset_id()
        task_name = self.tasks_widget.get_selected_task_name()

        anatomy = Anatomy(project_name)
        success, rootless_dir = anatomy.find_root_template_from_path(workdir)
        filepath = "/".join([
            os.path.normpath(rootless_dir).replace("\\", "/"),
            filename
        ])

        workfile_doc = new_workfile_info_doc(
            filename, asset_id, task_name, [filepath]
        )

        session = OperationsSession()
        session.create_entity(project_name, "workfile", workfile_doc)
        session.commit()
        return workfile_doc

    def refresh(self):
        # Refresh asset widget
        self.assets_widget.refresh()

        self._on_task_changed()

    def set_context(self, context):
        self._context_to_set = context
        self._set_context_timer.start()

    def _on_context_set_timeout(self):
        if self._context_to_set is None:
            self._set_context_timer.stop()
            return

        if self.assets_widget.refreshing:
            return

        self._set_context_timer.stop()
        self._context_to_set, context = None, self._context_to_set
        if "asset" in context:
            asset_doc = get_asset_by_name(
                self.project_name, context["asset"], fields=["_id"]
            )

            asset_id = None
            if asset_doc:
                asset_id = asset_doc["_id"]
            # Select the asset
            self.assets_widget.select_asset(asset_id)
            self.tasks_widget.set_asset_id(asset_id)

        if "task" in context:
            self.tasks_widget.select_task_name(context["task"])
        self._on_task_changed()

    def _on_asset_changed(self):
        asset_id = self.assets_widget.get_selected_asset_id()
        if asset_id:
            self.tasks_widget.setEnabled(True)
        else:
            # Force disable the other widgets if no
            # active selection
            self.tasks_widget.setEnabled(False)
            self.files_widget.setEnabled(False)

        self.tasks_widget.set_asset_id(asset_id)

    def _on_task_changed(self):
        asset_id = self.assets_widget.get_selected_asset_id()
        task_name = self.tasks_widget.get_selected_task_name()
        task_type = self.tasks_widget.get_selected_task_type()

        asset_is_valid = asset_id is not None
        self.tasks_widget.setEnabled(asset_is_valid)

        self.files_widget.setEnabled(bool(task_name) and asset_is_valid)
        self.files_widget.set_asset_task(asset_id, task_name, task_type)
        self.files_widget.refresh()
