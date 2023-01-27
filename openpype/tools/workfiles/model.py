import os
import logging

from qtpy import QtCore, QtGui
import qtawesome

from openpype.client import (
    get_subsets,
    get_versions,
    get_representations,
)
from openpype.style import (
    get_default_entity_icon_color,
    get_disabled_entity_icon_color,
)
from openpype.pipeline import get_representation_path

log = logging.getLogger(__name__)


FILEPATH_ROLE = QtCore.Qt.UserRole + 2
DATE_MODIFIED_ROLE = QtCore.Qt.UserRole + 3
ITEM_ID_ROLE = QtCore.Qt.UserRole + 4


class WorkAreaFilesModel(QtGui.QStandardItemModel):
    """Model is looking into one folder for files with extension."""

    def __init__(self, extensions, *args, **kwargs):
        super(WorkAreaFilesModel, self).__init__(*args, **kwargs)

        self.setColumnCount(2)

        self._root = None
        self._file_extensions = extensions
        self._invalid_path_item = None
        self._empty_root_item = None
        self._file_icon = qtawesome.icon(
            "fa.file-o",
            color=get_default_entity_icon_color()
        )
        self._invalid_item_visible = False
        self._items_by_filename = {}

    def _get_invalid_path_item(self):
        if self._invalid_path_item is None:
            message = "Work Area does not exist. Use Save As to create it."
            item = QtGui.QStandardItem(message)
            icon = qtawesome.icon(
                "fa.times",
                color=get_disabled_entity_icon_color()
            )
            item.setData(icon, QtCore.Qt.DecorationRole)
            item.setFlags(QtCore.Qt.NoItemFlags)
            item.setColumnCount(self.columnCount())
            self._invalid_path_item = item
        return self._invalid_path_item

    def _get_empty_root_item(self):
        if self._empty_root_item is None:
            message = "Work Area is empty."
            item = QtGui.QStandardItem(message)
            icon = qtawesome.icon(
                "fa.times",
                color=get_disabled_entity_icon_color()
            )
            item.setData(icon, QtCore.Qt.DecorationRole)
            item.setFlags(QtCore.Qt.NoItemFlags)
            item.setColumnCount(self.columnCount())
            self._empty_root_item = item
        return self._empty_root_item

    def set_root(self, root):
        """Change directory where to look for file."""
        self._root = root
        if root and not os.path.exists(root):
            log.debug("Work Area does not exist: {}".format(root))
        self.refresh()

    def _clear(self):
        root_item = self.invisibleRootItem()
        rows = root_item.rowCount()
        if rows > 0:
            if self._invalid_item_visible:
                for row in range(rows):
                    root_item.takeRow(row)
            else:
                root_item.removeRows(0, rows)
        self._items_by_filename = {}

    def refresh(self):
        """Refresh and update model items."""
        root_item = self.invisibleRootItem()
        # If path is not set or does not exist then add invalid path item
        if not self._root or not os.path.exists(self._root):
            self._clear()
            # Add Work Area does not exist placeholder
            item = self._get_invalid_path_item()
            root_item.appendRow(item)
            self._invalid_item_visible = True
            return

        # Clear items if previous refresh set '_invalid_item_visible' to True
        # - Invalid items are not stored to '_items_by_filename' so they would
        #   not be removed
        if self._invalid_item_visible:
            self._clear()

        # Check for new items that should be added and items that should be
        #   removed
        new_items = []
        items_to_remove = set(self._items_by_filename.keys())
        for filename in os.listdir(self._root):
            filepath = os.path.join(self._root, filename)
            if os.path.isdir(filepath):
                continue

            ext = os.path.splitext(filename)[1]
            if ext not in self._file_extensions:
                continue

            modified = os.path.getmtime(filepath)

            # Use existing item or create new one
            if filename in items_to_remove:
                items_to_remove.remove(filename)
                item = self._items_by_filename[filename]
            else:
                item = QtGui.QStandardItem(filename)
                item.setColumnCount(self.columnCount())
                item.setFlags(
                    QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
                )
                item.setData(self._file_icon, QtCore.Qt.DecorationRole)
                new_items.append(item)
                self._items_by_filename[filename] = item
            # Update data that may be different
            item.setData(filepath, FILEPATH_ROLE)
            item.setData(modified, DATE_MODIFIED_ROLE)

        # Add new items if there are any
        if new_items:
            root_item.appendRows(new_items)

        # Remove items that are no longer available
        for filename in items_to_remove:
            item = self._items_by_filename.pop(filename)
            root_item.removeRow(item.row())

        # Add empty root item if there are not filenames that could be shown
        if root_item.rowCount() > 0:
            self._invalid_item_visible = False
        else:
            self._invalid_item_visible = True
            item = self._get_empty_root_item()
            root_item.appendRow(item)

    def has_valid_items(self):
        """Directory has files that are listed in items."""
        return not self._invalid_item_visible

    def flags(self, index):
        # Use flags of first column for all columns
        if index.column() != 0:
            index = self.index(index.row(), 0, index.parent())
        return super(WorkAreaFilesModel, self).flags(index)

    def data(self, index, role=None):
        if role is None:
            role = QtCore.Qt.DisplayRole

        # Handle roles for first column
        if index.column() == 1:
            if role == QtCore.Qt.DecorationRole:
                return None

            if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
                role = DATE_MODIFIED_ROLE
            index = self.index(index.row(), 0, index.parent())

        return super(WorkAreaFilesModel, self).data(index, role)

    def headerData(self, section, orientation, role):
        # Show nice labels in the header
        if (
            role == QtCore.Qt.DisplayRole
            and orientation == QtCore.Qt.Horizontal
        ):
            if section == 0:
                return "Name"
            elif section == 1:
                return "Date modified"

        return super(WorkAreaFilesModel, self).headerData(
            section, orientation, role
        )


