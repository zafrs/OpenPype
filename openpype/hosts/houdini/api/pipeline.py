import os
import sys
import logging
import contextlib

import hou

import pyblish.api

from openpype.pipeline import (
    register_creator_plugin_path,
    register_loader_plugin_path,
    AVALON_CONTAINER_ID,
)
from openpype.pipeline.load import any_outdated_containers
from openpype.hosts.houdini import HOUDINI_HOST_DIR
from openpype.hosts.houdini.api import lib, shelves

from openpype.lib import (
    register_event_callback,
    emit_event,
)

from .lib import get_asset_fps

log = logging.getLogger("openpype.hosts.houdini")

AVALON_CONTAINERS = "/obj/AVALON_CONTAINERS"
IS_HEADLESS = not hasattr(hou, "ui")

PLUGINS_DIR = os.path.join(HOUDINI_HOST_DIR, "plugins")
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")
INVENTORY_PATH = os.path.join(PLUGINS_DIR, "inventory")


self = sys.modules[__name__]
self._has_been_setup = False
self._parent = None
self._events = dict()


def install():
    _register_callbacks()

    pyblish.api.register_host("houdini")
    pyblish.api.register_host("hython")
    pyblish.api.register_host("hpython")

    pyblish.api.register_plugin_path(PUBLISH_PATH)
    register_loader_plugin_path(LOAD_PATH)
    register_creator_plugin_path(CREATE_PATH)

    log.info("Installing callbacks ... ")
    # register_event_callback("init", on_init)
    register_event_callback("before.save", before_save)
    register_event_callback("save", on_save)
    register_event_callback("open", on_open)
    register_event_callback("new", on_new)

    pyblish.api.register_callback(
        "instanceToggled", on_pyblish_instance_toggled
    )

    self._has_been_setup = True
    # add houdini vendor packages
    hou_pythonpath = os.path.join(HOUDINI_HOST_DIR, "vendor")

    sys.path.append(hou_pythonpath)

    # Set asset settings for the empty scene directly after launch of Houdini
    # so it initializes into the correct scene FPS, Frame Range, etc.
    # todo: make sure this doesn't trigger when opening with last workfile
    _set_context_settings()
    shelves.generate_shelves()


def uninstall():
    """Uninstall Houdini-specific functionality of avalon-core.

    This function is called automatically on calling `api.uninstall()`.
    """

    pyblish.api.deregister_host("hython")
    pyblish.api.deregister_host("hpython")
    pyblish.api.deregister_host("houdini")


def _register_callbacks():
    for event in self._events.copy().values():
        if event is None:
            continue

        try:
            hou.hipFile.removeEventCallback(event)
        except RuntimeError as e:
            log.info(e)

    self._events[on_file_event_callback] = hou.hipFile.addEventCallback(
        on_file_event_callback
    )


def on_file_event_callback(event):
    if event == hou.hipFileEventType.AfterLoad:
        emit_event("open")
    elif event == hou.hipFileEventType.AfterSave:
        emit_event("save")
    elif event == hou.hipFileEventType.BeforeSave:
        emit_event("before.save")
    elif event == hou.hipFileEventType.AfterClear:
        emit_event("new")


def get_main_window():
    """Acquire Houdini's main window"""
    if self._parent is None:
        self._parent = hou.ui.mainQtWindow()
    return self._parent


def teardown():
    """Remove integration"""
    if not self._has_been_setup:
        return

    self._has_been_setup = False
    print("pyblish: Integration torn down successfully")


def containerise(name,
                 namespace,
                 nodes,
                 context,
                 loader=None,
                 suffix=""):
    """Bundle `nodes` into a subnet and imprint it with metadata

    Containerisation enables a tracking of version, author and origin
    for loaded assets.

    Arguments:
        name (str): Name of resulting assembly
        namespace (str): Namespace under which to host container
        nodes (list): Long names of nodes to containerise
        context (dict): Asset information
        loader (str, optional): Name of loader used to produce this container.
        suffix (str, optional): Suffix of container, defaults to `_CON`.

    Returns:
        container (str): Name of container assembly

    """

    # Ensure AVALON_CONTAINERS subnet exists
    subnet = hou.node(AVALON_CONTAINERS)
    if subnet is None:
        obj_network = hou.node("/obj")
        subnet = obj_network.createNode("subnet",
                                        node_name="AVALON_CONTAINERS")

    # Create proper container name
    container_name = "{}_{}".format(name, suffix or "CON")
    container = hou.node("/obj/{}".format(name))
    container.setName(container_name, unique_name=True)

    data = {
        "schema": "openpype:container-2.0",
        "id": AVALON_CONTAINER_ID,
        "name": name,
        "namespace": namespace,
        "loader": str(loader),
        "representation": str(context["representation"]["_id"]),
    }

    lib.imprint(container, data)

    # "Parent" the container under the container network
    hou.moveNodesTo([container], subnet)

    subnet.node(container_name).moveToGoodPosition()

    return container


