import os
import re
import pyblish.api
import openpype
from openpype.hosts.nuke.api import plugin
from openpype.hosts.nuke.api.lib import maintained_selection


class ExtractReviewDataMov(openpype.api.Extractor):
    """Extracts movie and thumbnail with baked in luts

    must be run after extract_render_local.py

    """

    order = pyblish.api.ExtractorOrder + 0.01
    label = "Extract Review Data Mov"

    families = ["review"]
    hosts = ["nuke"]

    # presets
    viewer_lut_raw = None
    outputs = {}

    def process(self, instance):
        families = instance.data["families"]
        task_type = instance.context.data["taskType"]
        subset = instance.data["subset"]
        self.log.info("Creating staging dir...")

        if "representations" not in instance.data:
            instance.data["representations"] = []

        staging_dir = os.path.normpath(
            os.path.dirname(instance.data["path"]))

        instance.data["stagingDir"] = staging_dir

        self.log.info(
            "StagingDir `{0}`...".format(instance.data["stagingDir"]))

        self.log.info(self.outputs)

        # generate data
        with maintained_selection():
            generated_repres = []
            for o_name, o_data in self.outputs.items():
                f_families = o_data["filter"]["families"]
                f_task_types = o_data["filter"]["task_types"]
                f_subsets = o_data["filter"]["sebsets"]

                # test if family found in context
                test_families = any([
                    # first if exact family set is matching
                    # make sure only interesetion of list is correct
                    bool(set(families).intersection(f_families)),
                    # and if famiies are set at all
                    # if not then return True because we want this preset
                    # to be active if nothig is set
                    bool(not f_families)
                ])

                # test task types from filter
                test_task_types = any([
                    # check if actual task type is defined in task types
                    # set in preset's filter
                    bool(task_type in f_task_types),
                    # and if taskTypes are defined in preset filter
                    # if not then return True, because we want this filter
                    # to be active if no taskType is set
                    bool(not f_task_types)
                ])

                # test subsets from filter
                test_subsets = any([
                    # check if any of subset filter inputs
                    # converted to regex patern is not found in subset
                    # we keep strict case sensitivity
                    bool(next((
                        s for s in f_subsets
                        if re.search(re.compile(s), subset)
                    ), None)),
                    # but if no subsets were set then make this acuntable too
                    bool(not f_subsets)
                ])

                # we need all filters to be positive for this
                # preset to be activated
                test_all = all([
                    test_families,
                    test_task_types,
                    test_subsets
                ])

                # if it is not positive then skip this preset
                if not test_all:
                    continue

                self.log.info(
                    "Baking output `{}` with settings: {}".format(
                        o_name, o_data))

                # check if settings have more then one preset
                # so we dont need to add outputName to representation
                # in case there is only one preset
                multiple_presets = bool(len(self.outputs.keys()) > 1)

                # create exporter instance
                exporter = plugin.ExporterReviewMov(
                    self, instance, o_name, o_data["extension"],
                    multiple_presets)

                if "render.farm" in families:
                    if "review" in instance.data["families"]:
                        instance.data["families"].remove("review")

                    data = exporter.generate_mov(farm=True, **o_data)

                    self.log.debug(
                        "_ data: {}".format(data))

                    if not instance.data.get("bakingNukeScripts"):
                        instance.data["bakingNukeScripts"] = []

                    instance.data["bakingNukeScripts"].append({
                        "bakeRenderPath": data.get("bakeRenderPath"),
                        "bakeScriptPath": data.get("bakeScriptPath"),
                        "bakeWriteNodeName": data.get("bakeWriteNodeName")
                    })
                else:
                    data = exporter.generate_mov(**o_data)
                    generated_repres.extend(data["representations"])

                self.log.info(generated_repres)

        if generated_repres:
            # assign to representations
            instance.data["representations"] += generated_repres
        else:
            instance.data["families"].remove("review")
            self.log.info((
                "Removing `review` from families. "
                "Not available baking profile."
            ))
            self.log.debug(instance.data["families"])

        self.log.debug(
            "_ representations: {}".format(
                instance.data["representations"]))
