# -*- coding: utf-8 -*-
"""Creator plugin for creating workfiles."""
from openpype import AYON_SERVER_ENABLED
from openpype.pipeline import CreatedInstance, AutoCreator
from openpype.client import get_asset_by_name, get_asset_name_identifier
from openpype.hosts.max.api import plugin
from openpype.hosts.max.api.lib import read, imprint
from pymxs import runtime as rt


class CreateWorkfile(plugin.MaxCreatorBase, AutoCreator):
    """Workfile auto-creator."""
    identifier = "io.openpype.creators.max.workfile"
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
        asset_name = self.create_context.get_current_asset_name()
        task_name = self.create_context.get_current_task_name()
        host_name = self.create_context.host_name

        if current_instance is None:
            current_instance_asset = None
        elif AYON_SERVER_ENABLED:
            current_instance_asset = current_instance["folderPath"]
        else:
            current_instance_asset = current_instance["asset"]

        if current_instance is None:
            asset_doc = get_asset_by_name(project_name, asset_name)
            subset_name = self.get_subset_name(
                variant, task_name, asset_doc, project_name, host_name
            )
            data = {
                "task": task_name,
                "variant": variant
            }
            if AYON_SERVER_ENABLED:
                data["folderPath"] = asset_name
            else:
                data["asset"] = asset_name

            data.update(
                self.get_dynamic_data(
                    variant, task_name, asset_doc,
                    project_name, host_name, current_instance)
            )
            self.log.info("Auto-creating workfile instance...")
            instance_node = self.create_node(subset_name)
            data["instance_node"] = instance_node.name
            current_instance = CreatedInstance(
                self.family, subset_name, data, self
            )
            self._add_instance_to_context(current_instance)
            imprint(instance_node.name, current_instance.data)
        elif (
            current_instance_asset != asset_name
            or current_instance["task"] != task_name
        ):
            # Update instance context if is not the same
            asset_doc = get_asset_by_name(project_name, asset_name)
            subset_name = self.get_subset_name(
                variant, task_name, asset_doc, project_name, host_name
            )
            asset_name = get_asset_name_identifier(asset_doc)

            if AYON_SERVER_ENABLED:
                current_instance["folderPath"] = asset_name
            else:
                current_instance["asset"] = asset_name
            current_instance["task"] = task_name
            current_instance["subset"] = subset_name

    def collect_instances(self):
        self.cache_subsets(self.collection_shared_data)
        for instance in self.collection_shared_data["max_cached_subsets"].get(self.identifier, []):  # noqa
            if not rt.getNodeByName(instance):
                continue
            created_instance = CreatedInstance.from_existing(
                read(rt.GetNodeByName(instance)), self
            )
            self._add_instance_to_context(created_instance)

    def update_instances(self, update_list):
        for created_inst, _ in update_list:
            instance_node = created_inst.get("instance_node")
            imprint(
                instance_node,
                created_inst.data_to_store()
            )

    def remove_instances(self, instances):
        """Remove specified instance from the scene.

        This is only removing `id` parameter so instance is no longer
        instance, because it might contain valuable data for artist.

        """
        for instance in instances:
            instance_node = rt.GetNodeByName(
                instance.data.get("instance_node"))
            if instance_node:
                rt.Delete(instance_node)

            self._remove_instance_from_context(instance)

    def create_node(self, subset_name):
        if rt.getNodeByName(subset_name):
            node = rt.getNodeByName(subset_name)
            return node
        node = rt.Container(name=subset_name)
        node.isHidden = True
        return node
