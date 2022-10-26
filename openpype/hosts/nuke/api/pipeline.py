import os
import importlib
from collections import OrderedDict

import nuke

import pyblish.api

import openpype
from openpype.settings import get_current_project_settings
from openpype.lib import register_event_callback, Logger
from openpype.pipeline import (
    register_loader_plugin_path,
    register_creator_plugin_path,
    register_inventory_action_path,
    deregister_loader_plugin_path,
    deregister_creator_plugin_path,
    deregister_inventory_action_path,
    AVALON_CONTAINER_ID,
)
from openpype.pipeline.workfile import BuildWorkfile
from openpype.tools.utils import host_tools

from .command import viewer_update_and_undo_stop
from .lib import (
    Context,
    get_main_window,
    add_publish_knob,
    WorkfileSettings,
    process_workfile_builder,
    launch_workfiles_app,
    check_inventory_versions,
    set_avalon_knob_data,
    read_avalon_data,
)
from .workfile_template_builder import (
    NukePlaceholderLoadPlugin,
    build_workfile_template,
    update_workfile_template,
    create_placeholder,
    update_placeholder,
)

log = Logger.get_logger(__name__)

HOST_DIR = os.path.dirname(os.path.abspath(openpype.hosts.nuke.__file__))
PLUGINS_DIR = os.path.join(HOST_DIR, "plugins")
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")
INVENTORY_PATH = os.path.join(PLUGINS_DIR, "inventory")

MENU_LABEL = os.environ["AVALON_LABEL"]


# registering pyblish gui regarding settings in presets
if os.getenv("PYBLISH_GUI", None):
    pyblish.api.register_gui(os.getenv("PYBLISH_GUI", None))


def reload_config():
    """Attempt to reload pipeline at run-time.

    CAUTION: This is primarily for development and debugging purposes.

    """

    for module in (
        "openpype.hosts.nuke.api.actions",
        "openpype.hosts.nuke.api.menu",
        "openpype.hosts.nuke.api.plugin",
        "openpype.hosts.nuke.api.lib",
    ):
        log.info("Reloading module: {}...".format(module))

        module = importlib.import_module(module)

        try:
            importlib.reload(module)
        except AttributeError as e:
            from importlib import reload
            log.warning("Cannot reload module: {}".format(e))
            reload(module)


def install():
    ''' Installing all requarements for Nuke host
    '''

    pyblish.api.register_host("nuke")

    log.info("Registering Nuke plug-ins..")
    pyblish.api.register_plugin_path(PUBLISH_PATH)
    register_loader_plugin_path(LOAD_PATH)
    register_creator_plugin_path(CREATE_PATH)
    register_inventory_action_path(INVENTORY_PATH)

    # Register Avalon event for workfiles loading.
    register_event_callback("workio.open_file", check_inventory_versions)
    register_event_callback("taskChanged", change_context_label)

    pyblish.api.register_callback(
        "instanceToggled", on_pyblish_instance_toggled)
    workfile_settings = WorkfileSettings()

    # Set context settings.
    nuke.addOnCreate(workfile_settings.set_context_settings, nodeClass="Root")
    nuke.addOnCreate(workfile_settings.set_favorites, nodeClass="Root")
    nuke.addOnCreate(process_workfile_builder, nodeClass="Root")

    _install_menu()
    launch_workfiles_app()


def uninstall():
    '''Uninstalling host's integration
    '''
    log.info("Deregistering Nuke plug-ins..")
    pyblish.deregister_host("nuke")
    pyblish.api.deregister_plugin_path(PUBLISH_PATH)
    deregister_loader_plugin_path(LOAD_PATH)
    deregister_creator_plugin_path(CREATE_PATH)
    deregister_inventory_action_path(INVENTORY_PATH)

    pyblish.api.deregister_callback(
        "instanceToggled", on_pyblish_instance_toggled)

    reload_config()
    _uninstall_menu()


