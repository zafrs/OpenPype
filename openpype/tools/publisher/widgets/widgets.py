# -*- coding: utf-8 -*-
import os
import re
import copy
import functools
import uuid
import shutil
import collections
from qtpy import QtWidgets, QtCore, QtGui
import qtawesome

from openpype import AYON_SERVER_ENABLED
from openpype.lib.attribute_definitions import UnknownDef
from openpype.tools.attribute_defs import create_widget_for_attr_def
from openpype.tools import resources
from openpype.tools.flickcharm import FlickCharm
from openpype.tools.utils import (
    PlaceholderLineEdit,
    IconButton,
    PixmapLabel,
    BaseClickableFrame,
    set_style_property,
)
from openpype.style import get_objected_colors
from openpype.pipeline.create import (
    SUBSET_NAME_ALLOWED_SYMBOLS,
    TaskNotSetError,
)
from .thumbnail_widget import ThumbnailWidget
from .assets_widget import AssetsDialog
from .tasks_widget import TasksModel
from .icons import (
    get_pixmap,
    get_icon_path
)

from ..constants import (
    VARIANT_TOOLTIP,
    ResetKeySequence,
    INPUTS_LAYOUT_HSPACING,
    INPUTS_LAYOUT_VSPACING,
)

FA_PREFIXES = ["", "fa.", "fa5.", "fa5b.", "fa5s.", "ei.", "mdi."]


def parse_icon_def(
    icon_def, default_width=None, default_height=None, color=None
):
    if not icon_def:
        return None

    if isinstance(icon_def, QtGui.QPixmap):
        return icon_def

    color = color or "white"
    default_width = default_width or 512
    default_height = default_height or 512

    if isinstance(icon_def, QtGui.QIcon):
        return icon_def.pixmap(default_width, default_height)

    try:
        if os.path.exists(icon_def):
            return QtGui.QPixmap(icon_def)
    except Exception:
        # TODO logging
        pass

    for prefix in FA_PREFIXES:
        try:
            icon_name = "{}{}".format(prefix, icon_def)
            icon = qtawesome.icon(icon_name, color=color)
            return icon.pixmap(default_width, default_height)
        except Exception:
            # TODO logging
            continue


class PublishPixmapLabel(PixmapLabel):
    def _get_pix_size(self):
        size = self.fontMetrics().height()
        size += size % 2
        return size, size


class IconValuePixmapLabel(PublishPixmapLabel):
    """Label resizing to width and height of font.

    Handle icon parsing from creators/instances. Using of QAwesome module
    of path to images.
    """
    default_size = 200

    def __init__(self, icon_def, parent):
        source_pixmap = self._parse_icon_def(icon_def)

        super(IconValuePixmapLabel, self).__init__(source_pixmap, parent)

    def set_icon_def(self, icon_def):
        """Set icon by it's definition name.

        Args:
            icon_def (str): Name of FontAwesome icon or path to image.
        """
        source_pixmap = self._parse_icon_def(icon_def)
        self.set_source_pixmap(source_pixmap)

    def _default_pixmap(self):
        pix = QtGui.QPixmap(1, 1)
        pix.fill(QtCore.Qt.transparent)
        return pix

    def _parse_icon_def(self, icon_def):
        icon = parse_icon_def(icon_def, self.default_size, self.default_size)
        if icon:
            return icon
        return self._default_pixmap()


class ContextWarningLabel(PublishPixmapLabel):
    """Pixmap label with warning icon."""
    def __init__(self, parent):
        pix = get_pixmap("warning")

        super(ContextWarningLabel, self).__init__(pix, parent)

        self.setToolTip(
            "Contain invalid context. Please check details."
        )
        self.setObjectName("FamilyIconLabel")


class PublishIconBtn(IconButton):
    """Button using alpha of source image to redraw with different color.

    Main class for buttons showed in publisher.

    TODO:
    Add different states:
    - normal           : before publishing
    - publishing       : publishing is running
    - validation error : validation error happened
    - error            : other error happened
    - success          : publishing finished
    """

    def __init__(self, pixmap_path, *args, **kwargs):
        super(PublishIconBtn, self).__init__(*args, **kwargs)

        colors = get_objected_colors()
        icon = self.generate_icon(
            pixmap_path,
            enabled_color=colors["font"].get_qcolor(),
            disabled_color=colors["font-disabled"].get_qcolor())
        self.setIcon(icon)

    def generate_icon(self, pixmap_path, enabled_color, disabled_color):
        icon = QtGui.QIcon()
        image = QtGui.QImage(pixmap_path)
        enabled_pixmap = self.paint_image_with_color(image, enabled_color)
        icon.addPixmap(enabled_pixmap, QtGui.QIcon.Normal)
        disabled_pixmap = self.paint_image_with_color(image, disabled_color)
        icon.addPixmap(disabled_pixmap, QtGui.QIcon.Disabled)
        return icon

    @staticmethod
    def paint_image_with_color(image, color):
        """Redraw image with single color using it's alpha.

        It is expected that input image is singlecolor image with alpha.

        Args:
            image (QImage): Loaded image with alpha.
            color (QColor): Color that will be used to paint image.
        """
        width = image.width()
        height = image.height()
        partition = 8
        part_w = int(width / partition)
        part_h = int(height / partition)
        part_w -= part_w % 2
        part_h -= part_h % 2
        scaled_image = image.scaled(
            width - (2 * part_w),
            height - (2 * part_h),
            QtCore.Qt.IgnoreAspectRatio,
            QtCore.Qt.SmoothTransformation
        )
        alpha_mask = scaled_image.createAlphaMask()
        alpha_region = QtGui.QRegion(QtGui.QBitmap.fromImage(alpha_mask))
        alpha_region.translate(part_w, part_h)

        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setClipRegion(alpha_region)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        painter.drawRect(QtCore.QRect(0, 0, width, height))
        painter.end()

        return pixmap


class CreateBtn(PublishIconBtn):
    """Create instance button."""

    def __init__(self, parent=None):
        icon_path = get_icon_path("create")
        super(CreateBtn, self).__init__(icon_path, "Create", parent)
        self.setToolTip("Create new {}/s".format(
            "product" if AYON_SERVER_ENABLED else "subset"
        ))
        self.setLayoutDirection(QtCore.Qt.RightToLeft)


class SaveBtn(PublishIconBtn):
    """Save context and instances information."""
    def __init__(self, parent=None):
        icon_path = get_icon_path("save")
        super(SaveBtn, self).__init__(icon_path, parent)
        self.setToolTip(
            "Save changes ({})".format(
                QtGui.QKeySequence(QtGui.QKeySequence.Save).toString()
            )
        )


class ResetBtn(PublishIconBtn):
    """Publish reset button."""
    def __init__(self, parent=None):
        icon_path = get_icon_path("refresh")
        super(ResetBtn, self).__init__(icon_path, parent)
        self.setToolTip(
            "Reset & discard changes ({})".format(ResetKeySequence.toString())
        )


class StopBtn(PublishIconBtn):
    """Publish stop button."""
    def __init__(self, parent):
        icon_path = get_icon_path("stop")
        super(StopBtn, self).__init__(icon_path, parent)
        self.setToolTip("Stop/Pause publishing")


class ValidateBtn(PublishIconBtn):
    """Publish validate button."""
    def __init__(self, parent=None):
        icon_path = get_icon_path("validate")
        super(ValidateBtn, self).__init__(icon_path, parent)
        self.setToolTip("Validate")