def parse_container(container):
    """Return the container node's full container data.

    Args:
        container (hou.Node): A container node name.

    Returns:
        dict: The container schema data for this container node.

    """
    data = lib.read(container)

    # Backwards compatibility pre-schemas for containers
    data["schema"] = data.get("schema", "openpype:container-1.0")

    # Append transient data
    data["objectName"] = container.path()
    data["node"] = container

    return data


def ls():
    containers = []
    for identifier in (AVALON_CONTAINER_ID,
                       "pyblish.mindbender.container"):
        containers += lib.lsattr("id", identifier)

    for container in sorted(containers,
                            # Hou 19+ Python 3 hou.ObjNode are not
                            # sortable due to not supporting greater
                            # than comparisons
                            key=lambda node: node.path()):
        yield parse_container(container)


def before_save():
    return lib.validate_fps()


def on_save():

    log.info("Running callback on save..")

    nodes = lib.get_id_required_nodes()
    for node, new_id in lib.generate_ids(nodes):
        lib.set_id(node, new_id, overwrite=False)


def on_open():

    if not hou.isUIAvailable():
        log.debug("Batch mode detected, ignoring `on_open` callbacks..")
        return

    log.info("Running callback on open..")

    # Validate FPS after update_task_from_path to
    # ensure it is using correct FPS for the asset
    lib.validate_fps()

    if any_outdated_containers():
        from openpype.widgets import popup

        log.warning("Scene has outdated content.")

        # Get main window
        parent = get_main_window()
        if parent is None:
            log.info("Skipping outdated content pop-up "
                     "because Houdini window can't be found.")
        else:

            # Show outdated pop-up
            def _on_show_inventory():
                from openpype.tools.utils import host_tools
                host_tools.show_scene_inventory(parent=parent)

            dialog = popup.Popup(parent=parent)
            dialog.setWindowTitle("Houdini scene has outdated content")
            dialog.setMessage("There are outdated containers in "
                              "your Houdini scene.")
            dialog.on_clicked.connect(_on_show_inventory)
            dialog.show()


def on_new():
    """Set project resolution and fps when create a new file"""

    if hou.hipFile.isLoadingHipFile():
        # This event also triggers when Houdini opens a file due to the
        # new event being registered to 'afterClear'. As such we can skip
        # 'new' logic if the user is opening a file anyway
        log.debug("Skipping on new callback due to scene being opened.")
        return

    log.info("Running callback on new..")
    _set_context_settings()

    # It seems that the current frame always gets reset to frame 1 on
    # new scene. So we enforce current frame to be at the start of the playbar
    # with execute deferred
    def _enforce_start_frame():
        start = hou.playbar.playbackRange()[0]
        hou.setFrame(start)

    if hou.isUIAvailable():
        import hdefereval
        hdefereval.executeDeferred(_enforce_start_frame)
    else:
        # Run without execute deferred when no UI is available because
        # without UI `hdefereval` is not available to import
        _enforce_start_frame()


def _set_context_settings():
    """Apply the project settings from the project definition

    Settings can be overwritten by an asset if the asset.data contains
    any information regarding those settings.

    Examples of settings:
        fps
        resolution
        renderer

    Returns:
        None
    """

    # Set new scene fps
    fps = get_asset_fps()
    print("Setting scene FPS to %i" % fps)
    lib.set_scene_fps(fps)

    lib.reset_framerange()


def on_pyblish_instance_toggled(instance, new_value, old_value):
    """Toggle saver tool passthrough states on instance toggles."""
    @contextlib.contextmanager
    def main_take(no_update=True):
        """Enter root take during context"""
        original_take = hou.takes.currentTake()
        original_update_mode = hou.updateModeSetting()
        root = hou.takes.rootTake()
        has_changed = False
        try:
            if original_take != root:
                has_changed = True
                if no_update:
                    hou.setUpdateMode(hou.updateMode.Manual)
                hou.takes.setCurrentTake(root)
                yield
        finally:
            if has_changed:
                if no_update:
                    hou.setUpdateMode(original_update_mode)
                hou.takes.setCurrentTake(original_take)

    if not instance.data.get("_allowToggleBypass", True):
        return

    nodes = instance[:]
    if not nodes:
        return

    # Assume instance node is first node
    instance_node = nodes[0]

    if not hasattr(instance_node, "isBypassed"):
        # Likely not a node that can actually be bypassed
        log.debug("Can't bypass node: %s", instance_node.path())
        return

    if instance_node.isBypassed() != (not old_value):
        print("%s old bypass state didn't match old instance state, "
              "updating anyway.." % instance_node.path())

    try:
        # Go into the main take, because when in another take changing
        # the bypass state of a note cannot be done due to it being locked
        # by default.
        with main_take(no_update=True):
            instance_node.bypass(not new_value)
    except hou.PermissionError as exc:
        log.warning("%s - %s", instance_node.path(), exc)
