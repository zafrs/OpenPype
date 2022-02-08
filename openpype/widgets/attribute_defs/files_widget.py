import os
import collections
import uuid
import clique
from Qt import QtWidgets, QtCore, QtGui

from openpype.tools.utils import paint_image_with_color
# TODO change imports
from openpype.tools.resources import (
    get_pixmap,
    get_image,
)
from openpype.tools.utils import (
    IconButton,
    PixmapLabel
)

ITEM_ID_ROLE = QtCore.Qt.UserRole + 1
ITEM_LABEL_ROLE = QtCore.Qt.UserRole + 2
ITEM_ICON_ROLE = QtCore.Qt.UserRole + 3
FILENAMES_ROLE = QtCore.Qt.UserRole + 4
DIRPATH_ROLE = QtCore.Qt.UserRole + 5
IS_DIR_ROLE = QtCore.Qt.UserRole + 6
EXT_ROLE = QtCore.Qt.UserRole + 7


class DropEmpty(QtWidgets.QWidget):
    _drop_enabled_text = "Drag & Drop\n(drop files here)"

    def __init__(self, parent):
        super(DropEmpty, self).__init__(parent)
        label_widget = QtWidgets.QLabel(self._drop_enabled_text, self)
        label_widget.setAlignment(QtCore.Qt.AlignCenter)

        label_widget.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addSpacing(10)
        layout.addWidget(
            label_widget,
            alignment=QtCore.Qt.AlignCenter
        )
        layout.addSpacing(10)

        self._label_widget = label_widget

    def paintEvent(self, event):
        super(DropEmpty, self).paintEvent(event)
        painter = QtGui.QPainter(self)
        pen = QtGui.QPen()
        pen.setWidth(1)
        pen.setBrush(QtCore.Qt.darkGray)
        pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(pen)
        content_margins = self.layout().contentsMargins()

        left_m = content_margins.left()
        top_m = content_margins.top()
        rect = QtCore.QRect(
            left_m,
            top_m,
            (
                self.rect().width()
                - (left_m + content_margins.right() + pen.width())
            ),
            (
                self.rect().height()
                - (top_m + content_margins.bottom() + pen.width())
            )
        )
        painter.drawRect(rect)