class PublishBtn(PublishIconBtn):
    """Publish start publish button."""
    def __init__(self, parent=None):
        icon_path = get_icon_path("play")
        super(PublishBtn, self).__init__(icon_path, "Publish", parent)
        self.setToolTip("Publish")


class CreateInstanceBtn(PublishIconBtn):
    """Create add button."""
    def __init__(self, parent=None):
        icon_path = get_icon_path("add")
        super(CreateInstanceBtn, self).__init__(icon_path, parent)
        self.setToolTip("Create new instance")


class PublishReportBtn(PublishIconBtn):
    """Publish report button."""

    triggered = QtCore.Signal(str)

    def __init__(self, parent=None):
        icon_path = get_icon_path("view_report")
        super(PublishReportBtn, self).__init__(icon_path, parent)
        self.setToolTip("Copy report")
        self._actions = []

    def add_action(self, label, identifier):
        self._actions.append(
            (label, identifier)
        )

    def _on_action_trigger(self, identifier):
        self.triggered.emit(identifier)

    def mouseReleaseEvent(self, event):
        super(PublishReportBtn, self).mouseReleaseEvent(event)
        menu = QtWidgets.QMenu(self)
        actions = []
        for item in self._actions:
            label, identifier = item
            action = QtWidgets.QAction(label, menu)
            action.triggered.connect(
                functools.partial(self._on_action_trigger, identifier)
            )
            actions.append(action)
        menu.addActions(actions)
        menu.exec_(event.globalPos())


class RemoveInstanceBtn(PublishIconBtn):
    """Create remove button."""
    def __init__(self, parent=None):
        icon_path = resources.get_icon_path("delete")
        super(RemoveInstanceBtn, self).__init__(icon_path, parent)
        self.setToolTip("Remove selected instances")


class ChangeViewBtn(PublishIconBtn):
    """Create toggle view button."""
    def __init__(self, parent=None):
        icon_path = get_icon_path("change_view")
        super(ChangeViewBtn, self).__init__(icon_path, parent)
        self.setToolTip("Swap between views")


class AbstractInstanceView(QtWidgets.QWidget):
    """Abstract class for instance view in creation part."""
    selection_changed = QtCore.Signal()
    active_changed = QtCore.Signal()
    # Refreshed attribute is not changed by view itself
    # - widget which triggers `refresh` is changing the state
    # TODO store that information in widget which cares about refreshing
    refreshed = False

    def set_refreshed(self, refreshed):
        """View is refreshed with last instances.

        Views are not updated all the time. Only if are visible.
        """
        self.refreshed = refreshed

    def refresh(self):
        """Refresh instances in the view from current `CreatedContext`."""
        raise NotImplementedError((
            "{} Method 'refresh' is not implemented."
        ).format(self.__class__.__name__))

    def has_items(self):
        """View has at least one item.

        This is more a question for controller but is called from widget
        which should probably should not use controller.

        Returns:
            bool: There is at least one instance or conversion item.
        """

        raise NotImplementedError((
            "{} Method 'has_items' is not implemented."
        ).format(self.__class__.__name__))

    def get_selected_items(self):
        """Selected instances required for callbacks.

        Example: When delete button is clicked to know what should be deleted.
        """

        raise NotImplementedError((
            "{} Method 'get_selected_items' is not implemented."
        ).format(self.__class__.__name__))

    def set_selected_items(self, instance_ids, context_selected):
        """Change selection for instances and context.

        Used to applying selection from one view to other.

        Args:
            instance_ids (List[str]): Selected instance ids.
            context_selected (bool): Context is selected.
        """

        raise NotImplementedError((
            "{} Method 'set_selected_items' is not implemented."
        ).format(self.__class__.__name__))

    def set_active_toggle_enabled(self, enabled):
        """Instances are disabled for changing enabled state.

        Active state should stay the same until is "unset".

        Args:
            enabled (bool): Instance state can be changed.
        """

        raise NotImplementedError((
            "{} Method 'set_active_toggle_enabled' is not implemented."
        ).format(self.__class__.__name__))


class ClickableLineEdit(QtWidgets.QLineEdit):
    """QLineEdit capturing left mouse click.

    Triggers `clicked` signal on mouse click.
    """
    clicked = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super(ClickableLineEdit, self).__init__(*args, **kwargs)
        self.setReadOnly(True)
        self._mouse_pressed = False

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._mouse_pressed = True
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._mouse_pressed:
            self._mouse_pressed = False
            if self.rect().contains(event.pos()):
                self.clicked.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()


class AssetsField(BaseClickableFrame):
    """Field where asset name of selected instance/s is showed.

    Click on the field will trigger `AssetsDialog`.
    """
    value_changed = QtCore.Signal()

    def __init__(self, controller, parent):
        super(AssetsField, self).__init__(parent)
        self.setObjectName("AssetNameInputWidget")

        # Don't use 'self' for parent!
        # - this widget has specific styles
        dialog = AssetsDialog(controller, parent)

        name_input = ClickableLineEdit(self)
        name_input.setObjectName("AssetNameInput")

        icon_name = "fa.window-maximize"
        icon = qtawesome.icon(icon_name, color="white")
        icon_btn = QtWidgets.QPushButton(self)
        icon_btn.setIcon(icon)
        icon_btn.setObjectName("AssetNameInputButton")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(name_input, 1)
        layout.addWidget(icon_btn, 0)

        # Make sure all widgets are vertically extended to highest widget
        for widget in (
            name_input,
            icon_btn
        ):
            size_policy = widget.sizePolicy()
            size_policy.setVerticalPolicy(
                QtWidgets.QSizePolicy.MinimumExpanding)
            widget.setSizePolicy(size_policy)
        name_input.clicked.connect(self._mouse_release_callback)
        icon_btn.clicked.connect(self._mouse_release_callback)
        dialog.finished.connect(self._on_dialog_finish)

        self._dialog = dialog
        self._name_input = name_input
        self._icon_btn = icon_btn

        self._origin_value = []
        self._origin_selection = []
        self._selected_items = []
        self._has_value_changed = False
        self._is_valid = True
        self._multiselection_text = None

    def _on_dialog_finish(self, result):
        if not result:
            return

        asset_name = self._dialog.get_selected_asset()
        if asset_name is None:
            return

        self._selected_items = [asset_name]
        self._has_value_changed = (
            self._origin_value != self._selected_items
        )
        self.set_text(asset_name)
        self._set_is_valid(True)

        self.value_changed.emit()

    def _mouse_release_callback(self):
        self._dialog.set_selected_assets(self._selected_items)
        self._dialog.open()

    def set_multiselection_text(self, text):
        """Change text for multiselection of different assets.

        When there are selected multiple instances at once and they don't have
        same asset in context.
        """
        self._multiselection_text = text

    def _set_is_valid(self, valid):
        if valid == self._is_valid:
            return
        self._is_valid = valid
        state = ""
        if not valid:
            state = "invalid"
        self._set_state_property(state)

    def _set_state_property(self, state):
        set_style_property(self, "state", state)
        set_style_property(self._name_input, "state", state)
        set_style_property(self._icon_btn, "state", state)

    def is_valid(self):
        """Is asset valid."""
        return self._is_valid

    def has_value_changed(self):
        """Value of asset has changed."""
        return self._has_value_changed

    def get_selected_items(self):
        """Selected asset names."""
        return list(self._selected_items)

    def set_text(self, text):
        """Set text in text field.

        Does not change selected items (assets).
        """
        self._name_input.setText(text)
        self._name_input.end(False)

    def set_selected_items(self, asset_names=None):
        """Set asset names for selection of instances.

        Passed asset names are validated and if there are 2 or more different
        asset names then multiselection text is shown.

        Args:
            asset_names (list, tuple, set, NoneType): List of asset names.
        """
        if asset_names is None:
            asset_names = []

        self._has_value_changed = False
        self._origin_value = list(asset_names)
        self._selected_items = list(asset_names)
        is_valid = True
        if not asset_names:
            self.set_text("")

        elif len(asset_names) == 1:
            asset_name = tuple(asset_names)[0]
            is_valid = self._dialog.name_is_valid(asset_name)
            self.set_text(asset_name)
        else:
            for asset_name in asset_names:
                is_valid = self._dialog.name_is_valid(asset_name)
                if not is_valid:
                    break

            multiselection_text = self._multiselection_text
            if multiselection_text is None:
                multiselection_text = "|".join(asset_names)
            self.set_text(multiselection_text)

        self._set_is_valid(is_valid)

    def reset_to_origin(self):
        """Change to asset names set with last `set_selected_items` call."""
        self.set_selected_items(self._origin_value)

    def confirm_value(self):
        self._origin_value = copy.deepcopy(self._selected_items)
        self._has_value_changed = False


