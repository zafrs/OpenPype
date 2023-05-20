# -*- coding: utf-8 -*-
"""Creator plugin for creating workfiles."""
from openpype.hosts.houdini.api import plugin
from openpype.hosts.houdini.api.lib import read, imprint
from openpype.hosts.houdini.api.pipeline import CONTEXT_CONTAINER
from openpype.pipeline import CreatedInstance, AutoCreator
from openpype.pipeline import legacy_io
from openpype.client import get_asset_by_name
import hou


class CreateWorkfile(plugin.HoudiniCreatorBase, AutoCreator):
    """Workfile auto-creator."""
    identifier = "io.openpype.creators.houdini.workfile"
    label = "Workfile"
    family = "workfile"
    icon = "fa5.file"

    default_variant = "Main"

    def create(self):
        variant = self.default_variant
        current_instance = next(
            (
                instance for instance in self.create_context.instances
                if instance.creator_identifier == self.identifier
            ), None)

        project_name = self.project_name
        asset_name = legacy_io.Session["AVALON_ASSET"]
        task_name = legacy_io.Session["AVALON_TASK"]
        host_name = legacy_io.Session["AVALON_APP"]

        if current_instance is None:
            asset_doc = get_asset_by_name(project_name, asset_name)
            subset_name = self.get_subset_name(
                variant, task_name, asset_doc, project_name, host_name
            )
            data = {
                "asset": asset_name,
                "task": task_name,
                "variant": variant
            }
            data.update(
                self.get_dynamic_data(
                    variant, task_name, asset_doc,
                    project_name, host_name, current_instance)
            )
            self.log.info("Auto-creating workfile instance...")
            current_instance = CreatedInstance(
                self.family, subset_name, data, self
            )
            self._add_instance_to_context(current_instance)
        elif (
                current_instance["asset"] != asset_name
                or current_instance["task"] != task_name
        ):
            # Update instance context if is not the same
            asset_doc = get_asset_by_name(project_name, asset_name)
            subset_name = self.get_subset_name(
                variant, task_name, asset_doc, project_name, host_name
            )
            current_instance["asset"] = asset_name
            current_instance["task"] = task_name
            current_instance["subset"] = subset_name

        # write workfile information to context container.
        op_ctx = hou.node(CONTEXT_CONTAINER)
        if not op_ctx:
            op_ctx = self.create_context_node()

        workfile_data = {"workfile": current_instance.data_to_store()}
        imprint(op_ctx, workfile_data)

    def collect_instances(self):
        op_ctx = hou.node(CONTEXT_CONTAINER)
        instance = read(op_ctx)
        if not instance:
            return
        workfile = instance.get("workfile")
        if not workfile:
            return
        created_instance = CreatedInstance.from_existing(
            workfile, self
        )
        self._add_instance_to_context(created_instance)

    def update_instances(self, update_list):
        op_ctx = hou.node(CONTEXT_CONTAINER)
        for created_inst, _changes in update_list:
            if created_inst["creator_identifier"] == self.identifier:
                workfile_data = {"workfile": created_inst.data_to_store()}
                imprint(op_ctx, workfile_data, update=True)
