import os
import re
from pprint import pformat
import nuke
import pyblish.api

from openpype.client import (
    get_last_version_by_subset_name,
    get_representations,
)
from openpype.pipeline import (
    legacy_io,
    get_representation_path,
)


@pyblish.api.log
class CollectNukeWrites(pyblish.api.InstancePlugin):
    """Collect all write nodes."""

    order = pyblish.api.CollectorOrder - 0.48
    label = "Pre-collect Writes"
    hosts = ["nuke", "nukeassist"]
    families = ["write"]

    def process(self, instance):
        _families_test = [instance.data["family"]] + instance.data["families"]
        self.log.debug("_families_test: {}".format(_families_test))

        node = None
        for x in instance:
            if x.Class() == "Write" and x.name().startswith("inside_"):
                node = x

        if node is None:
            return

        instance.data["writeNode"] = node
        self.log.debug("checking instance: {}".format(instance))

        # Determine defined file type
        ext = node["file_type"].value()

        # Determine output type
        output_type = "img"
        if ext == "mov":
            output_type = "mov"

        # Get frame range
        handle_start = instance.context.data["handleStart"]
        handle_end = instance.context.data["handleEnd"]
        first_frame = int(nuke.root()["first_frame"].getValue())
        last_frame = int(nuke.root()["last_frame"].getValue())
        frame_length = int(last_frame - first_frame + 1)

        if node["use_limit"].getValue():
            first_frame = int(node["first"].getValue())
            last_frame = int(node["last"].getValue())

        # Prepare expected output paths by evaluating each frame of write node
        #   - paths are first collected to set to avoid duplicated paths, then
        #       sorted and converted to list
        node_file = node["file"]
        expected_paths = list(sorted({
            node_file.evaluate(frame)
            for frame in range(first_frame, last_frame + 1)
        }))
        expected_filenames = [
            os.path.basename(filepath)
            for filepath in expected_paths
        ]
        path = nuke.filename(node)
        output_dir = os.path.dirname(path)

        self.log.debug('output dir: {}'.format(output_dir))

        # create label
        name = node.name()
        # Include start and end render frame in label
        label = "{0} ({1}-{2})".format(
            name,
            int(first_frame),
            int(last_frame)
        )

        if [fm for fm in _families_test
                if fm in ["render", "prerender", "still"]]:
            if "representations" not in instance.data:
                instance.data["representations"] = list()

            representation = {
                'name': ext,
                'ext': ext,
                "stagingDir": output_dir,
                "tags": list()
            }

            try:
                collected_frames = [
                    filename
                    for filename in os.listdir(output_dir)
                    if filename in expected_filenames
                ]
                if collected_frames:
                    collected_frames_len = len(collected_frames)
                    frame_start_str = "%0{}d".format(
                        len(str(last_frame))) % first_frame
                    representation['frameStart'] = frame_start_str

                    # in case slate is expected and not yet rendered
                    self.log.debug("_ frame_length: {}".format(frame_length))
                    self.log.debug(
                        "_ collected_frames_len: {}".format(
                            collected_frames_len))
                    # this will only run if slate frame is not already
                    # rendered from previews publishes
                    if "slate" in _families_test \
                            and (frame_length == collected_frames_len) \
                            and ("prerender" not in _families_test):
                        frame_slate_str = "%0{}d".format(
                            len(str(last_frame))) % (first_frame - 1)
                        slate_frame = collected_frames[0].replace(
                            frame_start_str, frame_slate_str)
                        collected_frames.insert(0, slate_frame)

                if collected_frames_len == 1:
                    representation['files'] = collected_frames.pop()
                    if "still" in _families_test:
                        instance.data['family'] = 'image'
                        instance.data["families"].remove('still')
                else:
                    representation['files'] = collected_frames
                instance.data["representations"].append(representation)
            except Exception:
                instance.data["representations"].append(representation)
                self.log.debug("couldn't collect frames: {}".format(label))

        # Add version data to instance
        colorspace = node["colorspace"].value()

        # remove default part of the string
        if "default (" in colorspace:
            colorspace = re.sub(r"default.\(|\)", "", colorspace)
            self.log.debug("colorspace: `{}`".format(colorspace))

        version_data = {
            "families": [
                _f.replace(".local", "").replace(".farm", "")
                for _f in _families_test if "write" != _f
            ],
            "colorspace": colorspace
        }

        group_node = [x for x in instance if x.Class() == "Group"][0]
        dl_chunk_size = 1
        if "deadlineChunkSize" in group_node.knobs():
            dl_chunk_size = group_node["deadlineChunkSize"].value()

        dl_priority = 50
        if "deadlinePriority" in group_node.knobs():
            dl_priority = group_node["deadlinePriority"].value()

        dl_concurrent_tasks = 0
        if "deadlineConcurrentTasks" in group_node.knobs():
            dl_concurrent_tasks = group_node["deadlineConcurrentTasks"].value()

        instance.data.update({
            "versionData": version_data,
            "path": path,
            "outputDir": output_dir,
            "ext": ext,
            "label": label,
            "outputType": output_type,
            "colorspace": colorspace,
            "deadlineChunkSize": dl_chunk_size,
            "deadlinePriority": dl_priority,
            "deadlineConcurrentTasks": dl_concurrent_tasks
        })

        if self.is_prerender(_families_test):
            instance.data.update({
                "handleStart": 0,
                "handleEnd": 0,
                "frameStart": first_frame,
                "frameEnd": last_frame,
                "frameStartHandle": first_frame,
                "frameEndHandle": last_frame,
            })
        else:
            instance.data.update({
                "handleStart": handle_start,
                "handleEnd": handle_end,
                "frameStart": first_frame + handle_start,
                "frameEnd": last_frame - handle_end,
                "frameStartHandle": first_frame,
                "frameEndHandle": last_frame,
            })

            # make sure rendered sequence on farm will
            # be used for exctract review
            if not instance.data["review"]:
                instance.data["useSequenceForReview"] = False

        self.log.debug("instance.data: {}".format(pformat(instance.data)))

    def is_prerender(self, families):
        return next((f for f in families if "prerender" in f), None)