class TasksComboboxProxy(QtCore.QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        super(TasksComboboxProxy, self).__init__(*args, **kwargs)
        self._filter_empty = False

    def set_filter_empty(self, filter_empty):
        if self._filter_empty is filter_empty:
            return
        self._filter_empty = filter_empty
        self.invalidate()

    def filterAcceptsRow(self, source_row, parent_index):
        if self._filter_empty:
            model = self.sourceModel()
            source_index = model.index(
                source_row, self.filterKeyColumn(), parent_index
            )
            if not source_index.data(QtCore.Qt.DisplayRole):
                return False
        return True


class TasksCombobox(QtWidgets.QComboBox):
    """Combobox to show tasks for selected instances.

    Combobox gives ability to select only from intersection of task names for
    asset names in selected instances.

    If asset names in selected instances does not have same tasks then combobox
    will be empty.
    """
    value_changed = QtCore.Signal()

    def __init__(self, controller, parent):
        super(TasksCombobox, self).__init__(parent)
        self.setObjectName("TasksCombobox")

        # Set empty delegate to propagate stylesheet to a combobox
        delegate = QtWidgets.QStyledItemDelegate()
        self.setItemDelegate(delegate)

        model = TasksModel(controller, True)
        proxy_model = TasksComboboxProxy()
        proxy_model.setSourceModel(model)
        self.setModel(proxy_model)

        self.currentIndexChanged.connect(self._on_index_change)

        self._delegate = delegate
        self._model = model
        self._proxy_model = proxy_model
        self._origin_value = []
        self._origin_selection = []
        self._selected_items = []
        self._has_value_changed = False
        self._ignore_index_change = False
        self._multiselection_text = None
        self._is_valid = True

        self._text = None

        # Make sure combobox is extended horizontally
        size_policy = self.sizePolicy()
        size_policy.setHorizontalPolicy(
            QtWidgets.QSizePolicy.MinimumExpanding)
        self.setSizePolicy(size_policy)

    def set_invalid_empty_task(self, invalid=True):
        self._proxy_model.set_filter_empty(invalid)
        if invalid:
            self._set_is_valid(False)
            self.set_text(
                "< One or more {} require Task selected >".format(
                    "products" if AYON_SERVER_ENABLED else "subsets"
                )
            )
        else:
            self.set_text(None)

    def set_multiselection_text(self, text):
        """Change text shown when multiple different tasks are in context."""
        self._multiselection_text = text

    def _on_index_change(self):
        if self._ignore_index_change:
            return

        self.set_text(None)
        text = self.currentText()
        idx = self.findText(text)
        if idx < 0:
            return

        self._set_is_valid(True)
        self._selected_items = [text]
        self._has_value_changed = (
            self._origin_selection != self._selected_items
        )

        self.value_changed.emit()

    def set_text(self, text):
        """Set context shown in combobox without changing selected items."""
        if text == self._text:
            return

        self._text = text
        self.repaint()

    def paintEvent(self, event):
        """Paint custom text without using QLineEdit.

        The easiest way how to draw custom text in combobox and keep combobox
        properties and event handling.
        """
        painter = QtGui.QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.Text))
        opt = QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(opt)
        if self._text is not None:
            opt.currentText = self._text

        style = self.style()
        style.drawComplexControl(
            QtWidgets.QStyle.CC_ComboBox, opt, painter, self
        )
        style.drawControl(
            QtWidgets.QStyle.CE_ComboBoxLabel, opt, painter, self
        )
        painter.end()

    def is_valid(self):
        """Are all selected items valid."""
        return self._is_valid

    def has_value_changed(self):
        """Did selection of task changed."""
        return self._has_value_changed

    def _set_is_valid(self, valid):
        if valid == self._is_valid:
            return
        self._is_valid = valid
        state = ""
        if not valid:
            state = "invalid"
        self._set_state_property(state)

    def _set_state_property(self, state):
        current_value = self.property("state")
        if current_value != state:
            self.setProperty("state", state)
            self.style().polish(self)

    def get_selected_items(self):
        """Get selected tasks.

        If value has changed then will return list with single item.

        Returns:
            list: Selected tasks.
        """
        return list(self._selected_items)

    def set_asset_names(self, asset_names):
        """Set asset names for which should show tasks."""
        self._ignore_index_change = True

        self._model.set_asset_names(asset_names)
        self._proxy_model.set_filter_empty(False)
        self._proxy_model.sort(0)

        self._ignore_index_change = False

        # It is a bug if not exactly one asset got here
        if len(asset_names) != 1:
            self.set_selected_item("")
            self._set_is_valid(False)
            return

        asset_name = tuple(asset_names)[0]

        is_valid = False
        if self._selected_items:
            is_valid = True

        valid_task_names = []
        for task_name in self._selected_items:
            _is_valid = self._model.is_task_name_valid(asset_name, task_name)
            if _is_valid:
                valid_task_names.append(task_name)
            else:
                is_valid = _is_valid

        self._selected_items = valid_task_names
        if len(self._selected_items) == 0:
            self.set_selected_item("")

        elif len(self._selected_items) == 1:
            self.set_selected_item(self._selected_items[0])

        else:
            multiselection_text = self._multiselection_text
            if multiselection_text is None:
                multiselection_text = "|".join(self._selected_items)
            self.set_selected_item(multiselection_text)

        self._set_is_valid(is_valid)

    def confirm_value(self, asset_names):
        new_task_name = self._selected_items[0]
        self._origin_value = [
            (asset_name, new_task_name)
            for asset_name in asset_names
        ]
        self._origin_selection = copy.deepcopy(self._selected_items)
        self._has_value_changed = False

    def set_selected_items(self, asset_task_combinations=None):
        """Set items for selected instances.

        Args:
            asset_task_combinations (list): List of tuples. Each item in
                the list contain asset name and task name.
        """
        self._proxy_model.set_filter_empty(False)
        self._proxy_model.sort(0)

        if asset_task_combinations is None:
            asset_task_combinations = []

        task_names = set()
        task_names_by_asset_name = collections.defaultdict(set)
        for asset_name, task_name in asset_task_combinations:
            task_names.add(task_name)
            task_names_by_asset_name[asset_name].add(task_name)
        asset_names = set(task_names_by_asset_name.keys())

        self._ignore_index_change = True

        self._model.set_asset_names(asset_names)

        self._has_value_changed = False

        self._origin_value = copy.deepcopy(asset_task_combinations)

        self._origin_selection = list(task_names)
        self._selected_items = list(task_names)
        # Reset current index
        self.setCurrentIndex(-1)
        is_valid = True
        if not task_names:
            self.set_selected_item("")

        elif len(task_names) == 1:
            task_name = tuple(task_names)[0]
            idx = self.findText(task_name)
            is_valid = not idx < 0
            if not is_valid and len(asset_names) > 1:
                is_valid = self._validate_task_names_by_asset_names(
                    task_names_by_asset_name
                )
            self.set_selected_item(task_name)

        else:
            for task_name in task_names:
                idx = self.findText(task_name)
                is_valid = not idx < 0
                if not is_valid:
                    break

            if not is_valid and len(asset_names) > 1:
                is_valid = self._validate_task_names_by_asset_names(
                    task_names_by_asset_name
                )
            multiselection_text = self._multiselection_text
            if multiselection_text is None:
                multiselection_text = "|".join(task_names)
            self.set_selected_item(multiselection_text)

        self._set_is_valid(is_valid)

        self._ignore_index_change = False

        self.value_changed.emit()

    def _validate_task_names_by_asset_names(self, task_names_by_asset_name):
        for asset_name, task_names in task_names_by_asset_name.items():
            for task_name in task_names:
                if not self._model.is_task_name_valid(asset_name, task_name):
                    return False
        return True

    def set_selected_item(self, item_name):
        """Set task which is set on selected instance.

        Args:
            item_name(str): Task name which should be selected.
        """
        idx = self.findText(item_name)
        # Set current index (must be set to -1 if is invalid)
        self.setCurrentIndex(idx)
        self.set_text(item_name)

    def reset_to_origin(self):
        """Change to task names set with last `set_selected_items` call."""
        self.set_selected_items(self._origin_value)


