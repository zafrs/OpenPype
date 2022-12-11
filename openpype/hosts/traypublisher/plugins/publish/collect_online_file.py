# -*- coding: utf-8 -*-
import pyblish.api
from pathlib import Path


class CollectOnlineFile(pyblish.api.InstancePlugin):
    """Collect online file and retain its file name."""
    label = "Collect Online File"
    order = pyblish.api.CollectorOrder
    families = ["online"]
    hosts = ["traypublisher"]

    def process(self, instance):
        file = Path(instance.data["creator_attributes"]["path"])

        instance.data["representations"].append(
            {
                "name": file.suffix.lstrip("."),
                "ext": file.suffix.lstrip("."),
                "files": file.name,
                "stagingDir": file.parent.as_posix()
            }
        )
