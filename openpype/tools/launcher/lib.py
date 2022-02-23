"""Utility script for updating database with configuration files

Until assets are created entirely in the database, this script
provides a bridge between the file-based project inventory and configuration.

- Migrating an old project:
    $ python -m avalon.inventory --extract --silo-parent=f02_prod
    $ python -m avalon.inventory --upload

- Managing an existing project:
    1. Run `python -m avalon.inventory --load`
    2. Update the .inventory.toml or .config.toml
    3. Run `python -m avalon.inventory --save`

"""

import os
from Qt import QtGui
from avalon.vendor import qtawesome
from openpype.api import resources

ICON_CACHE = {}
NOT_FOUND = type("NotFound", (object, ), {})


def get_action_icon(action):
    icon_name = action.icon
    if not icon_name:
        return None

    global ICON_CACHE

    icon = ICON_CACHE.get(icon_name)
    if icon is NOT_FOUND:
        return None
    elif icon:
        return icon

    icon_path = resources.get_resource(icon_name)
    if not os.path.exists(icon_path):
        icon_path = icon_name.format(resources.RESOURCES_DIR)

    if os.path.exists(icon_path):
        icon = QtGui.QIcon(icon_path)
        ICON_CACHE[icon_name] = icon
        return icon

    try:
        icon_color = getattr(action, "color", None) or "white"
        icon = qtawesome.icon(
            "fa.{}".format(icon_name), color=icon_color
        )

    except Exception:
        ICON_CACHE[icon_name] = NOT_FOUND
        print("Can't load icon \"{}\"".format(icon_name))

    return icon


def get_action_label(action):
    label = getattr(action, "label", None)
    if not label:
        return action.name

    label_variant = getattr(action, "label_variant", None)
    if not label_variant:
        return label
    return " ".join([label, label_variant])