class VariantInputWidget(PlaceholderLineEdit):
    """Input widget for variant."""
    value_changed = QtCore.Signal()

    def __init__(self, parent):
        super(VariantInputWidget, self).__init__(parent)

        self.setObjectName("VariantInput")
        self.setToolTip(VARIANT_TOOLTIP)

        name_pattern = "^[{}]*$".format(SUBSET_NAME_ALLOWED_SYMBOLS)
        self._name_pattern = name_pattern
        self._compiled_name_pattern = re.compile(name_pattern)

        self._origin_value = []
        self._current_value = []

        self._ignore_value_change = False
        self._has_value_changed = False
        self._multiselection_text = None

        self._is_valid = True

        self.textChanged.connect(self._on_text_change)

    def is_valid(self):
        """Is variant text valid."""
        return self._is_valid

    def has_value_changed(self):
        """Value of variant has changed."""
        return self._has_value_changed

    def _set_state_property(self, state):
        current_value = self.property("state")
        if current_value != state:
            self.setProperty("state", state)
            self.style().polish(self)

    def set_multiselection_text(self, text):
        """Change text of multiselection."""
        self._multiselection_text = text

    def confirm_value(self):
        self._origin_value = copy.deepcopy(self._current_value)
        self._has_value_changed = False

    def _set_is_valid(self, valid):
        if valid == self._is_valid:
            return
        self._is_valid = valid
        state = ""
        if not valid:
            state = "invalid"
        self._set_state_property(state)

    def _on_text_change(self):
        if self._ignore_value_change:
            return

        is_valid = bool(self._compiled_name_pattern.match(self.text()))
        self._set_is_valid(is_valid)

        self._current_value = [self.text()]
        self._has_value_changed = self._current_value != self._origin_value

        self.value_changed.emit()

    def reset_to_origin(self):
        """Set origin value of selected instances."""
        self.set_value(self._origin_value)

    def get_value(self):
        """Get current value.

        Origin value returned if didn't change.
        """
        return copy.deepcopy(self._current_value)

    def set_value(self, variants=None):
        """Set value of currently selected instances."""
        if variants is None:
            variants = []

        self._ignore_value_change = True

        self._has_value_changed = False

        self._origin_value = list(variants)
        self._current_value = list(variants)

        self.setPlaceholderText("")
        if not variants:
            self.setText("")

        elif len(variants) == 1:
            self.setText(self._current_value[0])

        else:
            multiselection_text = self._multiselection_text
            if multiselection_text is None:
                multiselection_text = "|".join(variants)
            self.setText("")
            self.setPlaceholderText(multiselection_text)

        self._ignore_value_change = False


class MultipleItemWidget(QtWidgets.QWidget):
    """Widget for immutable text which can have more than one value.

    Content may be bigger than widget's size and does not have scroll but has
    flick widget on top (is possible to move around with clicked mouse).
    """

    def __init__(self, parent):
        super(MultipleItemWidget, self).__init__(parent)

        model = QtGui.QStandardItemModel()

        view = QtWidgets.QListView(self)
        view.setObjectName("MultipleItemView")
        view.setLayoutMode(QtWidgets.QListView.Batched)
        view.setViewMode(QtWidgets.QListView.IconMode)
        view.setResizeMode(QtWidgets.QListView.Adjust)
        view.setWrapping(False)
        view.setSpacing(2)
        view.setModel(model)
        view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        flick = FlickCharm(parent=view)
        flick.activateOn(view)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view)

        model.rowsInserted.connect(self._on_insert)

        self._view = view
        self._model = model

        self._value = []

    def _on_insert(self):
        self._update_size()

    def _update_size(self):
        model = self._view.model()
        if model.rowCount() == 0:
            return
        height = self._view.sizeHintForRow(0)
        self.setMaximumHeight(height + (2 * self._view.spacing()))

    def showEvent(self, event):
        super(MultipleItemWidget, self).showEvent(event)
        tmp_item = None
        if not self._value:
            # Add temp item to be able calculate maximum height of widget
            tmp_item = QtGui.QStandardItem("tmp")
            self._model.appendRow(tmp_item)
            self._update_size()

        if tmp_item is not None:
            self._model.clear()

    def resizeEvent(self, event):
        super(MultipleItemWidget, self).resizeEvent(event)
        self._update_size()

    def set_value(self, value=None):
        """Set value/s of currently selected instance."""
        if value is None:
            value = []
        self._value = value

        self._model.clear()
        for item_text in value:
            item = QtGui.QStandardItem(item_text)
            item.setEditable(False)
            item.setSelectable(False)
            self._model.appendRow(item)


