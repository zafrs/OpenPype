import re

import pyblish.api

from openpype.hosts.photoshop import api as photoshop
from openpype.pipeline.create import SUBSET_NAME_ALLOWED_SYMBOLS
from openpype.pipeline.publish import (
    ValidateContentsOrder,
    PublishXmlValidationError,
)


class ValidateNamingRepair(pyblish.api.Action):
    """Repair the instance asset."""

    label = "Repair"
    icon = "wrench"
    on = "failed"

    def process(self, context, plugin):

        # Get the errored instances
        failed = []
        for result in context.data["results"]:
            if (result["error"] is not None and result["instance"] is not None
                    and result["instance"] not in failed):
                failed.append(result["instance"])

        invalid_chars, replace_char = plugin.get_replace_chars()
        self.log.debug("{} --- {}".format(invalid_chars, replace_char))

        # Apply pyblish.logic to get the instances for the plug-in
        instances = pyblish.api.instances_by_plugin(failed, plugin)
        stub = photoshop.stub()
        for instance in instances:
            self.log.debug("validate_naming instance {}".format(instance))
            current_layer_state = stub.get_layer(instance.data["layer"].id)
            self.log.debug("current_layer{}".format(current_layer_state))

            layer_meta = stub.read(current_layer_state)
            instance_id = (layer_meta.get("instance_id") or
                           layer_meta.get("uuid"))
            if not instance_id:
                self.log.warning("Unable to repair, cannot find layer")
                continue

            layer_name = re.sub(invalid_chars,
                                replace_char,
                                current_layer_state.clean_name)
            layer_name = stub.PUBLISH_ICON + layer_name

            stub.rename_layer(current_layer_state.id, layer_name)

            subset_name = re.sub(invalid_chars, replace_char,
                                 instance.data["subset"])

            # format from Tool Creator
            subset_name = re.sub(
                "[^{}]+".format(SUBSET_NAME_ALLOWED_SYMBOLS),
                "",
                subset_name
            )

            layer_meta["subset"] = subset_name
            stub.imprint(instance_id, layer_meta)

        return True


class ValidateNaming(pyblish.api.InstancePlugin):
    """Validate the instance name.

    Spaces in names are not allowed. Will be replace with underscores.
    """

    label = "Validate Naming"
    hosts = ["photoshop"]
    order = ValidateContentsOrder
    families = ["image"]
    actions = [ValidateNamingRepair]

    # configured by Settings
    invalid_chars = ''
    replace_char = ''

    def process(self, instance):
        help_msg = ' Use Repair button to fix it and then refresh publish.'

        layer = instance.data.get("layer")
        if layer:
            msg = "Name \"{}\" is not allowed.{}".format(layer.clean_name,
                                                         help_msg)

            formatting_data = {"msg": msg}
            if re.search(self.invalid_chars, layer.clean_name):
                raise PublishXmlValidationError(self, msg,
                                                formatting_data=formatting_data
                                                )

        msg = "Subset \"{}\" is not allowed.{}".format(instance.data["subset"],
                                                       help_msg)
        formatting_data = {"msg": msg}
        if re.search(self.invalid_chars, instance.data["subset"]):
            raise PublishXmlValidationError(self, msg,
                                            formatting_data=formatting_data)

    @classmethod
    def get_replace_chars(cls):
        """Pass values configured in Settings for Repair."""
        return cls.invalid_chars, cls.replace_char
