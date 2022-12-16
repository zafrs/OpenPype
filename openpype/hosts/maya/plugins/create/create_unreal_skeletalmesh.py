# -*- coding: utf-8 -*-
"""Creator for Unreal Skeletal Meshes."""
from openpype.hosts.maya.api import plugin, lib
from openpype.pipeline import legacy_io
from maya import cmds  # noqa


class CreateUnrealSkeletalMesh(plugin.Creator):
    """Unreal Static Meshes with collisions."""
    name = "staticMeshMain"
    label = "Unreal - Skeletal Mesh"
    family = "skeletalMesh"
    icon = "thumbs-up"
    dynamic_subset_keys = ["asset"]

    joint_hints = []

    def __init__(self, *args, **kwargs):
        """Constructor."""
        super(CreateUnrealSkeletalMesh, self).__init__(*args, **kwargs)

    @classmethod
    def get_dynamic_data(
            cls, variant, task_name, asset_id, project_name, host_name
    ):
        dynamic_data = super(CreateUnrealSkeletalMesh, cls).get_dynamic_data(
            variant, task_name, asset_id, project_name, host_name
        )
        dynamic_data["asset"] = legacy_io.Session.get("AVALON_ASSET")
        return dynamic_data

    def process(self):
        self.name = "{}_{}".format(self.family, self.name)
        with lib.undo_chunk():
            instance = super(CreateUnrealSkeletalMesh, self).process()
            content = cmds.sets(instance, query=True)

            # empty set and process its former content
            cmds.sets(content, rm=instance)
            geometry_set = cmds.sets(name="geometry_SET", empty=True)
            joints_set = cmds.sets(name="joints_SET", empty=True)

            cmds.sets([geometry_set, joints_set], forceElement=instance)
            members = cmds.ls(content) or []

            for node in members:
                if node in self.joint_hints:
                    cmds.sets(node, forceElement=joints_set)
                else:
                    cmds.sets(node, forceElement=geometry_set)

            # Add animation data
            self.data.update(lib.collect_animation_data())

            # Only renderable visible shapes
            self.data["renderableOnly"] = False
            # only nodes that are visible
            self.data["visibleOnly"] = False
            # Include parent groups
            self.data["includeParentHierarchy"] = False
            # Default to exporting world-space
            self.data["worldSpace"] = True
            # Default to suspend refresh.
            self.data["refresh"] = False

            # Add options for custom attributes
            self.data["attr"] = ""
            self.data["attrPrefix"] = ""