class GlobalAttrsWidget(QtWidgets.QWidget):
    """Global attributes mainly to define context and subset name of instances.

    Subset name is or may be affected on context. Gives abiity to modify
    context and subset name of instance. This change is not autopromoted but
    must be submitted.

    Warning: Until artist hit `Submit` changes must not be propagated to
    instance data.

    Global attributes contain these widgets:
    Variant:      [  text input  ]
    Asset:        [ asset dialog ]
    Task:         [   combobox   ]
    Family:       [   immutable  ]
    Subset name:  [   immutable  ]
                     [Submit] [Cancel]
    """
    instance_context_changed = QtCore.Signal()

    multiselection_text = "< Multiselection >"
    unknown_value = "N/A"

    def __init__(self, controller, parent):
        super(GlobalAttrsWidget, self).__init__(parent)

        self._controller = controller
        self._current_instances = []

        variant_input = VariantInputWidget(self)
        asset_value_widget = AssetsField(controller, self)
        task_value_widget = TasksCombobox(controller, self)
        family_value_widget = MultipleItemWidget(self)
        subset_value_widget = MultipleItemWidget(self)

        variant_input.set_multiselection_text(self.multiselection_text)
        asset_value_widget.set_multiselection_text(self.multiselection_text)
        task_value_widget.set_multiselection_text(self.multiselection_text)

        variant_input.set_value()
        asset_value_widget.set_selected_items()
        task_value_widget.set_selected_items()
        family_value_widget.set_value()
        subset_value_widget.set_value()

        submit_btn = QtWidgets.QPushButton("Confirm", self)
        cancel_btn = QtWidgets.QPushButton("Cancel", self)
        submit_btn.setEnabled(False)
        cancel_btn.setEnabled(False)

        btns_layout = QtWidgets.QHBoxLayout()
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.addStretch(1)
        btns_layout.setSpacing(5)
        btns_layout.addWidget(submit_btn)
        btns_layout.addWidget(cancel_btn)

        main_layout = QtWidgets.QFormLayout(self)
        main_layout.setHorizontalSpacing(INPUTS_LAYOUT_HSPACING)
        main_layout.setVerticalSpacing(INPUTS_LAYOUT_VSPACING)
        main_layout.addRow("Variant", variant_input)
        main_layout.addRow(
            "Folder" if AYON_SERVER_ENABLED else "Asset",
            asset_value_widget)
        main_layout.addRow("Task", task_value_widget)
        main_layout.addRow(
            "Product type" if AYON_SERVER_ENABLED else "Family",
            family_value_widget)
        main_layout.addRow(
            "Product name" if AYON_SERVER_ENABLED else "Subset",
            subset_value_widget)
        main_layout.addRow(btns_layout)

        variant_input.value_changed.connect(self._on_variant_change)
        asset_value_widget.value_changed.connect(self._on_asset_change)
        task_value_widget.value_changed.connect(self._on_task_change)
        submit_btn.clicked.connect(self._on_submit)
        cancel_btn.clicked.connect(self._on_cancel)

        self.variant_input = variant_input
        self.asset_value_widget = asset_value_widget
        self.task_value_widget = task_value_widget
        self.family_value_widget = family_value_widget
        self.subset_value_widget = subset_value_widget
        self.submit_btn = submit_btn
        self.cancel_btn = cancel_btn

    def _on_submit(self):
        """Commit changes for selected instances."""

        variant_value = None
        asset_name = None
        task_name = None
        if self.variant_input.has_value_changed():
            variant_value = self.variant_input.get_value()[0]

        if self.asset_value_widget.has_value_changed():
            asset_name = self.asset_value_widget.get_selected_items()[0]

        if self.task_value_widget.has_value_changed():
            task_name = self.task_value_widget.get_selected_items()[0]

        subset_names = set()
        invalid_tasks = False
        asset_names = []
        for instance in self._current_instances:
            new_variant_value = instance.get("variant")
            if AYON_SERVER_ENABLED:
                new_asset_name = instance.get("folderPath")
            else:
                new_asset_name = instance.get("asset")
            new_task_name = instance.get("task")
            if variant_value is not None:
                new_variant_value = variant_value

            if asset_name is not None:
                new_asset_name = asset_name

            if task_name is not None:
                new_task_name = task_name

            asset_names.append(new_asset_name)
            try:
                new_subset_name = self._controller.get_subset_name(
                    instance.creator_identifier,
                    new_variant_value,
                    new_task_name,
                    new_asset_name,
                    instance.id,
                )

            except TaskNotSetError:
                invalid_tasks = True
                instance.set_task_invalid(True)
                subset_names.add(instance["subset"])
                continue

            subset_names.add(new_subset_name)
            if variant_value is not None:
                instance["variant"] = variant_value

            if asset_name is not None:
                if AYON_SERVER_ENABLED:
                    instance["folderPath"] = asset_name
                else:
                    instance["asset"] = asset_name

                instance.set_asset_invalid(False)

            if task_name is not None:
                instance["task"] = task_name or None
                instance.set_task_invalid(False)

            instance["subset"] = new_subset_name

        if invalid_tasks:
            self.task_value_widget.set_invalid_empty_task()

        self.subset_value_widget.set_value(subset_names)

        self._set_btns_enabled(False)
        self._set_btns_visible(invalid_tasks)

        if variant_value is not None:
            self.variant_input.confirm_value()

        if asset_name is not None:
            self.asset_value_widget.confirm_value()

        if task_name is not None:
            self.task_value_widget.confirm_value(asset_names)

        self.instance_context_changed.emit()

    def _on_cancel(self):
        """Cancel changes and set back to their irigin value."""

        self.variant_input.reset_to_origin()
        self.asset_value_widget.reset_to_origin()
        self.task_value_widget.reset_to_origin()
        self._set_btns_enabled(False)

    def _on_value_change(self):
        any_invalid = (
            not self.variant_input.is_valid()
            or not self.asset_value_widget.is_valid()
            or not self.task_value_widget.is_valid()
        )
        any_changed = (
            self.variant_input.has_value_changed()
            or self.asset_value_widget.has_value_changed()
            or self.task_value_widget.has_value_changed()
        )
        self._set_btns_visible(any_changed or any_invalid)
        self.cancel_btn.setEnabled(any_changed)
        self.submit_btn.setEnabled(not any_invalid)

    def _on_variant_change(self):
        self._on_value_change()

    def _on_asset_change(self):
        asset_names = self.asset_value_widget.get_selected_items()
        self.task_value_widget.set_asset_names(asset_names)
        self._on_value_change()

    def _on_task_change(self):
        self._on_value_change()

    def _set_btns_visible(self, visible):
        self.cancel_btn.setVisible(visible)
        self.submit_btn.setVisible(visible)

    def _set_btns_enabled(self, enabled):
        self.cancel_btn.setEnabled(enabled)
        self.submit_btn.setEnabled(enabled)

    def set_current_instances(self, instances):
        """Set currently selected instances.

        Args:
            instances(List[CreatedInstance]): List of selected instances.
                Empty instances tells that nothing or context is selected.
        """
        self._set_btns_visible(False)

        self._current_instances = instances

        asset_names = set()
        variants = set()
        families = set()
        subset_names = set()

        editable = True
        if len(instances) == 0:
            editable = False

        asset_task_combinations = []
        for instance in instances:
            # NOTE I'm not sure how this can even happen?
            if instance.creator_identifier is None:
                editable = False

            variants.add(instance.get("variant") or self.unknown_value)
            families.add(instance.get("family") or self.unknown_value)
            if AYON_SERVER_ENABLED:
                asset_name = instance.get("folderPath") or self.unknown_value
            else:
                asset_name = instance.get("asset") or self.unknown_value
            task_name = instance.get("task") or ""
            asset_names.add(asset_name)
            asset_task_combinations.append((asset_name, task_name))
            subset_names.add(instance.get("subset") or self.unknown_value)

        self.variant_input.set_value(variants)

        # Set context of asset widget
        self.asset_value_widget.set_selected_items(asset_names)
        # Set context of task widget
        self.task_value_widget.set_selected_items(asset_task_combinations)
        self.family_value_widget.set_value(families)
        self.subset_value_widget.set_value(subset_names)

        self.variant_input.setEnabled(editable)
        self.asset_value_widget.setEnabled(editable)
        self.task_value_widget.setEnabled(editable)


