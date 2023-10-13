import os
import logging
from functools import partial

from qtpy import QtWidgets, QtGui

import maya.utils
import maya.cmds as cmds

from openpype.pipeline import (
    get_current_asset_name,
    get_current_task_name
)
from openpype.pipeline.workfile import BuildWorkfile
from openpype.tools.utils import host_tools
from openpype.hosts.maya.api import lib, lib_rendersettings
from .lib import get_main_window, IS_HEADLESS
from ..tools import show_look_assigner

from .workfile_template_builder import (
    create_placeholder,
    update_placeholder,
    build_workfile_template,
    update_workfile_template,
)

log = logging.getLogger(__name__)

MENU_NAME = "op_maya_menu"


def _get_menu(menu_name=None):
    """Return the menu instance if it currently exists in Maya"""
    if menu_name is None:
        menu_name = MENU_NAME

    widgets = {w.objectName(): w for w in QtWidgets.QApplication.allWidgets()}
    return widgets.get(menu_name)


def get_context_label():
    return "{}, {}".format(
        get_current_asset_name(),
        get_current_task_name()
    )


def install(project_settings):
    if cmds.about(batch=True):
        log.info("Skipping openpype.menu initialization in batch mode..")
        return

    def add_menu():
        pyblish_icon = host_tools.get_pyblish_icon()
        parent_widget = get_main_window()
        cmds.menu(
            MENU_NAME,
            label=os.environ.get("AVALON_LABEL") or "OpenPype",
            tearOff=True,
            parent="MayaWindow"
        )

        # Create context menu
        cmds.menuItem(
            "currentContext",
            label=get_context_label(),
            parent=MENU_NAME,
            enable=False
        )

        cmds.setParent("..", menu=True)

        cmds.menuItem(divider=True)

        cmds.menuItem(
            "Create...",
            command=lambda *args: host_tools.show_publisher(
                parent=parent_widget,
                tab="create"
            )
        )

        cmds.menuItem(
            "Load...",
            command=lambda *args: host_tools.show_loader(
                parent=parent_widget,
                use_context=True
            )
        )

        cmds.menuItem(
            "Publish...",
            command=lambda *args: host_tools.show_publisher(
                parent=parent_widget,
                tab="publish"
            ),
            image=pyblish_icon
        )

        cmds.menuItem(
            "Manage...",
            command=lambda *args: host_tools.show_scene_inventory(
                parent=parent_widget
            )
        )

        cmds.menuItem(
            "Library...",
            command=lambda *args: host_tools.show_library_loader(
                parent=parent_widget
            )
        )

        cmds.menuItem(divider=True)

        cmds.menuItem(
            "Work Files...",
            command=lambda *args: host_tools.show_workfiles(
                parent=parent_widget
            ),
        )

        cmds.menuItem(
            "Set Frame Range",
            command=lambda *args: lib.reset_frame_range()
        )

        cmds.menuItem(
            "Set Resolution",
            command=lambda *args: lib.reset_scene_resolution()
        )

        cmds.menuItem(
            "Set Colorspace",
            command=lambda *args: lib.set_colorspace(),
        )

        cmds.menuItem(
            "Set Render Settings",
            command=lambda *args: lib_rendersettings.RenderSettings().set_default_renderer_settings()    # noqa
        )

        cmds.menuItem(divider=True, parent=MENU_NAME)
        cmds.menuItem(
            "Build First Workfile",
            parent=MENU_NAME,
            command=lambda *args: BuildWorkfile().process()
        )

        cmds.menuItem(
            "Look assigner...",
            command=lambda *args: show_look_assigner(
                parent_widget
            )
        )

        cmds.menuItem(
            "Experimental tools...",
            command=lambda *args: host_tools.show_experimental_tools_dialog(
                parent_widget
            )
        )

        builder_menu = cmds.menuItem(
            "Template Builder",
            subMenu=True,
            tearOff=True,
            parent=MENU_NAME
        )
        cmds.menuItem(
            "Create Placeholder",
            parent=builder_menu,
            command=create_placeholder
        )
        cmds.menuItem(
            "Update Placeholder",
            parent=builder_menu,
            command=update_placeholder
        )
        cmds.menuItem(
            "Build Workfile from template",
            parent=builder_menu,
            command=build_workfile_template
        )
        cmds.menuItem(
            "Update Workfile from template",
            parent=builder_menu,
            command=update_workfile_template
        )

        cmds.setParent(MENU_NAME, menu=True)

    def add_scripts_menu(project_settings):
        try:
            import scriptsmenu.launchformaya as launchformaya
        except ImportError:
            log.warning(
                "Skipping studio.menu install, because "
                "'scriptsmenu' module seems unavailable."
            )
            return

        config = project_settings["maya"]["scriptsmenu"]["definition"]
        _menu = project_settings["maya"]["scriptsmenu"]["name"]

        if not config:
            log.warning("Skipping studio menu, no definition found.")
            return

        # run the launcher for Maya menu
        studio_menu = launchformaya.main(
            title=_menu.title(),
            objectName=_menu.title().lower().replace(" ", "_")
        )

        # apply configuration
        studio_menu.build_from_configuration(studio_menu, config)

    # Allow time for uninstallation to finish.
    # We use Maya's executeDeferred instead of QTimer.singleShot
    # so that it only gets called after Maya UI has initialized too.
    # This is crucial with Maya 2020+ which initializes without UI
    # first as a QCoreApplication
    maya.utils.executeDeferred(add_menu)
    cmds.evalDeferred(partial(add_scripts_menu, project_settings),
                      lowestPriority=True)


def uninstall():
    menu = _get_menu()
    if menu:
        log.info("Attempting to uninstall ...")

        try:
            menu.deleteLater()
            del menu
        except Exception as e:
            log.error(e)


def popup():
    """Pop-up the existing menu near the mouse cursor."""
    menu = _get_menu()
    cursor = QtGui.QCursor()
    point = cursor.pos()
    menu.exec_(point)


def update_menu_task_label():
    """Update the task label in Avalon menu to current session"""

    if IS_HEADLESS:
        return

    object_name = "{}|currentContext".format(MENU_NAME)
    if not cmds.menuItem(object_name, query=True, exists=True):
        log.warning("Can't find menuItem: {}".format(object_name))
        return

    label = get_context_label()
    cmds.menuItem(object_name, edit=True, label=label)
