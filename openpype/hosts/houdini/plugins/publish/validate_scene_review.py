# -*- coding: utf-8 -*-
import pyblish.api
from openpype.pipeline import PublishValidationError
import hou


class ValidateSceneReview(pyblish.api.InstancePlugin):
    """Validator Some Scene Settings before publishing the review
        1. Scene Path
        2. Resolution
    """

    order = pyblish.api.ValidatorOrder
    families = ["review"]
    hosts = ["houdini"]
    label = "Scene Setting for review"

    def process(self, instance):
        invalid = self.get_invalid_scene_path(instance)

        report = []
        if invalid:
            report.append(
                "Scene path does not exist: '%s'" % invalid[0],
            )

        invalid = self.get_invalid_resolution(instance)
        if invalid:
            report.extend(invalid)

        if report:
            raise PublishValidationError(
                "\n\n".join(report),
                title=self.label)

    def get_invalid_scene_path(self, instance):

        node = hou.node(instance.data.get("instance_node"))
        scene_path_parm = node.parm("scenepath")
        scene_path_node = scene_path_parm.evalAsNode()
        if not scene_path_node:
            return [scene_path_parm.evalAsString()]

    def get_invalid_resolution(self, instance):
        node = hou.node(instance.data.get("instance_node"))

        # The resolution setting is only used when Override Camera Resolution
        # is enabled. So we skip validation if it is disabled.
        override = node.parm("tres").eval()
        if not override:
            return

        invalid = []
        res_width = node.parm("res1").eval()
        res_height = node.parm("res2").eval()
        if res_width == 0:
            invalid.append("Override Resolution width is set to zero.")
        if res_height == 0:
            invalid.append("Override Resolution height is set to zero")

        return invalid