class CreatorAttrsWidget(QtWidgets.QWidget):
    """Widget showing creator specific attributes for selected instances.

    Attributes are defined on creator so are dynamic. Their look and type is
    based on attribute definitions that are defined in
    `~/openpype/pipeline/lib/attribute_definitions.py` and their widget
    representation in `~/openpype/tools/attribute_defs/*`.

    Widgets are disabled if context of instance is not valid.

    Definitions are shown for all instance no matter if they are created with
    different creators. If creator have same (similar) definitions their
    widgets are merged into one (different label does not count).
    """

    def __init__(self, controller, parent):
        super(CreatorAttrsWidget, self).__init__(parent)

        scroll_area = QtWidgets.QScrollArea(self)
        scroll_area.setWidgetResizable(True)

        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(scroll_area, 1)

        self._main_layout = main_layout

        self._controller = controller
        self._scroll_area = scroll_area

        self._attr_def_id_to_instances = {}
        self._attr_def_id_to_attr_def = {}

        # To store content of scroll area to prevent garbage collection
        self._content_widget = None

    def set_instances_valid(self, valid):
        """Change valid state of current instances."""

        if (
            self._content_widget is not None
            and self._content_widget.isEnabled() != valid
        ):
            self._content_widget.setEnabled(valid)

    def set_current_instances(self, instances):
        """Set current instances for which are attribute definitions shown."""

        prev_content_widget = self._scroll_area.widget()
        if prev_content_widget:
            self._scroll_area.takeWidget()
            prev_content_widget.hide()
            prev_content_widget.deleteLater()

        self._content_widget = None
        self._attr_def_id_to_instances = {}
        self._attr_def_id_to_attr_def = {}

        result = self._controller.get_creator_attribute_definitions(
            instances
        )

        content_widget = QtWidgets.QWidget(self._scroll_area)
        content_layout = QtWidgets.QGridLayout(content_widget)
        content_layout.setColumnStretch(0, 0)
        content_layout.setColumnStretch(1, 1)
        content_layout.setAlignment(QtCore.Qt.AlignTop)
        content_layout.setHorizontalSpacing(INPUTS_LAYOUT_HSPACING)
        content_layout.setVerticalSpacing(INPUTS_LAYOUT_VSPACING)

        row = 0
        for attr_def, attr_instances, values in result:
            widget = create_widget_for_attr_def(attr_def, content_widget)
            if attr_def.is_value_def:
                if len(values) == 1:
                    value = values[0]
                    if value is not None:
                        widget.set_value(values[0])
                else:
                    widget.set_value(values, True)

            widget.value_changed.connect(self._input_value_changed)
            self._attr_def_id_to_instances[attr_def.id] = attr_instances
            self._attr_def_id_to_attr_def[attr_def.id] = attr_def

            if attr_def.hidden:
                continue

            expand_cols = 2
            if attr_def.is_value_def and attr_def.is_label_horizontal:
                expand_cols = 1

            col_num = 2 - expand_cols

            label = None
            if attr_def.is_value_def:
                label = attr_def.label or attr_def.key
            if label:
                label_widget = QtWidgets.QLabel(label, self)
                tooltip = attr_def.tooltip
                if tooltip:
                    label_widget.setToolTip(tooltip)
                if attr_def.is_label_horizontal:
                    label_widget.setAlignment(
                        QtCore.Qt.AlignRight
                        | QtCore.Qt.AlignVCenter
                    )
                content_layout.addWidget(
                    label_widget, row, 0, 1, expand_cols
                )
                if not attr_def.is_label_horizontal:
                    row += 1

            content_layout.addWidget(
                widget, row, col_num, 1, expand_cols
            )
            row += 1

        self._scroll_area.setWidget(content_widget)
        self._content_widget = content_widget

    def _input_value_changed(self, value, attr_id):
        instances = self._attr_def_id_to_instances.get(attr_id)
        attr_def = self._attr_def_id_to_attr_def.get(attr_id)
        if not instances or not attr_def:
            return

        for instance in instances:
            creator_attributes = instance["creator_attributes"]
            if attr_def.key in creator_attributes:
                creator_attributes[attr_def.key] = value


class PublishPluginAttrsWidget(QtWidgets.QWidget):
    """Widget showing publsish plugin attributes for selected instances.

    Attributes are defined on publish plugins. Publish plugin may define
    attribute definitions but must inherit `OpenPypePyblishPluginMixin`
    (~/openpype/pipeline/publish). At the moment requires to implement
    `get_attribute_defs` and `convert_attribute_values` class methods.

    Look and type of attributes is based on attribute definitions that are
    defined in `~/openpype/pipeline/lib/attribute_definitions.py` and their
    widget representation in `~/openpype/tools/attribute_defs/*`.

    Widgets are disabled if context of instance is not valid.

    Definitions are shown for all instance no matter if they have different
    families. Similar definitions are merged into one (different label
    does not count).
    """

    def __init__(self, controller, parent):
        super(PublishPluginAttrsWidget, self).__init__(parent)

        scroll_area = QtWidgets.QScrollArea(self)
        scroll_area.setWidgetResizable(True)

        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(scroll_area, 1)

        self._main_layout = main_layout

        self._controller = controller
        self._scroll_area = scroll_area

        self._attr_def_id_to_instances = {}
        self._attr_def_id_to_attr_def = {}
        self._attr_def_id_to_plugin_name = {}

        # Store content of scroll area to prevent garbage collection
        self._content_widget = None

    def set_instances_valid(self, valid):
        """Change valid state of current instances."""
        if (
            self._content_widget is not None
            and self._content_widget.isEnabled() != valid
        ):
            self._content_widget.setEnabled(valid)

    def set_current_instances(self, instances, context_selected):
        """Set current instances for which are attribute definitions shown."""

        prev_content_widget = self._scroll_area.widget()
        if prev_content_widget:
            self._scroll_area.takeWidget()
            prev_content_widget.hide()
            prev_content_widget.deleteLater()

        self._content_widget = None

        self._attr_def_id_to_instances = {}
        self._attr_def_id_to_attr_def = {}
        self._attr_def_id_to_plugin_name = {}

        result = self._controller.get_publish_attribute_definitions(
            instances, context_selected
        )

        content_widget = QtWidgets.QWidget(self._scroll_area)
        attr_def_widget = QtWidgets.QWidget(content_widget)
        attr_def_layout = QtWidgets.QGridLayout(attr_def_widget)
        attr_def_layout.setColumnStretch(0, 0)
        attr_def_layout.setColumnStretch(1, 1)
        attr_def_layout.setHorizontalSpacing(INPUTS_LAYOUT_HSPACING)
        attr_def_layout.setVerticalSpacing(INPUTS_LAYOUT_VSPACING)

        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.addWidget(attr_def_widget, 0)
        content_layout.addStretch(1)

        row = 0
        for plugin_name, attr_defs, all_plugin_values in result:
            plugin_values = all_plugin_values[plugin_name]

            for attr_def in attr_defs:
                widget = create_widget_for_attr_def(
                    attr_def, content_widget
                )
                hidden_widget = attr_def.hidden
                # Hide unknown values of publish plugins
                # - The keys in most of cases does not represent what would
                #   label represent
                if isinstance(attr_def, UnknownDef):
                    widget.setVisible(False)
                    hidden_widget = True

                if not hidden_widget:
                    expand_cols = 2
                    if attr_def.is_value_def and attr_def.is_label_horizontal:
                        expand_cols = 1

                    col_num = 2 - expand_cols
                    label = None
                    if attr_def.is_value_def:
                        label = attr_def.label or attr_def.key
                    if label:
                        label_widget = QtWidgets.QLabel(label, content_widget)
                        tooltip = attr_def.tooltip
                        if tooltip:
                            label_widget.setToolTip(tooltip)
                        if attr_def.is_label_horizontal:
                            label_widget.setAlignment(
                                QtCore.Qt.AlignRight
                                | QtCore.Qt.AlignVCenter
                            )
                        attr_def_layout.addWidget(
                            label_widget, row, 0, 1, expand_cols
                        )
                        if not attr_def.is_label_horizontal:
                            row += 1
                    attr_def_layout.addWidget(
                        widget, row, col_num, 1, expand_cols
                    )
                    row += 1

                if not attr_def.is_value_def:
                    continue

                widget.value_changed.connect(self._input_value_changed)

                attr_values = plugin_values[attr_def.key]
                multivalue = len(attr_values) > 1
                values = []
                instances = []
                for instance, value in attr_values:
                    values.append(value)
                    instances.append(instance)

                self._attr_def_id_to_attr_def[attr_def.id] = attr_def
                self._attr_def_id_to_instances[attr_def.id] = instances
                self._attr_def_id_to_plugin_name[attr_def.id] = plugin_name

                if multivalue:
                    widget.set_value(values, multivalue)
                else:
                    widget.set_value(values[0])

        self._scroll_area.setWidget(content_widget)
        self._content_widget = content_widget

    def _input_value_changed(self, value, attr_id):
        instances = self._attr_def_id_to_instances.get(attr_id)
        attr_def = self._attr_def_id_to_attr_def.get(attr_id)
        plugin_name = self._attr_def_id_to_plugin_name.get(attr_id)
        if not instances or not attr_def or not plugin_name:
            return

        for instance in instances:
            plugin_val = instance.publish_attributes[plugin_name]
            plugin_val[attr_def.key] = value


