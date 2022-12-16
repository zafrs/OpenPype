from maya import cmds

import pyblish.api

import openpype.hosts.maya.api.action
from openpype.pipeline.publish import ValidateContentsOrder


class ValidateRenderNoDefaultCameras(pyblish.api.InstancePlugin):
    """Ensure no default (startup) cameras are to be rendered."""

    order = ValidateContentsOrder
    hosts = ['maya']
    families = ['renderlayer']
    label = "No Default Cameras Renderable"
    actions = [openpype.hosts.maya.api.action.SelectInvalidAction]

    @staticmethod
    def get_invalid(instance):

        renderable = set(instance.data["cameras"])

        # Collect default cameras
        cameras = cmds.ls(type='camera', long=True)
        defaults = set(cam for cam in cameras if
                       cmds.camera(cam, query=True, startupCamera=True))

        return [cam for cam in renderable if cam in defaults]

    def process(self, instance):
        """Process all the cameras in the instance"""
        invalid = self.get_invalid(instance)
        if invalid:
            raise RuntimeError("Renderable default cameras "
                               "found: {0}".format(invalid))
