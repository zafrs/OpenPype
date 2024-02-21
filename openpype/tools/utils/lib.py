import os
import sys
import contextlib
import collections
import traceback

from qtpy import QtWidgets, QtCore, QtGui
import qtawesome

from openpype.client import (
    get_project,
    get_asset_by_name,
)
from openpype.style import (
    get_default_entity_icon_color,
    get_objected_colors,
    get_app_icon_path,
)
from openpype.resources import get_image_path
from openpype.lib import filter_profiles, Logger
from openpype.settings import get_project_settings
from openpype.pipeline import (
    registered_host,
    get_current_context,
    get_current_host_name,
)

from .constants import CHECKED_INT, UNCHECKED_INT

log = Logger.get_logger(__name__)


def checkstate_int_to_enum(state):
    if not isinstance(state, int):
        return state
    if state == CHECKED_INT:
        return QtCore.Qt.Checked

    if state == UNCHECKED_INT:
        return QtCore.Qt.Unchecked
    return QtCore.Qt.PartiallyChecked


def checkstate_enum_to_int(state):
    if isinstance(state, int):
        return state
    if state == QtCore.Qt.Checked:
        return 0
    if state == QtCore.Qt.PartiallyChecked:
        return 1
    return 2


def center_window(window):
    """Move window to center of it's screen."""

    if hasattr(QtWidgets.QApplication, "desktop"):
        desktop = QtWidgets.QApplication.desktop()
        screen_idx = desktop.screenNumber(window)
        screen_geo = desktop.screenGeometry(screen_idx)
    else:
        screen = window.screen()
        screen_geo = screen.geometry()

    geo = window.frameGeometry()
    geo.moveCenter(screen_geo.center())
    if geo.y() < screen_geo.y():
        geo.setY(screen_geo.y())
    window.move(geo.topLeft())


def html_escape(text):
    """Basic escape of html syntax symbols in text."""

    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def set_style_property(widget, property_name, property_value):
    """Set widget's property that may affect style.

    If current property value is different then style of widget is polished.
    """
    cur_value = widget.property(property_name)
    if cur_value == property_value:
        return
    widget.setProperty(property_name, property_value)
    style = widget.style()
    style.polish(widget)


def paint_image_with_color(image, color):
    """Redraw image with single color using it's alpha.

    It is expected that input image is singlecolor image with alpha.

    Args:
        image (QImage): Loaded image with alpha.
        color (QColor): Color that will be used to paint image.
    """
    width = image.width()
    height = image.height()

    alpha_mask = image.createAlphaMask()
    alpha_region = QtGui.QRegion(QtGui.QBitmap.fromImage(alpha_mask))

    pixmap = QtGui.QPixmap(width, height)
    pixmap.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(pixmap)
    render_hints = (
        QtGui.QPainter.Antialiasing
        | QtGui.QPainter.SmoothPixmapTransform
    )
    # Deprecated since 5.14
    if hasattr(QtGui.QPainter, "HighQualityAntialiasing"):
        render_hints |= QtGui.QPainter.HighQualityAntialiasing
    painter.setRenderHints(render_hints)

    painter.setClipRegion(alpha_region)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(color)
    painter.drawRect(QtCore.QRect(0, 0, width, height))
    painter.end()

    return pixmap


def format_version(value, hero_version=False):
    """Formats integer to displayable version name"""
    label = "v{0:03d}".format(value)
    if not hero_version:
        return label
    return "[{}]".format(label)


@contextlib.contextmanager
def qt_app_context():
    app = QtWidgets.QApplication.instance()

    if not app:
        print("Starting new QApplication..")
        app = QtWidgets.QApplication(sys.argv)
        yield app
        app.exec_()
    else:
        print("Using existing QApplication..")
        yield app


def get_qt_app():
    """Get Qt application.

    The function initializes new Qt application if it is not already
    initialized. It also sets some attributes to the application to
    ensure that it will work properly on high DPI displays.

    Returns:
        QtWidgets.QApplication: Current Qt application.
    """

    app = QtWidgets.QApplication.instance()
    if app is None:
        for attr_name in (
            "AA_EnableHighDpiScaling",
            "AA_UseHighDpiPixmaps",
        ):
            attr = getattr(QtCore.Qt, attr_name, None)
            if attr is not None:
                QtWidgets.QApplication.setAttribute(attr)

        policy = os.getenv("QT_SCALE_FACTOR_ROUNDING_POLICY")
        if (
            hasattr(
                QtWidgets.QApplication, "setHighDpiScaleFactorRoundingPolicy"
            )
            and not policy
        ):
            QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
                QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )

        app = QtWidgets.QApplication(sys.argv)

    return app