class FilesModel(QtGui.QStandardItemModel):
    sequence_exts = [
        ".ani", ".anim", ".apng", ".art", ".bmp", ".bpg", ".bsave", ".cal",
        ".cin", ".cpc", ".cpt", ".dds", ".dpx", ".ecw", ".exr", ".fits",
        ".flic", ".flif", ".fpx", ".gif", ".hdri", ".hevc", ".icer",
        ".icns", ".ico", ".cur", ".ics", ".ilbm", ".jbig", ".jbig2",
        ".jng", ".jpeg", ".jpeg-ls", ".2000", ".jpg", ".xr",
        ".jpeg-hdr", ".kra", ".mng", ".miff", ".nrrd",
        ".ora", ".pam", ".pbm", ".pgm", ".ppm", ".pnm", ".pcx", ".pgf",
        ".pictor", ".png", ".psb", ".psp", ".qtvr", ".ras",
        ".rgbe", ".logluv", ".tiff", ".sgi", ".tga", ".tiff", ".tiff/ep",
        ".tiff/it", ".ufo", ".ufp", ".wbmp", ".webp", ".xbm", ".xcf",
        ".xpm", ".xwd"
    ]

    def __init__(self):
        super(FilesModel, self).__init__()
        self._filenames_by_dirpath = collections.defaultdict(set)
        self._items_by_dirpath = collections.defaultdict(list)

    def add_filepaths(self, filepaths):
        if not filepaths:
            return

        new_dirpaths = set()
        for filepath in filepaths:
            filename = os.path.basename(filepath)
            dirpath = os.path.dirname(filepath)
            filenames = self._filenames_by_dirpath[dirpath]
            if filename not in filenames:
                new_dirpaths.add(dirpath)
                filenames.add(filename)
        self._refresh_items(new_dirpaths)

    def remove_item_by_ids(self, item_ids):
        if not item_ids:
            return

        remaining_ids = set(item_ids)
        result = collections.defaultdict(list)
        for dirpath, items in self._items_by_dirpath.items():
            if not remaining_ids:
                break
            for item in items:
                if not remaining_ids:
                    break
                item_id = item.data(ITEM_ID_ROLE)
                if item_id in remaining_ids:
                    remaining_ids.remove(item_id)
                    result[dirpath].append(item)

        if not result:
            return

        dirpaths = set(result.keys())
        for dirpath, items in result.items():
            filenames_cache = self._filenames_by_dirpath[dirpath]
            for item in items:
                filenames = item.data(FILENAMES_ROLE)

                self._items_by_dirpath[dirpath].remove(item)
                self.removeRows(item.row(), 1)
                for filename in filenames:
                    if filename in filenames_cache:
                        filenames_cache.remove(filename)

        self._refresh_items(dirpaths)

    def _refresh_items(self, dirpaths=None):
        if dirpaths is None:
            dirpaths = set(self._items_by_dirpath.keys())

        new_items = []
        for dirpath in dirpaths:
            items_to_remove = list(self._items_by_dirpath[dirpath])
            cols, remainders = clique.assemble(
                self._filenames_by_dirpath[dirpath]
            )
            filtered_cols = []
            for collection in cols:
                filenames = set(collection)
                valid_col = True
                for filename in filenames:
                    ext = os.path.splitext(filename)[-1]
                    valid_col = ext in self.sequence_exts
                    break

                if valid_col:
                    filtered_cols.append(collection)
                else:
                    for filename in filenames:
                        remainders.append(filename)

            for filename in remainders:
                found = False
                for item in items_to_remove:
                    item_filenames = item.data(FILENAMES_ROLE)
                    if filename in item_filenames and len(item_filenames) == 1:
                        found = True
                        items_to_remove.remove(item)
                        break

                if found:
                    continue

                fullpath = os.path.join(dirpath, filename)
                if os.path.isdir(fullpath):
                    icon_pixmap = get_pixmap(filename="folder.png")
                else:
                    icon_pixmap = get_pixmap(filename="file.png")
                label = filename
                filenames = [filename]
                item = self._create_item(
                    label, filenames, dirpath, icon_pixmap
                )
                new_items.append(item)
                self._items_by_dirpath[dirpath].append(item)

            for collection in filtered_cols:
                filenames = set(collection)
                found = False
                for item in items_to_remove:
                    item_filenames = item.data(FILENAMES_ROLE)
                    if item_filenames == filenames:
                        found = True
                        items_to_remove.remove(item)
                        break

                if found:
                    continue

                col_range = collection.format("{ranges}")
                label = "{}<{}>{}".format(
                    collection.head, col_range, collection.tail
                )
                icon_pixmap = get_pixmap(filename="files.png")
                item = self._create_item(
                    label, filenames, dirpath, icon_pixmap
                )
                new_items.append(item)
                self._items_by_dirpath[dirpath].append(item)

            for item in items_to_remove:
                self._items_by_dirpath[dirpath].remove(item)
                self.removeRows(item.row(), 1)

        if new_items:
            self.invisibleRootItem().appendRows(new_items)

    def _create_item(self, label, filenames, dirpath, icon_pixmap=None):
        first_filename = None
        for filename in filenames:
            first_filename = filename
            break
        ext = os.path.splitext(first_filename)[-1]
        is_dir = False
        if len(filenames) == 1:
            filepath = os.path.join(dirpath, first_filename)
            is_dir = os.path.isdir(filepath)

        item = QtGui.QStandardItem()
        item.setData(str(uuid.uuid4()), ITEM_ID_ROLE)
        item.setData(label, ITEM_LABEL_ROLE)
        item.setData(filenames, FILENAMES_ROLE)
        item.setData(dirpath, DIRPATH_ROLE)
        item.setData(icon_pixmap, ITEM_ICON_ROLE)
        item.setData(ext, EXT_ROLE)
        item.setData(is_dir, IS_DIR_ROLE)

        return item


class FilesProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        super(FilesProxyModel, self).__init__(*args, **kwargs)
        self._allow_folders = False
        self._allowed_extensions = None

    def set_allow_folders(self, allow=None):
        if allow is None:
            allow = not self._allow_folders

        if allow == self._allow_folders:
            return
        self._allow_folders = allow
        self.invalidateFilter()

    def set_allowed_extensions(self, extensions=None):
        if extensions is not None:
            extensions = set(extensions)

        if self._allowed_extensions != extensions:
            self._allowed_extensions = extensions
            self.invalidateFilter()

    def filterAcceptsRow(self, row, parent_index):
        model = self.sourceModel()
        index = model.index(row, self.filterKeyColumn(), parent_index)
        # First check if item is folder and if folders are enabled
        if index.data(IS_DIR_ROLE):
            if not self._allow_folders:
                return False
            return True

        # Check if there are any allowed extensions
        if self._allowed_extensions is None:
            return False

        if index.data(EXT_ROLE) not in self._allowed_extensions:
            return False
        return True

    def lessThan(self, left, right):
        left_comparison = left.data(DIRPATH_ROLE)
        right_comparison = right.data(DIRPATH_ROLE)
        if left_comparison == right_comparison:
            left_comparison = left.data(ITEM_LABEL_ROLE)
            right_comparison = right.data(ITEM_LABEL_ROLE)

        if sorted((left_comparison, right_comparison))[0] == left_comparison:
            return True
        return False


