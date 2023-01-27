import re

from openpype import resources
from openpype.lib import BoolDef, UISeparatorDef
from openpype.hosts.aftereffects import api
from openpype.pipeline import (
    Creator,
    CreatedInstance,
    CreatorError,
    legacy_io,
)
from openpype.hosts.aftereffects.api.pipeline import cache_and_get_instances
from openpype.lib import prepare_template_data


class RenderCreator(Creator):
    identifier = "render"
    label = "Render"
    family = "render"
    description = "Render creator"

    create_allow_context_change = True

    def __init__(self, project_settings, *args, **kwargs):
        super(RenderCreator, self).__init__(project_settings, *args, **kwargs)
        self._default_variants = (project_settings["aftereffects"]
                                                  ["create"]
                                                  ["RenderCreator"]
                                                  ["defaults"])

    def get_icon(self):
        return resources.get_openpype_splash_filepath()

    def collect_instances(self):
        for instance_data in cache_and_get_instances(self):
            # legacy instances have family=='render' or 'renderLocal', use them
            creator_id = (instance_data.get("creator_identifier") or
                          instance_data.get("family", '').replace("Local", ''))
            if creator_id == self.identifier:
                instance_data = self._handle_legacy(instance_data)
                instance = CreatedInstance.from_existing(
                    instance_data, self
                )
                self._add_instance_to_context(instance)

    def update_instances(self, update_list):
        for created_inst, _changes in update_list:
            api.get_stub().imprint(created_inst.get("instance_id"),
                                   created_inst.data_to_store())
            subset_change = _changes.get("subset")
            if subset_change:
                api.get_stub().rename_item(created_inst.data["members"][0],
                                           subset_change[1])

    def remove_instances(self, instances):
        for instance in instances:
            self._remove_instance_from_context(instance)
            self.host.remove_instance(instance)

            subset = instance.data["subset"]
            comp_id = instance.data["members"][0]
            comp = api.get_stub().get_item(comp_id)
            if comp:
                new_comp_name = comp.name.replace(subset, '')
                if not new_comp_name:
                    new_comp_name = "dummyCompName"
                api.get_stub().rename_item(comp_id,
                                           new_comp_name)

    def create(self, subset_name_from_ui, data, pre_create_data):
        stub = api.get_stub()  # only after After Effects is up
        if pre_create_data.get("use_selection"):
            comps = stub.get_selected_items(
                comps=True, folders=False, footages=False
            )
        else:
            comps = stub.get_items(comps=True, folders=False, footages=False)

        if not comps:
            raise CreatorError(
                "Nothing to create. Select composition "
                "if 'useSelection' or create at least "
                "one composition."
            )

        for comp in comps:
            if pre_create_data.get("use_composition_name"):
                composition_name = comp.name
                dynamic_fill = prepare_template_data({"composition":
                                                      composition_name})
                subset_name = subset_name_from_ui.format(**dynamic_fill)
                data["composition_name"] = composition_name
            else:
                subset_name = subset_name_from_ui
                subset_name = re.sub(r"\{composition\}", '', subset_name,
                                     flags=re.IGNORECASE)

            for inst in self.create_context.instances:
                if subset_name == inst.subset_name:
                    raise CreatorError("{} already exists".format(
                        inst.subset_name))

            data["members"] = [comp.id]
            new_instance = CreatedInstance(self.family, subset_name, data,
                                           self)
            if "farm" in pre_create_data:
                use_farm = pre_create_data["farm"]
                new_instance.creator_attributes["farm"] = use_farm

            api.get_stub().imprint(new_instance.id,
                                   new_instance.data_to_store())
            self._add_instance_to_context(new_instance)

            stub.rename_item(comp.id, subset_name)

    def get_default_variants(self):
        return self._default_variants

    def get_instance_attr_defs(self):
        return [BoolDef("farm", label="Render on farm")]

    def get_pre_create_attr_defs(self):
        output = [
            BoolDef("use_selection", default=True, label="Use selection"),
            BoolDef("use_composition_name",
                    label="Use composition name in subset"),
            UISeparatorDef(),
            BoolDef("farm", label="Render on farm")
        ]
        return output

    def get_detail_description(self):
        return """Creator for Render instances"""

    def get_dynamic_data(self, variant, task_name, asset_doc,
                         project_name, host_name, instance):
        dynamic_data = {}
        if instance is not None:
            composition_name = instance.get("composition_name")
            if composition_name:
                dynamic_data["composition"] = composition_name
        else:
            dynamic_data["composition"] = "{composition}"

        return dynamic_data

    def _handle_legacy(self, instance_data):
        """Converts old instances to new format."""
        if not instance_data.get("members"):
            instance_data["members"] = [instance_data.get("uuid")]

        if instance_data.get("uuid"):
            # uuid not needed, replaced with unique instance_id
            api.get_stub().remove_instance(instance_data.get("uuid"))
            instance_data.pop("uuid")

        if not instance_data.get("task"):
            instance_data["task"] = legacy_io.Session.get("AVALON_TASK")

        if not instance_data.get("creator_attributes"):
            is_old_farm = instance_data["family"] != "renderLocal"
            instance_data["creator_attributes"] = {"farm": is_old_farm}
            instance_data["family"] = self.family

        return instance_data