def get_openpype_qt_app():
    """Main Qt application initialized for OpenPype processed.

    This function should be used only inside OpenPype process and never inside
        other processes.
    """

    app = get_qt_app()
    app.setWindowIcon(QtGui.QIcon(get_app_icon_path()))
    return app


class SharedObjects:
    jobs = {}
    icons = {}


def get_qta_icon_by_name_and_color(icon_name, icon_color):
    if not icon_name or not icon_color:
        return None

    full_icon_name = "{0}-{1}".format(icon_name, icon_color)
    if full_icon_name in SharedObjects.icons:
        return SharedObjects.icons[full_icon_name]

    variants = [icon_name]
    qta_instance = qtawesome._instance()
    for key in qta_instance.charmap.keys():
        variants.append("{0}.{1}".format(key, icon_name))

    icon = None
    used_variant = None
    for variant in variants:
        try:
            icon = qtawesome.icon(variant, color=icon_color)
            used_variant = variant
            break
        except Exception:
            pass

    if used_variant is None:
        log.info("Didn't find icon \"{}\"".format(icon_name))

    elif used_variant != icon_name:
        log.debug("Icon \"{}\" was not found \"{}\" is used instead".format(
            icon_name, used_variant
        ))

    SharedObjects.icons[full_icon_name] = icon
    return icon


def get_project_icon(project_doc):
    if project_doc:
        icon_name = project_doc.get("data", {}).get("icon")
        icon = get_qta_icon_by_name_and_color(icon_name, "white")
        if icon:
            return icon

    return get_qta_icon_by_name_and_color(
        "fa.map", get_default_entity_icon_color()
    )


def get_asset_icon_name(asset_doc, has_children=True):
    icon_name = get_asset_icon_name_from_doc(asset_doc)
    if icon_name:
        return icon_name
    return get_default_asset_icon_name(has_children)


def get_asset_icon_color(asset_doc):
    icon_color = get_asset_icon_color_from_doc(asset_doc)
    if icon_color:
        return icon_color
    return get_default_entity_icon_color()


def get_default_asset_icon_name(has_children):
    if has_children:
        return "fa.folder"
    return "fa.folder-o"


def get_asset_icon_name_from_doc(asset_doc):
    if asset_doc:
        return asset_doc["data"].get("icon")
    return None


def get_asset_icon_color_from_doc(asset_doc):
    if asset_doc:
        return asset_doc["data"].get("color")
    return None


def get_asset_icon_by_name(icon_name, icon_color, has_children=False):
    if not icon_name:
        icon_name = get_default_asset_icon_name(has_children)

    if icon_color:
        icon_color = QtGui.QColor(icon_color)
    else:
        icon_color = get_default_entity_icon_color()
    icon = get_qta_icon_by_name_and_color(icon_name, icon_color)
    if icon is not None:
        return icon
    return get_qta_icon_by_name_and_color(
        get_default_asset_icon_name(has_children),
        icon_color
    )


def get_asset_icon(asset_doc, has_children=False):
    icon_name = get_asset_icon_name(asset_doc, has_children)
    icon_color = get_asset_icon_color(asset_doc)

    return get_qta_icon_by_name_and_color(icon_name, icon_color)


def get_default_task_icon(color=None):
    if color is None:
        color = get_default_entity_icon_color()
    return get_qta_icon_by_name_and_color("fa.male", color)


def get_task_icon(project_doc, asset_doc, task_name):
    """Get icon for a task.

    Icon should be defined by task type which is stored on project.
    """

    color = get_default_entity_icon_color()

    tasks_info = asset_doc.get("data", {}).get("tasks") or {}
    task_info = tasks_info.get(task_name) or {}
    task_icon = task_info.get("icon")
    if task_icon:
        icon = get_qta_icon_by_name_and_color(task_icon, color)
        if icon is not None:
            return icon

    task_type = task_info.get("type")
    task_types = project_doc["config"]["tasks"]

    task_type_info = task_types.get(task_type) or {}
    task_type_icon = task_type_info.get("icon")
    if task_type_icon:
        icon = get_qta_icon_by_name_and_color(task_icon, color)
        if icon is not None:
            return icon
    return get_default_task_icon(color)