class ItemWidget(QtWidgets.QWidget):
    remove_requested = QtCore.Signal(str)

    def __init__(self, item_id, label, pixmap_icon, parent=None):
        self._item_id = item_id

        super(ItemWidget, self).__init__(parent)

        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        icon_widget = PixmapLabel(pixmap_icon, self)
        label_widget = QtWidgets.QLabel(label, self)
        pixmap = paint_image_with_color(
            get_image(filename="delete.png"), QtCore.Qt.white
        )
        remove_btn = IconButton(self)
        remove_btn.setIcon(QtGui.QIcon(pixmap))

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(icon_widget, 0)
        layout.addWidget(label_widget, 1)
        layout.addWidget(remove_btn, 0)

        remove_btn.clicked.connect(self._on_remove_clicked)

        self._icon_widget = icon_widget
        self._label_widget = label_widget
        self._remove_btn = remove_btn

    def _on_remove_clicked(self):
        self.remove_requested.emit(self._item_id)


class FilesView(QtWidgets.QListView):
    """View showing instances and their groups."""
    def __init__(self, *args, **kwargs):
        super(FilesView, self).__init__(*args, **kwargs)

        self.setEditTriggers(QtWidgets.QListView.NoEditTriggers)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )

    def get_selected_item_ids(self):
        """Ids of selected instances."""
        selected_item_ids = set()
        for index in self.selectionModel().selectedIndexes():
            instance_id = index.data(ITEM_ID_ROLE)
            if instance_id is not None:
                selected_item_ids.add(instance_id)
        return selected_item_ids

    def event(self, event):
        if not event.type() == QtCore.QEvent.KeyPress:
            pass

        elif event.key() == QtCore.Qt.Key_Space:
            self.toggle_requested.emit(-1)
            return True

        elif event.key() == QtCore.Qt.Key_Backspace:
            self.toggle_requested.emit(0)
            return True

        elif event.key() == QtCore.Qt.Key_Return:
            self.toggle_requested.emit(1)
            return True

        return super(FilesView, self).event(event)


class MultiFilesWidget(QtWidgets.QFrame):
    value_changed = QtCore.Signal()

    def __init__(self, parent):
        super(MultiFilesWidget, self).__init__(parent)
        self.setAcceptDrops(True)

        empty_widget = DropEmpty(self)

        files_model = FilesModel()
        files_proxy_model = FilesProxyModel()
        files_proxy_model.setSourceModel(files_model)
        files_view = FilesView(self)
        files_view.setModel(files_proxy_model)
        files_view.setVisible(False)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(empty_widget, 1)
        layout.addWidget(files_view, 1)

        files_proxy_model.rowsInserted.connect(self._on_rows_inserted)
        files_proxy_model.rowsRemoved.connect(self._on_rows_removed)

        self._in_set_value = False

        self._empty_widget = empty_widget
        self._files_model = files_model
        self._files_proxy_model = files_proxy_model
        self._files_view = files_view

        self._widgets_by_id = {}

    def set_value(self, value, multivalue):
        self._in_set_value = True
        widget_ids = set(self._widgets_by_id.keys())
        self._remove_item_by_ids(widget_ids)

        # TODO how to display multivalue?
        all_same = True
        if multivalue:
            new_value = set()
            item_row = None
            for _value in value:
                _value_set = set(_value)
                new_value |= _value_set
                if item_row is None:
                    item_row = _value_set
                elif item_row != _value_set:
                    all_same = False
            value = new_value

        if value:
            self._add_filepaths(value)
        self._in_set_value = False

    def current_value(self):
        model = self._files_proxy_model
        filepaths = set()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            dirpath = index.data(DIRPATH_ROLE)
            filenames = index.data(FILENAMES_ROLE)
            for filename in filenames:
                filepaths.add(os.path.join(dirpath, filename))
        return filepaths

    def set_filters(self, folders_allowed, exts_filter):
        self._files_proxy_model.set_allow_folders(folders_allowed)
        self._files_proxy_model.set_allowed_extensions(exts_filter)

    def _on_rows_inserted(self, parent_index, start_row, end_row):
        for row in range(start_row, end_row + 1):
            index = self._files_proxy_model.index(row, 0, parent_index)
            item_id = index.data(ITEM_ID_ROLE)
            if item_id in self._widgets_by_id:
                continue
            label = index.data(ITEM_LABEL_ROLE)
            pixmap_icon = index.data(ITEM_ICON_ROLE)

            widget = ItemWidget(item_id, label, pixmap_icon)
            self._files_view.setIndexWidget(index, widget)
            self._files_proxy_model.setData(
                index, widget.sizeHint(), QtCore.Qt.SizeHintRole
            )
            widget.remove_requested.connect(self._on_remove_request)
            self._widgets_by_id[item_id] = widget

        self._files_proxy_model.sort(0)

        if not self._in_set_value:
            self.value_changed.emit()

    def _on_rows_removed(self, parent_index, start_row, end_row):
        available_item_ids = set()
        for row in range(self._files_proxy_model.rowCount()):
            index = self._files_proxy_model.index(row, 0)
            item_id = index.data(ITEM_ID_ROLE)
            available_item_ids.add(index.data(ITEM_ID_ROLE))

        widget_ids = set(self._widgets_by_id.keys())
        for item_id in available_item_ids:
            if item_id in widget_ids:
                widget_ids.remove(item_id)

        for item_id in widget_ids:
            widget = self._widgets_by_id.pop(item_id)
            widget.setVisible(False)
            widget.deleteLater()

        if not self._in_set_value:
            self.value_changed.emit()

    def _on_remove_request(self, item_id):
        found_index = None
        for row in range(self._files_model.rowCount()):
            index = self._files_model.index(row, 0)
            _item_id = index.data(ITEM_ID_ROLE)
            if item_id == _item_id:
                found_index = index
                break

        if found_index is None:
            return

        items_to_delete = self._files_view.get_selected_item_ids()
        if item_id not in items_to_delete:
            items_to_delete = [item_id]

        self._remove_item_by_ids(items_to_delete)

    def sizeHint(self):
        # Get size hints of widget and visible widgets
        result = super(MultiFilesWidget, self).sizeHint()
        if not self._files_view.isVisible():
            not_visible_hint = self._files_view.sizeHint()
        else:
            not_visible_hint = self._empty_widget.sizeHint()

        # Get margins of this widget
        margins = self.layout().contentsMargins()

        # Change size hint based on result of maximum size hint of widgets
        result.setWidth(max(
            result.width(),
            not_visible_hint.width() + margins.left() + margins.right()
        ))
        result.setHeight(max(
            result.height(),
            not_visible_hint.height() + margins.top() + margins.bottom()
        ))

        return result

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            event.setDropAction(QtCore.Qt.CopyAction)
            event.accept()

    def dragLeaveEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            filepaths = []
            for url in mime_data.urls():
                filepath = url.toLocalFile()
                if os.path.exists(filepath):
                    filepaths.append(filepath)
            if filepaths:
                self._add_filepaths(filepaths)
        event.accept()

    def _add_filepaths(self, filepaths):
        self._files_model.add_filepaths(filepaths)
        self._update_visibility()

    def _remove_item_by_ids(self, item_ids):
        self._files_model.remove_item_by_ids(item_ids)
        self._update_visibility()

    def _update_visibility(self):
        files_exists = self._files_model.rowCount() > 0
        self._files_view.setVisible(files_exists)
        self._empty_widget.setVisible(not files_exists)


