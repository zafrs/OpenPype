import os
from openpype.lib import Logger
from openpype.settings import get_project_settings

log = Logger.get_logger(__name__)


def initialize():
    from openpype.hosts.traypublisher.api.plugin import SettingsCreator

    project_name = os.environ["AVALON_PROJECT"]
    project_settings = get_project_settings(project_name)

    simple_creators = project_settings["traypublisher"]["simple_creators"]

    global_variables = globals()
    for item in simple_creators:

        dynamic_plugin = SettingsCreator.from_settings(item)
        global_variables[dynamic_plugin.__name__] = dynamic_plugin


initialize()