def schedule(func, time, channel="default"):
    """Run `func` at a later `time` in a dedicated `channel`

    Given an arbitrary function, call this function after a given
    timeout. It will ensure that only one "job" is running within
    the given channel at any one time and cancel any currently
    running job if a new job is submitted before the timeout.

    """

    try:
        SharedObjects.jobs[channel].stop()
    except (AttributeError, KeyError, RuntimeError):
        pass

    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(func)
    timer.start(time)

    SharedObjects.jobs[channel] = timer


def iter_model_rows(model, column, include_root=False):
    """Iterate over all row indices in a model"""
    indices = [QtCore.QModelIndex()]  # start iteration at root

    for index in indices:
        # Add children to the iterations
        child_rows = model.rowCount(index)
        for child_row in range(child_rows):
            child_index = model.index(child_row, column, index)
            indices.append(child_index)

        if not include_root and not index.isValid():
            continue

        yield index


@contextlib.contextmanager
def preserve_expanded_rows(tree_view, column=0, role=None):
    """Preserves expanded row in QTreeView by column's data role.

    This function is created to maintain the expand vs collapse status of
    the model items. When refresh is triggered the items which are expanded
    will stay expanded and vice versa.

    Arguments:
        tree_view (QWidgets.QTreeView): the tree view which is
            nested in the application
        column (int): the column to retrieve the data from
        role (int): the role which dictates what will be returned

    Returns:
        None

    """
    if role is None:
        role = QtCore.Qt.DisplayRole
    model = tree_view.model()

    expanded = set()

    for index in iter_model_rows(model, column=column, include_root=False):
        if tree_view.isExpanded(index):
            value = index.data(role)
            expanded.add(value)

    try:
        yield
    finally:
        if not expanded:
            return

        for index in iter_model_rows(model, column=column, include_root=False):
            value = index.data(role)
            state = value in expanded
            if state:
                tree_view.expand(index)
            else:
                tree_view.collapse(index)


@contextlib.contextmanager
def preserve_selection(tree_view, column=0, role=None, current_index=True):
    """Preserves row selection in QTreeView by column's data role.

    This function is created to maintain the selection status of
    the model items. When refresh is triggered the items which are expanded
    will stay expanded and vice versa.

        tree_view (QWidgets.QTreeView): the tree view nested in the application
        column (int): the column to retrieve the data from
        role (int): the role which dictates what will be returned

    Returns:
        None

    """
    if role is None:
        role = QtCore.Qt.DisplayRole
    model = tree_view.model()
    selection_model = tree_view.selectionModel()
    flags = (
        QtCore.QItemSelectionModel.Select
        | QtCore.QItemSelectionModel.Rows
    )

    if current_index:
        current_index_value = tree_view.currentIndex().data(role)
    else:
        current_index_value = None

    selected_rows = selection_model.selectedRows()
    if not selected_rows:
        yield
        return

    selected = set(row.data(role) for row in selected_rows)
    try:
        yield
    finally:
        if not selected:
            return

        # Go through all indices, select the ones with similar data
        for index in iter_model_rows(model, column=column, include_root=False):
            value = index.data(role)
            state = value in selected
            if state:
                tree_view.scrollTo(index)  # Ensure item is visible
                selection_model.select(index, flags)

            if current_index_value and value == current_index_value:
                selection_model.setCurrentIndex(
                    index, selection_model.NoUpdate
                )


