import pyblish.api

from openpype.client import get_asset_name_identifier
import openpype.hosts.flame.api as opfapi
from openpype.hosts.flame.otio import flame_export
from openpype.pipeline.create import get_subset_name


class CollecTimelineOTIO(pyblish.api.ContextPlugin):
    """Inject the current working context into publish context"""

    label = "Collect Timeline OTIO"
    order = pyblish.api.CollectorOrder - 0.099

    def process(self, context):
        # plugin defined
        family = "workfile"
        variant = "otioTimeline"

        # main
        asset_doc = context.data["assetEntity"]
        task_name = context.data["task"]
        project = opfapi.get_current_project()
        sequence = opfapi.get_current_sequence(opfapi.CTX.selection)

        # create subset name
        subset_name = get_subset_name(
            family,
            variant,
            task_name,
            asset_doc,
            context.data["projectName"],
            context.data["hostName"],
            project_settings=context.data["project_settings"]
        )

        asset_name = get_asset_name_identifier(asset_doc)

        # adding otio timeline to context
        with opfapi.maintained_segment_selection(sequence) as selected_seg:
            otio_timeline = flame_export.create_otio_timeline(sequence)

            instance_data = {
                "name": subset_name,
                "asset": asset_name,
                "subset": subset_name,
                "family": "workfile",
                "families": []
            }

            # create instance with workfile
            instance = context.create_instance(**instance_data)
            self.log.info("Creating instance: {}".format(instance))

            # update context with main project attributes
            context.data.update({
                "flameProject": project,
                "flameSequence": sequence,
                "otioTimeline": otio_timeline,
                "currentFile": "Flame/{}/{}".format(
                    project.name, sequence.name
                ),
                "flameSelectedSegments": selected_seg,
                "fps": float(str(sequence.frame_rate)[:-4])
            })