def _show_workfiles():
    # Make sure parent is not set
    # - this makes Workfiles tool as separated window which
    #   avoid issues with reopening
    # - it is possible to explicitly change on top flag of the tool
    host_tools.show_workfiles(parent=None, on_top=False)


def get_workfile_build_placeholder_plugins():
    return [
        NukePlaceholderLoadPlugin
    ]


def _install_menu():
    # uninstall original avalon menu
    main_window = get_main_window()
    menubar = nuke.menu("Nuke")
    menu = menubar.addMenu(MENU_LABEL)

    label = "{0}, {1}".format(
        os.environ["AVALON_ASSET"], os.environ["AVALON_TASK"]
    )
    Context.context_label = label
    context_action = menu.addCommand(label)
    context_action.setEnabled(False)

    menu.addSeparator()
    menu.addCommand(
        "Work Files...",
        _show_workfiles
    )

    menu.addSeparator()
    menu.addCommand(
        "Create...",
        lambda: host_tools.show_creator(parent=main_window)
    )
    menu.addCommand(
        "Load...",
        lambda: host_tools.show_loader(
            parent=main_window,
            use_context=True
        )
    )
    menu.addCommand(
        "Publish...",
        lambda: host_tools.show_publish(parent=main_window)
    )
    menu.addCommand(
        "Manage...",
        lambda: host_tools.show_scene_inventory(parent=main_window)
    )
    menu.addCommand(
        "Library...",
        lambda: host_tools.show_library_loader(
            parent=main_window
        )
    )
    menu.addSeparator()
    menu.addCommand(
        "Set Resolution",
        lambda: WorkfileSettings().reset_resolution()
    )
    menu.addCommand(
        "Set Frame Range",
        lambda: WorkfileSettings().reset_frame_range_handles()
    )
    menu.addCommand(
        "Set Colorspace",
        lambda: WorkfileSettings().set_colorspace()
    )
    menu.addCommand(
        "Apply All Settings",
        lambda: WorkfileSettings().set_context_settings()
    )

    menu.addSeparator()
    menu.addCommand(
        "Build Workfile",
        lambda: BuildWorkfile().process()
    )

    menu_template = menu.addMenu("Template Builder")  # creating template menu
    menu_template.addCommand(
        "Build Workfile from template",
        lambda: build_workfile_template()
    )
    menu_template.addCommand(
        "Update Workfile",
        lambda: update_workfile_template()
    )
    menu_template.addSeparator()
    menu_template.addCommand(
        "Create Place Holder",
        lambda: create_placeholder()
    )
    menu_template.addCommand(
        "Update Place Holder",
        lambda: update_placeholder()
    )
    menu.addSeparator()
    menu.addCommand(
        "Experimental tools...",
        lambda: host_tools.show_experimental_tools_dialog(parent=main_window)
    )

    # add reload pipeline only in debug mode
    if bool(os.getenv("NUKE_DEBUG")):
        menu.addSeparator()
        menu.addCommand("Reload Pipeline", reload_config)

    # adding shortcuts
    add_shortcuts_from_presets()


def _uninstall_menu():
    menubar = nuke.menu("Nuke")
    menu = menubar.findItem(MENU_LABEL)

    for item in menu.items():
        log.info("Removing menu item: {}".format(item.name()))
        menu.removeItem(item.name())


def change_context_label():
    menubar = nuke.menu("Nuke")
    menu = menubar.findItem(MENU_LABEL)

    label = "{0}, {1}".format(
        os.environ["AVALON_ASSET"], os.environ["AVALON_TASK"]
    )

    rm_item = [
        (i, item) for i, item in enumerate(menu.items())
        if Context.context_label in item.name()
    ][0]

    menu.removeItem(rm_item[1].name())

    context_action = menu.addCommand(
        label,
        index=(rm_item[0])
    )
    context_action.setEnabled(False)

    log.info("Task label changed from `{}` to `{}`".format(
        Context.context_label, label))