class SubsetAttributesWidget(QtWidgets.QWidget):
    """Wrapper widget where attributes of instance/s are modified.
    ┌─────────────────┬─────────────┐
    │   Global        │             │
    │   attributes    │  Thumbnail  │  TOP
    │                 │             │
    ├─────────────┬───┴─────────────┤
    │  Creator    │   Publish       │
    │  attributes │   plugin        │  BOTTOM
    │             │   attributes    │
    └───────────────────────────────┘
    """
    instance_context_changed = QtCore.Signal()
    convert_requested = QtCore.Signal()

    def __init__(self, controller, parent):
        super(SubsetAttributesWidget, self).__init__(parent)

        # TOP PART
        top_widget = QtWidgets.QWidget(self)

        # Global attributes
        global_attrs_widget = GlobalAttrsWidget(controller, top_widget)
        thumbnail_widget = ThumbnailWidget(controller, top_widget)

        top_layout = QtWidgets.QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(global_attrs_widget, 7)
        top_layout.addWidget(thumbnail_widget, 3)

        # BOTTOM PART
        bottom_widget = QtWidgets.QWidget(self)

        # Wrap Creator attributes to widget to be able add convert button
        creator_widget = QtWidgets.QWidget(bottom_widget)

        # Convert button widget (with layout to handle stretch)
        convert_widget = QtWidgets.QWidget(creator_widget)
        convert_label = QtWidgets.QLabel(creator_widget)
        # Set the label text with 'setText' to apply html
        convert_label.setText(
            (
                "Found old publishable subsets"
                " incompatible with new publisher."
                "<br/><br/>Press the <b>update subsets</b> button"
                " to automatically update them"
                " to be able to publish again."
            )
        )
        convert_label.setWordWrap(True)
        convert_label.setAlignment(QtCore.Qt.AlignCenter)

        convert_btn = QtWidgets.QPushButton(
            "Update subsets", convert_widget
        )
        convert_separator = QtWidgets.QFrame(convert_widget)
        convert_separator.setObjectName("Separator")
        convert_separator.setMinimumHeight(1)
        convert_separator.setMaximumHeight(1)

        convert_layout = QtWidgets.QGridLayout(convert_widget)
        convert_layout.setContentsMargins(5, 0, 5, 0)
        convert_layout.setVerticalSpacing(10)
        convert_layout.addWidget(convert_label, 0, 0, 1, 3)
        convert_layout.addWidget(convert_btn, 1, 1)
        convert_layout.addWidget(convert_separator, 2, 0, 1, 3)
        convert_layout.setColumnStretch(0, 1)
        convert_layout.setColumnStretch(1, 0)
        convert_layout.setColumnStretch(2, 1)

        # Creator attributes widget
        creator_attrs_widget = CreatorAttrsWidget(
            controller, creator_widget
        )
        creator_layout = QtWidgets.QVBoxLayout(creator_widget)
        creator_layout.setContentsMargins(0, 0, 0, 0)
        creator_layout.addWidget(convert_widget, 0)
        creator_layout.addWidget(creator_attrs_widget, 1)

        publish_attrs_widget = PublishPluginAttrsWidget(
            controller, bottom_widget
        )

        bottom_separator = QtWidgets.QWidget(bottom_widget)
        bottom_separator.setObjectName("Separator")
        bottom_separator.setMinimumWidth(1)

        bottom_layout = QtWidgets.QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(creator_widget, 1)
        bottom_layout.addWidget(bottom_separator, 0)
        bottom_layout.addWidget(publish_attrs_widget, 1)

        top_bottom = QtWidgets.QWidget(self)
        top_bottom.setObjectName("Separator")
        top_bottom.setMinimumHeight(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(top_widget, 0)
        layout.addWidget(top_bottom, 0)
        layout.addWidget(bottom_widget, 1)

        self._convertor_identifiers = None
        self._current_instances = None
        self._context_selected = False
        self._all_instances_valid = True

        global_attrs_widget.instance_context_changed.connect(
            self._on_instance_context_changed
        )
        convert_btn.clicked.connect(self._on_convert_click)
        thumbnail_widget.thumbnail_created.connect(self._on_thumbnail_create)
        thumbnail_widget.thumbnail_cleared.connect(self._on_thumbnail_clear)

        controller.event_system.add_callback(
            "instance.thumbnail.changed", self._on_thumbnail_changed
        )

        self._controller = controller

        self._convert_widget = convert_widget

        self.global_attrs_widget = global_attrs_widget

        self.creator_attrs_widget = creator_attrs_widget
        self.publish_attrs_widget = publish_attrs_widget
        self._thumbnail_widget = thumbnail_widget

        self.top_bottom = top_bottom
        self.bottom_separator = bottom_separator

    def _on_instance_context_changed(self):
        all_valid = True
        for instance in self._current_instances:
            if not instance.has_valid_context:
                all_valid = False
                break

        self._all_instances_valid = all_valid
        self.creator_attrs_widget.set_instances_valid(all_valid)
        self.publish_attrs_widget.set_instances_valid(all_valid)

        self.instance_context_changed.emit()

    def _on_convert_click(self):
        self.convert_requested.emit()

    def set_current_instances(
        self, instances, context_selected, convertor_identifiers
    ):
        """Change currently selected items.

        Args:
            instances(List[CreatedInstance]): List of currently selected
                instances.
            context_selected(bool): Is context selected.
            convertor_identifiers(List[str]): Identifiers of convert items.
        """

        all_valid = True
        for instance in instances:
            if not instance.has_valid_context:
                all_valid = False
                break

        s_convertor_identifiers = set(convertor_identifiers)
        self._convertor_identifiers = s_convertor_identifiers
        self._current_instances = instances
        self._context_selected = context_selected
        self._all_instances_valid = all_valid

        self._convert_widget.setVisible(len(s_convertor_identifiers) > 0)
        self.global_attrs_widget.set_current_instances(instances)
        self.creator_attrs_widget.set_current_instances(instances)
        self.publish_attrs_widget.set_current_instances(
            instances, context_selected
        )
        self.creator_attrs_widget.set_instances_valid(all_valid)
        self.publish_attrs_widget.set_instances_valid(all_valid)

        self._update_thumbnails()

    def _on_thumbnail_create(self, path):
        instance_ids = [
            instance.id
            for instance in self._current_instances
        ]
        if self._context_selected:
            instance_ids.append(None)

        if not instance_ids:
            return

        mapping = {}
        if len(instance_ids) == 1:
            mapping[instance_ids[0]] = path

        else:
            for instance_id in instance_ids:
                root = os.path.dirname(path)
                ext = os.path.splitext(path)[-1]
                dst_path = os.path.join(root, str(uuid.uuid4()) + ext)
                shutil.copy(path, dst_path)
                mapping[instance_id] = dst_path

        self._controller.set_thumbnail_paths_for_instances(mapping)

    def _on_thumbnail_clear(self):
        instance_ids = [
            instance.id
            for instance in self._current_instances
        ]
        if self._context_selected:
            instance_ids.append(None)

        if not instance_ids:
            return

        mapping = {
            instance_id: None
            for instance_id in instance_ids
        }
        self._controller.set_thumbnail_paths_for_instances(mapping)

    def _on_thumbnail_changed(self, event):
        self._update_thumbnails()

    def _update_thumbnails(self):
        instance_ids = [
            instance.id
            for instance in self._current_instances
        ]
        if self._context_selected:
            instance_ids.append(None)

        if not instance_ids:
            self._thumbnail_widget.setVisible(False)
            self._thumbnail_widget.set_current_thumbnails(None)
            return

        mapping = self._controller.get_thumbnail_paths_for_instances(
            instance_ids
        )
        thumbnail_paths = []
        for instance_id in instance_ids:
            path = mapping[instance_id]
            if path:
                thumbnail_paths.append(path)

        self._thumbnail_widget.setVisible(True)
        self._thumbnail_widget.set_current_thumbnails(thumbnail_paths)


class CreateNextPageOverlay(QtWidgets.QWidget):
    clicked = QtCore.Signal()

    def __init__(self, parent):
        super(CreateNextPageOverlay, self).__init__(parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._arrow_color = (
            get_objected_colors("font").get_qcolor()
        )
        self._bg_color = (
            get_objected_colors("bg-buttons").get_qcolor()
        )

        change_anim = QtCore.QVariantAnimation()
        change_anim.setStartValue(0.0)
        change_anim.setEndValue(1.0)
        change_anim.setDuration(200)
        change_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        change_anim.valueChanged.connect(self._on_anim)

        self._change_anim = change_anim
        self._is_visible = None
        self._anim_value = 0.0
        self._increasing = False
        self._under_mouse = None
        self._handle_show_on_own = True
        self._mouse_pressed = False
        self.set_visible(True)

    def set_increasing(self, increasing):
        if self._increasing is increasing:
            return
        self._increasing = increasing
        if increasing:
            self._change_anim.setDirection(QtCore.QAbstractAnimation.Forward)
        else:
            self._change_anim.setDirection(QtCore.QAbstractAnimation.Backward)

        if self._change_anim.state() != QtCore.QAbstractAnimation.Running:
            self._change_anim.start()

    def set_visible(self, visible):
        if self._is_visible is visible:
            return

        self._is_visible = visible
        if not visible:
            self.set_increasing(False)
            if not self._is_anim_finished():
                return

        self.setVisible(visible)
        self._check_anim_timer()

    def _is_anim_finished(self):
        if self._increasing:
            return self._anim_value == 1.0
        return self._anim_value == 0.0

    def _on_anim(self, value):
        self._check_anim_timer()

        self._anim_value = value

        self.update()

        if not self._is_anim_finished():
            return

        if not self._is_visible:
            self.setVisible(False)

    def set_under_mouse(self, under_mouse):
        if self._under_mouse is under_mouse:
            return

        self._under_mouse = under_mouse
        self.set_increasing(under_mouse)

    def _is_under_mouse(self):
        mouse_pos = self.mapFromGlobal(QtGui.QCursor.pos())
        under_mouse = self.rect().contains(mouse_pos)
        return under_mouse

    def _check_anim_timer(self):
        if not self.isVisible():
            return

        self.set_increasing(self._under_mouse)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._mouse_pressed = True
        super(CreateNextPageOverlay, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._mouse_pressed:
            self._mouse_pressed = False
            if self.rect().contains(event.pos()):
                self.clicked.emit()

        super(CreateNextPageOverlay, self).mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)
        if self._anim_value == 0.0:
            painter.end()
            return

        painter.setClipRect(event.rect())
        painter.setRenderHints(
            QtGui.QPainter.Antialiasing
            | QtGui.QPainter.SmoothPixmapTransform
        )

        painter.setPen(QtCore.Qt.NoPen)

        rect = QtCore.QRect(self.rect())
        rect_width = rect.width()
        rect_height = rect.height()
        radius = rect_width * 0.2

        x_offset = 0
        y_offset = 0
        if self._anim_value != 1.0:
            x_offset += rect_width - (rect_width * self._anim_value)

        arrow_height = rect_height * 0.4
        arrow_half_height = arrow_height * 0.5
        arrow_x_start = x_offset + ((rect_width - arrow_half_height) * 0.5)
        arrow_x_end = arrow_x_start + arrow_half_height
        center_y = rect.center().y()

        painter.setBrush(self._bg_color)
        painter.drawRoundedRect(
            x_offset, y_offset,
            rect_width + radius, rect_height,
            radius, radius
        )

        src_arrow_path = QtGui.QPainterPath()
        src_arrow_path.moveTo(arrow_x_start, center_y - arrow_half_height)
        src_arrow_path.lineTo(arrow_x_end, center_y)
        src_arrow_path.lineTo(arrow_x_start, center_y + arrow_half_height)

        arrow_stroker = QtGui.QPainterPathStroker()
        arrow_stroker.setWidth(min(4, arrow_half_height * 0.2))
        arrow_path = arrow_stroker.createStroke(src_arrow_path)

        painter.fillPath(arrow_path, self._arrow_color)

        painter.end()
