import pyblish.api
from openpype.pipeline.publish import get_errored_instances_from_context
from openpype.hosts.nuke.api.lib import (
    get_write_node_template_attr,
    set_node_knobs_from_settings,
    color_gui_to_int
)

from openpype.pipeline.publish import (
    PublishXmlValidationError,
    OptionalPyblishPluginMixin,
)


class RepairNukeWriteNodeAction(pyblish.api.Action):
    label = "Repair"
    on = "failed"
    icon = "wrench"

    def process(self, context, plugin):
        instances = get_errored_instances_from_context(context)

        for instance in instances:
            child_nodes = (
                instance.data.get("transientData", {}).get("childNodes")
                or instance
            )

            write_group_node = instance.data["transientData"]["node"]
            # get write node from inside of group
            write_node = None
            for x in child_nodes:
                if x.Class() == "Write":
                    write_node = x

            correct_data = get_write_node_template_attr(write_group_node)

            set_node_knobs_from_settings(write_node, correct_data["knobs"])

            self.log.info("Node attributes were fixed")


class ValidateNukeWriteNode(
    OptionalPyblishPluginMixin,
    pyblish.api.InstancePlugin
):
    """ Validate Write node's knobs.

    Compare knobs on write node inside the render group
    with settings. At the moment supporting only `file` knob.
    """

    order = pyblish.api.ValidatorOrder
    optional = True
    families = ["render"]
    label = "Validate write node"
    actions = [RepairNukeWriteNodeAction]
    hosts = ["nuke"]

    def process(self, instance):
        if not self.is_active(instance.data):
            return

        child_nodes = (
            instance.data.get("transientData", {}).get("childNodes")
            or instance
        )

        write_group_node = instance.data["transientData"]["node"]

        # get write node from inside of group
        write_node = None
        for x in child_nodes:
            if x.Class() == "Write":
                write_node = x

        if write_node is None:
            return

        correct_data = get_write_node_template_attr(write_group_node)

        check = []
        self.log.debug("__ write_node: {}".format(
            write_node
        ))
        self.log.debug("__ correct_data: {}".format(
            correct_data
        ))

        for knob_data in correct_data["knobs"]:
            knob_type = knob_data["type"]
            self.log.debug("__ knob_type: {}".format(
                knob_type
            ))

            if (
                knob_type == "__legacy__"
            ):
                raise PublishXmlValidationError(
                    self, (
                        "Please update data in settings 'project_settings"
                        "/nuke/imageio/nodes/requiredNodes'"
                    ),
                    key="legacy"
                )

            key = knob_data["name"]
            value = knob_data["value"]
            node_value = write_node[key].value()

            # fix type differences
            if type(node_value) in (int, float):
                try:
                    if isinstance(value, list):
                        value = color_gui_to_int(value)
                    else:
                        value = float(value)
                        node_value = float(node_value)
                except ValueError:
                    value = str(value)
            else:
                value = str(value)
                node_value = str(node_value)

            self.log.debug("__ key: {} | value: {}".format(
                key, value
            ))
            if (
                node_value != value
                and key != "file"
                and key != "tile_color"
            ):
                check.append([key, value, write_node[key].value()])

        self.log.info(check)

        if check:
            self._make_error(check)

    def _make_error(self, check):
        # sourcery skip: merge-assign-and-aug-assign, move-assign-in-block
        dbg_msg = "Write node's knobs values are not correct!\n"
        msg_add = "Knob '{0}' > Correct: `{1}` > Wrong: `{2}`"

        details = [
            msg_add.format(item[0], item[1], item[2])
            for item in check
        ]
        xml_msg = "<br/>".join(details)
        dbg_msg += "\n\t".join(details)

        raise PublishXmlValidationError(
            self, dbg_msg, formatting_data={"xml_msg": xml_msg}
        )