def add_shortcuts_from_presets():
    menubar = nuke.menu("Nuke")
    nuke_presets = get_current_project_settings()["nuke"]["general"]

    if nuke_presets.get("menu"):
        menu_label_mapping = {
            "manage": "Manage...",
            "create": "Create...",
            "load": "Load...",
            "build_workfile": "Build Workfile",
            "publish": "Publish..."
        }

        for command_name, shortcut_str in nuke_presets.get("menu").items():
            log.info("menu_name `{}` | menu_label `{}`".format(
                command_name, MENU_LABEL
            ))
            log.info("Adding Shortcut `{}` to `{}`".format(
                shortcut_str, command_name
            ))
            try:
                menu = menubar.findItem(MENU_LABEL)
                item_label = menu_label_mapping[command_name]
                menuitem = menu.findItem(item_label)
                menuitem.setShortcut(shortcut_str)
            except AttributeError as e:
                log.error(e)


def on_pyblish_instance_toggled(instance, old_value, new_value):
    """Toggle node passthrough states on instance toggles."""

    log.info("instance toggle: {}, old_value: {}, new_value:{} ".format(
        instance, old_value, new_value))

    # Whether instances should be passthrough based on new value

    with viewer_update_and_undo_stop():
        n = instance[0]
        try:
            n["publish"].value()
        except ValueError:
            n = add_publish_knob(n)
            log.info(" `Publish` knob was added to write node..")

        n["publish"].setValue(new_value)


def containerise(node,
                 name,
                 namespace,
                 context,
                 loader=None,
                 data=None):
    """Bundle `node` into an assembly and imprint it with metadata

    Containerisation enables a tracking of version, author and origin
    for loaded assets.

    Arguments:
        node (nuke.Node): Nuke's node object to imprint as container
        name (str): Name of resulting assembly
        namespace (str): Namespace under which to host container
        context (dict): Asset information
        loader (str, optional): Name of node used to produce this container.

    Returns:
        node (nuke.Node): containerised nuke's node object

    """
    data = OrderedDict(
        [
            ("schema", "openpype:container-2.0"),
            ("id", AVALON_CONTAINER_ID),
            ("name", name),
            ("namespace", namespace),
            ("loader", str(loader)),
            ("representation", context["representation"]["_id"]),
        ],

        **data or dict()
    )

    set_avalon_knob_data(node, data)

    return node


def parse_container(node):
    """Returns containerised data of a node

    Reads the imprinted data from `containerise`.

    Arguments:
        node (nuke.Node): Nuke's node object to read imprinted data

    Returns:
        dict: The container schema data for this container node.

    """
    data = read_avalon_data(node)

    # (TODO) Remove key validation when `ls` has re-implemented.
    #
    # If not all required data return the empty container
    required = ["schema", "id", "name",
                "namespace", "loader", "representation"]
    if not all(key in data for key in required):
        return

    # Store the node's name
    data["objectName"] = node["name"].value()

    return data


def update_container(node, keys=None):
    """Returns node with updateted containder data

    Arguments:
        node (nuke.Node): The node in Nuke to imprint as container,
        keys (dict, optional): data which should be updated

    Returns:
        node (nuke.Node): nuke node with updated container data

    Raises:
        TypeError on given an invalid container node

    """
    keys = keys or dict()

    container = parse_container(node)
    if not container:
        raise TypeError("Not a valid container node.")

    container.update(keys)
    node = set_avalon_knob_data(node, container)

    return node


def ls():
    """List available containers.

    This function is used by the Container Manager in Nuke. You'll
    need to implement a for-loop that then *yields* one Container at
    a time.

    See the `container.json` schema for details on how it should look,
    and the Maya equivalent, which is in `avalon.maya.pipeline`
    """
    all_nodes = nuke.allNodes(recurseGroups=False)

    # TODO: add readgeo, readcamera, readimage
    nodes = [n for n in all_nodes]

    for n in nodes:
        log.debug("name: `{}`".format(n.name()))
        container = parse_container(n)
        if container:
            yield container
