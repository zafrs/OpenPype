import nuke

from openpype.hosts.nuke.api import plugin
from openpype.hosts.nuke.api.lib import create_write_node


class CreateWriteStill(plugin.AbstractWriteRender):
    # change this to template preset
    name = "WriteStillFrame"
    label = "Create Write Still Image"
    hosts = ["nuke"]
    n_class = "Write"
    family = "still"
    icon = "image"
    defaults = [
        "imageFrame{:0>4}".format(nuke.frame()),
        "MPFrame{:0>4}".format(nuke.frame()),
        "layoutFrame{:0>4}".format(nuke.frame()),
        "lightingFrame{:0>4}".format(nuke.frame()),
        "mattePaintFrame{:0>4}".format(nuke.frame()),
        "fxFrame{:0>4}".format(nuke.frame()),
        "compositingFrame{:0>4}".format(nuke.frame()),
        "animationFrame{:0>4}".format(nuke.frame())
    ]

    def __init__(self, *args, **kwargs):
        super(CreateWriteStill, self).__init__(*args, **kwargs)

    def _create_write_node(self, selected_node, inputs, outputs, write_data):
        # explicitly reset template to 'renders', not same as other 2 writes
        write_data.update({
            # "fpath_template": (
            #     "{work}/renders/nuke/{subset}/{subset}.{ext}")})
            "fpath_template": (
                "{work}/render/{subset}/{subset}.{ext}")})

        _prenodes = [
            {
                "name": "FrameHold01",
                "class": "FrameHold",
                "knobs": [
                    ("first_frame", nuke.frame())
                ],
                "dependent": None
            }
        ]

        write_node = create_write_node(
            self.name,
            write_data,
            input=selected_node,
            review=False,
            prenodes=_prenodes,
            farm=False,
            linked_knobs=["channels", "___", "first", "last", "use_limit"])

        return write_node

    def _modify_write_node(self, write_node):
        write_node.begin()
        for n in nuke.allNodes():
            # get write node
            if n.Class() in "Write":
                w_node = n
        write_node.end()

        w_node["use_limit"].setValue(True)
        w_node["first"].setValue(nuke.frame())
        w_node["last"].setValue(nuke.frame())

        return write_node
