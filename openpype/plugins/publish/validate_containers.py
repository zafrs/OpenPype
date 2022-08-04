import pyblish.api
from openpype.pipeline.load import any_outdated_containers


class ShowInventory(pyblish.api.Action):

    label = "Show Inventory"
    icon = "briefcase"
    on = "failed"

    def process(self, context, plugin):
        from openpype.tools.utils import host_tools

        host_tools.show_scene_inventory()


class ValidateContainers(pyblish.api.ContextPlugin):
    """Containers are must be updated to latest version on publish."""

    label = "Validate Containers"
    order = pyblish.api.ValidatorOrder
    hosts = ["maya", "houdini", "nuke", "harmony", "photoshop", "aftereffects"]
    optional = True
    actions = [ShowInventory]

    def process(self, context):
        if any_outdated_containers():
            raise ValueError("There are outdated containers in the scene.")
