# -*- coding: utf-8 -*-
"""Collect publishable instances in Unreal."""
import ast
import unreal  # noqa
import pyblish.api
from openpype.hosts.unreal.api.pipeline import UNREAL_VERSION
from openpype.pipeline.publish import KnownPublishError


class CollectInstances(pyblish.api.ContextPlugin):
    """Gather instances by OpenPypePublishInstance class

    This collector finds all paths containing `OpenPypePublishInstance` class
    asset

    Identifier:
        id (str): "pyblish.avalon.instance"

    """

    label = "Collect Instances"
    order = pyblish.api.CollectorOrder - 0.1
    hosts = ["unreal"]

    def process(self, context):

        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        class_name = ["/Script/OpenPype",
                      "AssetContainer"] if UNREAL_VERSION.major == 5 and \
                                           UNREAL_VERSION.minor > 0 else "OpenPypePublishInstance"  # noqa
        instance_containers = ar.get_assets_by_class(class_name, True)

        for container_data in instance_containers:
            asset = container_data.get_asset()
            data = unreal.EditorAssetLibrary.get_metadata_tag_values(asset)
            data["objectName"] = container_data.asset_name
            # convert to strings
            data = {str(key): str(value) for (key, value) in data.items()}
            if not data.get("family"):
                raise KnownPublishError("instance has no family")

            # content of container
            members = ast.literal_eval(data.get("members"))
            self.log.debug(members)
            self.log.debug(asset.get_path_name())
            # remove instance container
            self.log.info("Creating instance for {}".format(asset.get_name()))

            instance = context.create_instance(asset.get_name())
            instance[:] = members

            # Store the exact members of the object set
            instance.data["setMembers"] = members
            instance.data["families"] = [data.get("family")]
            instance.data["level"] = data.get("level")
            instance.data["parent"] = data.get("parent")

            label = "{0} ({1})".format(asset.get_name()[:-4],
                                       data["asset"])

            instance.data["label"] = label

            instance.data.update(data)