class PublishFilesModel(QtGui.QStandardItemModel):
    """Model filling files with published files calculated from representation.

    This model looks for workfile family representations based on selected
    asset and task.

    Asset must set to be able look for representations that could be used.
    Task is used to filter representations by task.
    Model has few filter criteria for filling.
    - First criteria is that version document must have "workfile" in
        "data.families".
    - Second cirteria is that representation must have extension same as
        defined extensions
    - If task is set then representation must have 'task["name"]' with same
        name.
    """

    def __init__(self, extensions, dbcon, anatomy, *args, **kwargs):
        super(PublishFilesModel, self).__init__(*args, **kwargs)

        self.setColumnCount(2)

        self._dbcon = dbcon
        self._anatomy = anatomy

        self._file_extensions = extensions

        self._invalid_context_item = None
        self._empty_root_item = None
        self._file_icon = qtawesome.icon(
            "fa.file-o",
            color=get_default_entity_icon_color()
        )
        self._invalid_icon = qtawesome.icon(
            "fa.times",
            color=get_disabled_entity_icon_color()
        )
        self._invalid_item_visible = False

        self._items_by_id = {}

        self._asset_id = None
        self._task_name = None

    @property
    def project_name(self):
        return self._dbcon.Session["AVALON_PROJECT"]

    def _set_item_invalid(self, item):
        item.setFlags(QtCore.Qt.NoItemFlags)
        item.setData(self._invalid_icon, QtCore.Qt.DecorationRole)

    def _set_item_valid(self, item):
        item.setFlags(
            QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        )
        item.setData(self._file_icon, QtCore.Qt.DecorationRole)

    def _get_invalid_context_item(self):
        if self._invalid_context_item is None:
            item = QtGui.QStandardItem("Selected context is not valid.")
            item.setColumnCount(self.columnCount())
            self._set_item_invalid(item)
            self._invalid_context_item = item
        return self._invalid_context_item

    def _get_empty_root_item(self):
        if self._empty_root_item is None:
            item = QtGui.QStandardItem("Didn't find any published workfiles.")
            item.setColumnCount(self.columnCount())
            self._set_item_invalid(item)
            self._empty_root_item = item
        return self._empty_root_item

    def set_context(self, asset_id, task_name):
        """Change context to asset and task.

        Args:
            asset_id (ObjectId): Id of selected asset.
            task_name (str): Name of selected task.
        """
        self._asset_id = asset_id
        self._task_name = task_name
        self.refresh()

    def _clear(self):
        root_item = self.invisibleRootItem()
        rows = root_item.rowCount()
        if rows > 0:
            if self._invalid_item_visible:
                for row in range(rows):
                    root_item.takeRow(row)
            else:
                root_item.removeRows(0, rows)
        self._items_by_id = {}

    def _get_workfie_representations(self):
        output = []
        # Get subset docs of asset
        subset_docs = get_subsets(
            self.project_name,
            asset_ids=[self._asset_id],
            fields=["_id", "name"]
        )

        subset_ids = [subset_doc["_id"] for subset_doc in subset_docs]
        if not subset_ids:
            return output

        # Get version docs of subsets with their families
        version_docs = get_versions(
            self.project_name,
            subset_ids=subset_ids,
            fields=["_id", "parent", "data.families"]
        )

        # Filter versions if they contain 'workfile' family
        filtered_versions = []
        for version_doc in version_docs:
            data = version_doc.get("data") or {}
            families = data.get("families") or []
            if "workfile" in families:
                filtered_versions.append(version_doc)

        version_ids = [version_doc["_id"] for version_doc in filtered_versions]
        if not version_ids:
            return output

        # Query representations of filtered versions and add filter for
        #   extension
        extensions = [ext.replace(".", "") for ext in self._file_extensions]
        repre_docs = get_representations(
            self.project_name,
            version_ids=version_ids,
            context_filters={"ext": extensions}
        )

        # Filter queried representations by task name if task is set
        filtered_repre_docs = []
        for repre_doc in repre_docs:
            if self._task_name is None:
                filtered_repre_docs.append(repre_doc)
                continue

            task_info = repre_doc["context"].get("task")
            if not task_info:
                print("Not task info")
                continue

            if isinstance(task_info, dict):
                task_name = task_info.get("name")
            else:
                task_name = task_info

            if task_name == self._task_name:
                filtered_repre_docs.append(repre_doc)

        # Collect paths of representations
        for repre_doc in filtered_repre_docs:
            path = get_representation_path(
                repre_doc, root=self._anatomy.roots
            )
            output.append((path, repre_doc["_id"]))
        return output

    def refresh(self):
        root_item = self.invisibleRootItem()
        if not self._asset_id:
            self._clear()
            # Add Work Area does not exist placeholder
            item = self._get_invalid_context_item()
            root_item.appendRow(item)
            self._invalid_item_visible = True
            return

        if self._invalid_item_visible:
            self._clear()

        new_items = []
        items_to_remove = set(self._items_by_id.keys())
        for item in self._get_workfie_representations():
            filepath, repre_id = item
            # TODO handle empty filepaths
            if not filepath:
                continue
            filename = os.path.basename(filepath)

            if repre_id in items_to_remove:
                items_to_remove.remove(repre_id)
                item = self._items_by_id[repre_id]
            else:
                item = QtGui.QStandardItem(filename)
                item.setColumnCount(self.columnCount())
                new_items.append(item)
                self._items_by_id[repre_id] = item

            if os.path.exists(filepath):
                modified = os.path.getmtime(filepath)
                tooltip = None
                self._set_item_valid(item)
            else:
                modified = None
                tooltip = "File is not available from this machine"
                self._set_item_invalid(item)

            item.setData(tooltip, QtCore.Qt.ToolTipRole)
            item.setData(filepath, FILEPATH_ROLE)
            item.setData(modified, DATE_MODIFIED_ROLE)
            item.setData(repre_id, ITEM_ID_ROLE)

        if new_items:
            root_item.appendRows(new_items)

        for filename in items_to_remove:
            item = self._items_by_id.pop(filename)
            root_item.removeRow(item.row())

        if root_item.rowCount() > 0:
            self._invalid_item_visible = False
        else:
            self._invalid_item_visible = True
            item = self._get_empty_root_item()
            root_item.appendRow(item)

    def has_valid_items(self):
        return not self._invalid_item_visible

    def flags(self, index):
        if index.column() != 0:
            index = self.index(index.row(), 0, index.parent())
        return super(PublishFilesModel, self).flags(index)

    def data(self, index, role=None):
        if role is None:
            role = QtCore.Qt.DisplayRole

        if index.column() == 1:
            if role == QtCore.Qt.DecorationRole:
                return None

            if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
                role = DATE_MODIFIED_ROLE
            index = self.index(index.row(), 0, index.parent())

        return super(PublishFilesModel, self).data(index, role)

    def headerData(self, section, orientation, role):
        # Show nice labels in the header
        if (
            role == QtCore.Qt.DisplayRole
            and orientation == QtCore.Qt.Horizontal
        ):
            if section == 0:
                return "Name"
            elif section == 1:
                return "Date modified"

        return super(PublishFilesModel, self).headerData(
            section, orientation, role
        )
