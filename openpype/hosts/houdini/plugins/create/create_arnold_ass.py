# -*- coding: utf-8 -*-
"""Creator plugin for creating Arnold ASS files."""
from openpype.hosts.houdini.api import plugin


class CreateArnoldAss(plugin.HoudiniCreator):
    """Arnold .ass Archive"""

    identifier = "io.openpype.creators.houdini.ass"
    label = "Arnold ASS"
    family = "ass"
    icon = "magic"
    defaults = ["Main"]

    # Default extension: `.ass` or `.ass.gz`
    ext = ".ass"

    def create(self, subset_name, instance_data, pre_create_data):
        import hou

        instance_data.pop("active", None)
        instance_data.update({"node_type": "arnold"})

        instance = super(CreateArnoldAss, self).create(
            subset_name,
            instance_data,
            pre_create_data)  # type: plugin.CreatedInstance

        instance_node = hou.node(instance.get("instance_node"))

        # Hide Properties Tab on Arnold ROP since that's used
        # for rendering instead of .ass Archive Export
        parm_template_group = instance_node.parmTemplateGroup()
        parm_template_group.hideFolder("Properties", True)
        instance_node.setParmTemplateGroup(parm_template_group)

        filepath = "{}{}".format(
            hou.text.expandString("$HIP/pyblish/"),
            "{}.$F4{}".format(subset_name, self.ext)
        )
        parms = {
            # Render frame range
            "trange": 1,
            # Arnold ROP settings
            "ar_ass_file": filepath,
            "ar_ass_export_enable": 1
        }

        instance_node.setParms(parms)

        # Lock any parameters in this list
        to_lock = ["ar_ass_export_enable", "family", "id"]
        self.lock_parameters(instance_node, to_lock)
