"""A module containing generic loader actions that will display in the Loader.

"""

from openpype.lib import Logger
from openpype.pipeline import load

log = Logger.get_logger(__name__)


class SetFrameRangeLoader(load.LoaderPlugin):
    """Set frame range excluding pre- and post-handles"""

    families = ["animation",
                "camera",
                "write",
                "yeticache",
                "pointcache"]
    representations = ["*"]
    extensions = {"*"}

    label = "Set frame range"
    order = 11
    icon = "clock-o"
    color = "white"

    def load(self, context, name, namespace, data):

        from openpype.hosts.nuke.api import lib

        version = context['version']
        version_data = version.get("data", {})

        start = version_data.get("frameStart", None)
        end = version_data.get("frameEnd", None)

        log.info("start: {}, end: {}".format(start, end))
        if start is None or end is None:
            log.info("Skipping setting frame range because start or "
                     "end frame data is missing..")
            return

        lib.update_frame_range(start, end)


class SetFrameRangeWithHandlesLoader(load.LoaderPlugin):
    """Set frame range including pre- and post-handles"""

    families = ["animation",
                "camera",
                "write",
                "yeticache",
                "pointcache"]
    representations = ["*"]

    label = "Set frame range (with handles)"
    order = 12
    icon = "clock-o"
    color = "white"

    def load(self, context, name, namespace, data):

        from openpype.hosts.nuke.api import lib

        version = context['version']
        version_data = version.get("data", {})

        start = version_data.get("frameStart", None)
        end = version_data.get("frameEnd", None)

        if start is None or end is None:
            print("Skipping setting frame range because start or "
                  "end frame data is missing..")
            return

        # Include handles
        start -= version_data.get("handleStart", 0)
        end += version_data.get("handleEnd", 0)

        lib.update_frame_range(start, end)