class SingleFileWidget(QtWidgets.QWidget):
    value_changed = QtCore.Signal()

    def __init__(self, parent):
        super(SingleFileWidget, self).__init__(parent)

        self.setAcceptDrops(True)

        filepath_input = QtWidgets.QLineEdit(self)

        browse_btn = QtWidgets.QPushButton("Browse", self)
        browse_btn.setVisible(False)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(filepath_input, 1)
        layout.addWidget(browse_btn, 0)

        browse_btn.clicked.connect(self._on_browse_clicked)
        filepath_input.textChanged.connect(self._on_text_change)

        self._in_set_value = False

        self._filepath_input = filepath_input
        self._folders_allowed = False
        self._exts_filter = []

    def set_value(self, value, multivalue):
        self._in_set_value = True

        if multivalue:
            set_value = set(value)
            if len(set_value) == 1:
                value = tuple(set_value)[0]
            else:
                value = "< Multiselection >"
        self._filepath_input.setText(value)

        self._in_set_value = False

    def current_value(self):
        return self._filepath_input.text()

    def set_filters(self, folders_allowed, exts_filter):
        self._folders_allowed = folders_allowed
        self._exts_filter = exts_filter

    def _on_text_change(self, text):
        if not self._in_set_value:
            self.value_changed.emit()

    def _on_browse_clicked(self):
        # TODO implement file dialog logic in '_on_browse_clicked'
        print("_on_browse_clicked")

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return

        filepaths = []
        for url in mime_data.urls():
            filepath = url.toLocalFile()
            if os.path.exists(filepath):
                filepaths.append(filepath)

        # TODO add folder, extensions check
        if len(filepaths) == 1:
            event.setDropAction(QtCore.Qt.CopyAction)
            event.accept()

    def dragLeaveEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            filepaths = []
            for url in mime_data.urls():
                filepath = url.toLocalFile()
                if os.path.exists(filepath):
                    filepaths.append(filepath)
            # TODO filter check
            if len(filepaths) == 1:
                self.set_value(filepaths[0], False)
        event.accept()