class FamilyConfigCache:
    default_color = "#0091B2"
    _default_icon = None

    def __init__(self, dbcon):
        self.dbcon = dbcon
        self.family_configs = {}
        self._family_filters_set = False
        self._family_filters_is_include = True
        self._require_refresh = True

    @classmethod
    def default_icon(cls):
        if cls._default_icon is None:
            cls._default_icon = qtawesome.icon(
                "fa.folder", color=cls.default_color
            )
        return cls._default_icon

    def family_config(self, family_name):
        """Get value from config with fallback to default"""
        if self._require_refresh:
            self._refresh()

        item = self.family_configs.get(family_name)
        if not item:
            item = {
                "icon": self.default_icon()
            }
            if self._family_filters_set:
                item["state"] = not self._family_filters_is_include
        return item

    def refresh(self, force=False):
        self._require_refresh = True

        if force:
            self._refresh()

    def _refresh(self):
        """Get the family configurations from the database

        The configuration must be stored on the project under `config`.
        For example:

        {"config": {
            "families": [
                {"name": "avalon.camera", label: "Camera", "icon": "photo"},
                {"name": "avalon.anim", label: "Animation", "icon": "male"},
            ]
        }}

        It is possible to override the default behavior and set specific
        families checked. For example we only want the families imagesequence
        and camera to be visible in the Loader.
        """
        self._require_refresh = False
        self._family_filters_set = False

        self.family_configs.clear()
        # Skip if we're not in host context
        if not registered_host():
            return

        # Update the icons from the project configuration
        context = get_current_context()
        project_name = context["project_name"]
        asset_name = context["asset_name"]
        task_name = context["task_name"]
        host_name = get_current_host_name()
        if not all((project_name, asset_name, task_name)):
            return

        matching_item = None
        project_settings = get_project_settings(project_name)
        profiles = (
            project_settings
            ["global"]
            ["tools"]
            ["loader"]
            ["family_filter_profiles"]
        )
        if profiles:
            # Make sure connection is installed
            # - accessing attribute which does not have auto-install
            asset_doc = get_asset_by_name(
                project_name, asset_name, fields=["data.tasks"]
            ) or {}
            tasks_info = asset_doc.get("data", {}).get("tasks") or {}
            task_type = tasks_info.get(task_name, {}).get("type")
            profiles_filter = {
                "task_types": task_type,
                "hosts": host_name
            }
            matching_item = filter_profiles(profiles, profiles_filter)

        families = []
        is_include = True
        if matching_item:
            families = matching_item["filter_families"]
            is_include = matching_item["is_include"]

        if not families:
            return

        self._family_filters_set = True
        self._family_filters_is_include = is_include

        # Replace icons with a Qt icon we can use in the user interfaces
        for family in families:
            family_info = {
                "name": family,
                "icon": self.default_icon(),
                "state": is_include
            }

            self.family_configs[family] = family_info


class GroupsConfig:
    # Subset group item's default icon and order
    _default_group_config = None

    def __init__(self, dbcon):
        self.dbcon = dbcon
        self.groups = {}
        self._default_group_color = get_default_entity_icon_color()

    @classmethod
    def default_group_config(cls):
        if cls._default_group_config is None:
            cls._default_group_config = {
                "icon": qtawesome.icon(
                    "fa.object-group",
                    color=get_default_entity_icon_color()
                ),
                "order": 0
            }
        return cls._default_group_config

    def refresh(self):
        """Get subset group configurations from the database

        The 'group' configuration must be stored in the project `config` field.
        See schema `config-1.0.json`

        """
        # Clear cached groups
        self.groups.clear()

        group_configs = []
        project_name = self.dbcon.Session.get("AVALON_PROJECT")
        if project_name:
            # Get pre-defined group name and appearance from project config
            project_doc = get_project(project_name, fields=["config.groups"])

            if project_doc:
                group_configs = project_doc["config"].get("groups") or []
            else:
                print("Project not found! \"{}\"".format(project_name))

        # Build pre-defined group configs
        for config in group_configs:
            name = config["name"]
            icon = "fa." + config.get("icon", "object-group")
            color = config.get("color", self._default_group_color)
            order = float(config.get("order", 0))

            self.groups[name] = {
                "icon": qtawesome.icon(icon, color=color),
                "order": order
            }

        return self.groups

    def ordered_groups(self, group_names):
        # default order zero included
        _orders = set([0])
        for config in self.groups.values():
            _orders.add(config["order"])

        # Remap order to list index
        orders = sorted(_orders)

        _groups = list()
        for name in group_names:
            # Get group config
            config = self.groups.get(name) or self.default_group_config()
            # Base order
            remapped_order = orders.index(config["order"])

            data = {
                "name": name,
                "icon": config["icon"],
                "_order": remapped_order,
            }

            _groups.append(data)

        # Sort by tuple (base_order, name)
        # If there are multiple groups in same order, will sorted by name.
        ordered_groups = sorted(
            _groups, key=lambda _group: (_group.pop("_order"), _group["name"])
        )

        total = len(ordered_groups)
        order_temp = "%0{}d".format(len(str(total)))

        # Update sorted order to config
        for index, group_data in enumerate(ordered_groups):
            order = index
            inverse_order = total - index

            # Format orders into fixed length string for groups sorting
            group_data["order"] = order_temp % order
            group_data["inverseOrder"] = order_temp % inverse_order

        return ordered_groups

    def active_groups(self, asset_ids, include_predefined=True):
        """Collect all active groups from each subset"""
        # Collect groups from subsets
        group_names = set(
            self.dbcon.distinct(
                "data.subsetGroup",
                {"type": "subset", "parent": {"$in": asset_ids}}
            )
        )
        if include_predefined:
            # Ensure all predefined group configs will be included
            group_names.update(self.groups.keys())

        return self.ordered_groups(group_names)

    def split_subsets_for_groups(self, subset_docs, grouping):
        """Collect all active groups from each subset"""
        subset_docs_without_group = collections.defaultdict(list)
        subset_docs_by_group = collections.defaultdict(dict)
        for subset_doc in subset_docs:
            subset_name = subset_doc["name"]
            if grouping:
                group_name = subset_doc["data"].get("subsetGroup")
                if group_name:
                    if subset_name not in subset_docs_by_group[group_name]:
                        subset_docs_by_group[group_name][subset_name] = []

                    subset_docs_by_group[group_name][subset_name].append(
                        subset_doc
                    )
                    continue

            subset_docs_without_group[subset_name].append(subset_doc)

        ordered_groups = self.ordered_groups(subset_docs_by_group.keys())

        return ordered_groups, subset_docs_without_group, subset_docs_by_group


