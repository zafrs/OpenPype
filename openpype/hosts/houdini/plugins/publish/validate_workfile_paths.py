# -*- coding: utf-8 -*-
import pyblish.api
import hou
from openpype.pipeline import (
    PublishValidationError,
    OptionalPyblishPluginMixin
)
from openpype.pipeline.publish import RepairAction

from openpype.pipeline.publish import RepairAction


class ValidateWorkfilePaths(
        pyblish.api.InstancePlugin, OptionalPyblishPluginMixin):
    """Validate workfile paths so they are absolute."""

    order = pyblish.api.ValidatorOrder
    families = ["workfile"]
    hosts = ["houdini"]
    label = "Validate Workfile Paths"
    actions = [RepairAction]
    optional = True

    node_types = ["file", "alembic"]
    prohibited_vars = ["$HIP", "$JOB"]

    def process(self, instance):
        if not self.is_active(instance.data):
            return
        invalid = self.get_invalid()
        self.log.info(
            "node types to check: {}".format(", ".join(self.node_types)))
        self.log.info(
            "prohibited vars: {}".format(", ".join(self.prohibited_vars))
        )
        if invalid:
            for param in invalid:
                self.log.error(
                    "{}: {}".format(param.path(), param.unexpandedString()))

            raise PublishValidationError(
                "Invalid paths found", title=self.label)

    @classmethod
    def get_invalid(cls):
        invalid = []
        for param, _ in hou.fileReferences():
            # it might return None for some reason
            if not param:
                continue
            # skip nodes we are not interested in
            if param.node().type().name() not in cls.node_types:
                continue

            if any(
                    v for v in cls.prohibited_vars
                    if v in param.unexpandedString()):
                invalid.append(param)

        return invalid

    @classmethod
    def repair(cls, instance):
        invalid = cls.get_invalid()
        for param in invalid:
            cls.log.info("processing: {}".format(param.path()))
            cls.log.info("Replacing {} for {}".format(
                param.unexpandedString(),
                hou.text.expandString(param.unexpandedString())))
            param.set(hou.text.expandString(param.unexpandedString()))