class DynamicQThread(QtCore.QThread):
    """QThread which can run any function with argument and kwargs.

    Args:
        func (function): Function which will be called.
        args (tuple): Arguments which will be passed to function.
        kwargs (tuple): Keyword arguments which will be passed to function.
        parent (QObject): Parent of thread.
    """
    def __init__(self, func, args=None, kwargs=None, parent=None):
        super(DynamicQThread, self).__init__(parent)
        if args is None:
            args = tuple()
        if kwargs is None:
            kwargs = {}
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        """Execute the function with arguments."""
        self._func(*self._args, **self._kwargs)


def create_qthread(func, *args, **kwargs):
    class Thread(QtCore.QThread):
        def run(self):
            try:
                func(*args, **kwargs)
            except BaseException:
                traceback.print_exception(*sys.exc_info())
                raise
    return Thread()


def get_repre_icons():
    """Returns a dict {'provider_name': QIcon}"""
    icons = {}
    try:
        from openpype_modules import sync_server
    except Exception:
        # Backwards compatibility
        try:
            from openpype.modules import sync_server
        except Exception:
            return icons

    resource_path = os.path.join(
        os.path.dirname(sync_server.sync_server_module.__file__),
        "providers", "resources"
    )
    if not os.path.exists(resource_path):
        print("No icons for Site Sync found")
        return icons

    for file_name in os.listdir(resource_path):
        if file_name and not file_name.endswith("png"):
            continue

        provider, _ = os.path.splitext(file_name)

        pix_url = os.path.join(resource_path, file_name)
        icons[provider] = QtGui.QIcon(pix_url)

    return icons


def is_sync_loader(loader):
    return is_remove_site_loader(loader) or is_add_site_loader(loader)


def is_remove_site_loader(loader):
    return hasattr(loader, "is_remove_site_loader")


def is_add_site_loader(loader):
    return hasattr(loader, "is_add_site_loader")


class WrappedCallbackItem:
    """Structure to store information about callback and args/kwargs for it.

    Item can be used to execute callback in main thread which may be needed
    for execution of Qt objects.

    Item store callback (callable variable), arguments and keyword arguments
    for the callback. Item hold information about it's process.
    """
    not_set = object()
    _log = None

    def __init__(self, callback, *args, **kwargs):
        self._done = False
        self._exception = self.not_set
        self._result = self.not_set
        self._callback = callback
        self._args = args
        self._kwargs = kwargs

    def __call__(self):
        self.execute()

    @property
    def log(self):
        cls = self.__class__
        if cls._log is None:
            cls._log = Logger.get_logger(cls.__name__)
        return cls._log

    @property
    def done(self):
        return self._done

    @property
    def exception(self):
        return self._exception

    @property
    def result(self):
        return self._result

    def execute(self):
        """Execute callback and store its result.

        Method must be called from main thread. Item is marked as `done`
        when callback execution finished. Store output of callback of exception
        information when callback raises one.
        """
        if self.done:
            self.log.warning("- item is already processed")
            return

        try:
            result = self._callback(*self._args, **self._kwargs)
            self._result = result

        except Exception as exc:
            self._exception = exc

        finally:
            self._done = True


def get_warning_pixmap(color=None):
    """Warning icon as QPixmap.

    Args:
        color(QtGui.QColor): Color that will be used to paint warning icon.
    """
    src_image_path = get_image_path("warning.png")
    src_image = QtGui.QImage(src_image_path)
    if color is None:
        color = get_objected_colors("delete-btn-bg").get_qcolor()

    return paint_image_with_color(src_image, color)
