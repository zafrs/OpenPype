import os
import re
import tempfile
from copy import deepcopy

import pyblish.api

from openpype.pipeline import publish
from openpype.hosts.flame import api as opfapi
from openpype.hosts.flame.api import MediaInfoFile
from openpype.pipeline.editorial import (
    get_media_range_with_retimes
)

import flame


class ExtractSubsetResources(publish.Extractor):
    """
    Extractor for transcoding files from Flame clip
    """

    label = "Extract subset resources"
    order = pyblish.api.ExtractorOrder
    families = ["clip"]
    hosts = ["flame"]

    # plugin defaults
    keep_original_representation = False

    default_presets = {
        "thumbnail": {
            "active": True,
            "ext": "jpg",
            "xml_preset_file": "Jpeg (8-bit).xml",
            "xml_preset_dir": "",
            "export_type": "File Sequence",
            "parsed_comment_attrs": False,
            "colorspace_out": "Output - sRGB",
            "representation_add_range": False,
            "representation_tags": ["thumbnail"],
            "path_regex": ".*"
        }
    }

    # hide publisher during exporting
    hide_ui_on_process = True

    # settings
    export_presets_mapping = {}

    def process(self, instance):
        if not self.keep_original_representation:
            # remove previeous representation if not needed
            instance.data["representations"] = []

        # flame objects
        segment = instance.data["item"]
        asset_name = instance.data["asset"]
        segment_name = segment.name.get_value()
        clip_path = instance.data["path"]
        sequence_clip = instance.context.data["flameSequence"]

        # segment's parent track name
        s_track_name = segment.parent.name.get_value()

        # get configured workfile frame start/end (handles excluded)
        frame_start = instance.data["frameStart"]
        # get media source first frame
        source_first_frame = instance.data["sourceFirstFrame"]

        self.log.debug("_ frame_start: {}".format(frame_start))
        self.log.debug("_ source_first_frame: {}".format(source_first_frame))

        # get timeline in/out of segment
        clip_in = instance.data["clipIn"]
        clip_out = instance.data["clipOut"]

        # get retimed attributres
        retimed_data = self._get_retimed_attributes(instance)

        # get individual keys
        retimed_handle_start = retimed_data["handle_start"]
        retimed_handle_end = retimed_data["handle_end"]
        retimed_source_duration = retimed_data["source_duration"]
        retimed_speed = retimed_data["speed"]

        # get handles value - take only the max from both
        handle_start = instance.data["handleStart"]
        handle_end = instance.data["handleEnd"]
        handles = max(handle_start, handle_end)
        include_handles = instance.data.get("includeHandles")
        retimed_handles = instance.data.get("retimedHandles")

        # get media source range with handles
        source_start_handles = instance.data["sourceStartH"]
        source_end_handles = instance.data["sourceEndH"]

        # retime if needed
        if retimed_speed != 1.0:
            if retimed_handles:
                # handles are retimed
                source_start_handles = (
                    instance.data["sourceStart"] - retimed_handle_start)
                source_end_handles = (
                    source_start_handles
                    + (retimed_source_duration - 1)
                    + retimed_handle_start
                    + retimed_handle_end
                )

            else:
                # handles are not retimed
                source_end_handles = (
                    source_start_handles
                    + (retimed_source_duration - 1)
                    + handle_start
                    + handle_end
                )

        # get frame range with handles for representation range
        frame_start_handle = frame_start - handle_start
        repre_frame_start = frame_start_handle
        if include_handles:
            if retimed_speed == 1.0 or not retimed_handles:
                frame_start_handle = frame_start
            else:
                frame_start_handle = (
                    frame_start - handle_start) + retimed_handle_start

        self.log.debug("_ frame_start_handle: {}".format(
            frame_start_handle))
        self.log.debug("_ repre_frame_start: {}".format(
            repre_frame_start))

        # calculate duration with handles
        source_duration_handles = (
            source_end_handles - source_start_handles) + 1

        self.log.debug("_ source_duration_handles: {}".format(
            source_duration_handles))

        # create staging dir path
        staging_dir = self.staging_dir(instance)

        # append staging dir for later cleanup
        instance.context.data["cleanupFullPaths"].append(staging_dir)

        # add default preset type for thumbnail and reviewable video
        # update them with settings and override in case the same
        # are found in there
        _preset_keys = [k.split('_')[0] for k in self.export_presets_mapping]
        export_presets = {
            k: v for k, v in deepcopy(self.default_presets).items()
            if k not in _preset_keys
        }
        export_presets.update(self.export_presets_mapping)

        if not instance.data.get("versionData"):
            instance.data["versionData"] = {}

        # set versiondata if any retime
        version_data = retimed_data.get("version_data")
        self.log.debug("_ version_data: {}".format(version_data))

        if version_data:
            instance.data["versionData"].update(version_data)

        # version data start frame
        version_frame_start = frame_start
        if include_handles:
            version_frame_start = frame_start_handle
        if retimed_speed != 1.0:
            if retimed_handles:
                instance.data["versionData"].update({
                    "frameStart": version_frame_start,
                    "frameEnd": (
                        (version_frame_start + source_duration_handles - 1)
                        - (retimed_handle_start + retimed_handle_end)
                    )
                })
            else:
                instance.data["versionData"].update({
                    "handleStart": handle_start,
                    "handleEnd": handle_end,
                    "frameStart": version_frame_start,
                    "frameEnd": (
                        (version_frame_start + source_duration_handles - 1)
                        - (handle_start + handle_end)
                    )
                })
        self.log.debug("_ version_data: {}".format(
            instance.data["versionData"]
        ))

        # loop all preset names and
        for unique_name, preset_config in export_presets.items():
            modify_xml_data = {}

            if self._should_skip(preset_config, clip_path, unique_name):
                continue

            # get all presets attributes
            extension = preset_config["ext"]
            preset_file = preset_config["xml_preset_file"]
            preset_dir = preset_config["xml_preset_dir"]
            export_type = preset_config["export_type"]
            repre_tags = preset_config["representation_tags"]
            parsed_comment_attrs = preset_config["parsed_comment_attrs"]
            color_out = preset_config["colorspace_out"]

            self.log.info(
                "Processing `{}` as `{}` to `{}` type...".format(
                    preset_file, export_type, extension
                )
            )

            exporting_clip = None
            name_patern_xml = "<name>_{}.".format(
                unique_name)

            if export_type == "Sequence Publish":
                # change export clip to sequence
                exporting_clip = flame.duplicate(sequence_clip)

                # only keep visible layer where instance segment is child
                self.hide_others(
                    exporting_clip, segment_name, s_track_name)

                # change name pattern
                name_patern_xml = (
                    "<segment name>_<shot name>_{}.").format(
                        unique_name)

                # only for h264 with baked retime
                in_mark = clip_in
                out_mark = clip_out + 1
                modify_xml_data.update({
                    "exportHandles": True,
                    "nbHandles": handles
                })
            else:
                in_mark = (source_start_handles - source_first_frame) + 1
                out_mark = in_mark + source_duration_handles
                exporting_clip = self.import_clip(clip_path)
                exporting_clip.name.set_value("{}_{}".format(
                    asset_name, segment_name))

            # add xml tags modifications
            modify_xml_data.update({
                # enum position low start from 0
                "frameIndex": 0,
                "startFrame": repre_frame_start,
                "namePattern": name_patern_xml
            })

            if parsed_comment_attrs:
                # add any xml overrides collected form segment.comment
                modify_xml_data.update(instance.data["xml_overrides"])

            self.log.debug("_ in_mark: {}".format(in_mark))
            self.log.debug("_ out_mark: {}".format(out_mark))

            export_kwargs = {}
            # validate xml preset file is filled
            if preset_file == "":
                raise ValueError(
                    ("Check Settings for {} preset: "
                        "`XML preset file` is not filled").format(
                        unique_name)
                )

            # resolve xml preset dir if not filled
            if preset_dir == "":
                preset_dir = opfapi.get_preset_path_by_xml_name(
                    preset_file)

                if not preset_dir:
                    raise ValueError(
                        ("Check Settings for {} preset: "
                            "`XML preset file` {} is not found").format(
                            unique_name, preset_file)
                    )

            # create preset path
            preset_orig_xml_path = str(os.path.join(
                preset_dir, preset_file
            ))

            # define kwargs based on preset type
            if "thumbnail" in unique_name:
                modify_xml_data.update({
                    "video/posterFrame": True,
                    "video/useFrameAsPoster": 1,
                    "namePattern": "__thumbnail"
                })
                thumb_frame_number = int(in_mark + (
                    (out_mark - in_mark + 1) / 2))

                self.log.debug("__ thumb_frame_number: {}".format(
                    thumb_frame_number
                ))

                export_kwargs["thumb_frame_number"] = thumb_frame_number
            else:
                export_kwargs.update({
                    "in_mark": in_mark,
                    "out_mark": out_mark
                })

            preset_path = opfapi.modify_preset_file(
                preset_orig_xml_path, staging_dir, modify_xml_data)

            # get and make export dir paths
            export_dir_path = str(os.path.join(
                staging_dir, unique_name
            ))
            os.makedirs(export_dir_path)

            # export
            opfapi.export_clip(
                export_dir_path, exporting_clip, preset_path, **export_kwargs)

            repr_name = unique_name
            # make sure only first segment is used if underscore in name
            # HACK: `ftrackreview_withLUT` will result only in `ftrackreview`
            if (
                "thumbnail" in unique_name
                or "ftrackreview" in unique_name
            ):
                repr_name = unique_name.split("_")[0]

            # create representation data
            representation_data = {
                "name": repr_name,
                "outputName": repr_name,
                "ext": extension,
                "stagingDir": export_dir_path,
                "tags": repre_tags,
                "data": {
                    "colorspace": color_out
                },
                "load_to_batch_group": preset_config.get(
                    "load_to_batch_group"),
                "batch_group_loader_name": preset_config.get(
                    "batch_group_loader_name") or None
            }

            # collect all available content of export dir
            files = os.listdir(export_dir_path)

            # make sure no nested folders inside
            n_stage_dir, n_files = self._unfolds_nested_folders(
                export_dir_path, files, extension)

            # fix representation in case of nested folders
            if n_stage_dir:
                representation_data["stagingDir"] = n_stage_dir
                files = n_files

            # add files to representation but add
            # imagesequence as list
            if (
                # first check if path in files is not mov extension
                [
                    f for f in files
                    if os.path.splitext(f)[-1] == ".mov"
                ]
                # then try if thumbnail is not in unique name
                or repr_name == "thumbnail"
            ):
                representation_data["files"] = files.pop()
            else:
                representation_data["files"] = files

            # add frame range
            if preset_config["representation_add_range"]:
                representation_data.update({
                    "frameStart": repre_frame_start,
                    "frameEnd": (
                        repre_frame_start + source_duration_handles) - 1,
                    "fps": instance.data["fps"]
                })

            instance.data["representations"].append(representation_data)

            # add review family if found in tags
            if "review" in repre_tags:
                instance.data["families"].append("review")

            self.log.info("Added representation: {}".format(
                representation_data))

            if export_type == "Sequence Publish":
                # at the end remove the duplicated clip
                flame.delete(exporting_clip)

    def _get_retimed_attributes(self, instance):
        handle_start = instance.data["handleStart"]
        handle_end = instance.data["handleEnd"]

        # get basic variables
        otio_clip = instance.data["otioClip"]

        # get available range trimmed with processed retimes
        retimed_attributes = get_media_range_with_retimes(
            otio_clip, handle_start, handle_end)
        self.log.debug(
            ">> retimed_attributes: {}".format(retimed_attributes))

        r_media_in = int(retimed_attributes["mediaIn"])
        r_media_out = int(retimed_attributes["mediaOut"])
        version_data = retimed_attributes.get("versionData")

        return {
            "version_data": version_data,
            "handle_start": int(retimed_attributes["handleStart"]),
            "handle_end": int(retimed_attributes["handleEnd"]),
            "source_duration": (
                (r_media_out - r_media_in) + 1
            ),
            "speed": float(retimed_attributes["speed"])
        }

    def _should_skip(self, preset_config, clip_path, unique_name):
        # get activating attributes
        activated_preset = preset_config["active"]
        filter_path_regex = preset_config.get("filter_path_regex")

        self.log.info(
            "Preset `{}` is active `{}` with filter `{}`".format(
                unique_name, activated_preset, filter_path_regex
            )
        )

        # skip if not activated presete
        if not activated_preset:
            return True

        # exclude by regex filter if any
        if (
            filter_path_regex
            and not re.search(filter_path_regex, clip_path)
        ):
            return True

    def _unfolds_nested_folders(self, stage_dir, files_list, ext):
        """Unfolds nested folders

        Args:
            stage_dir (str): path string with directory
            files_list (list): list of file names
            ext (str): extension (jpg)[without dot]

        Raises:
            IOError: in case no files were collected form any directory

        Returns:
            str, list: new staging dir path, new list of file names
            or
            None, None: In case single file in `files_list`
        """
        # exclude single files which are having extension
        # the same as input ext attr
        if (
            # only one file in list
            len(files_list) == 1
            # file is having extension as input
            and ext in os.path.splitext(files_list[0])[-1]
        ):
            return None, None
        elif (
            # more then one file in list
            len(files_list) >= 1
            # extension is correct
            and ext in os.path.splitext(files_list[0])[-1]
            # test file exists
            and os.path.exists(
                os.path.join(stage_dir, files_list[0])
            )
        ):
            return None, None

        new_stage_dir = None
        new_files_list = []
        for file in files_list:
            search_path = os.path.join(stage_dir, file)
            if not os.path.isdir(search_path):
                continue
            for root, _dirs, files in os.walk(search_path):
                for _file in files:
                    _fn, _ext = os.path.splitext(_file)
                    if ext.lower() != _ext[1:].lower():
                        continue
                    new_files_list.append(_file)
                    if not new_stage_dir:
                        new_stage_dir = root

        if not new_stage_dir:
            raise AssertionError(
                "Files in `{}` are not correct! Check `{}`".format(
                    files_list, stage_dir)
            )

        return new_stage_dir, new_files_list

    def hide_others(self, sequence_clip, segment_name, track_name):
        """Helper method used only if sequence clip is used

        Args:
            sequence_clip (flame.Clip): sequence clip
            segment_name (str): segment name
            track_name (str): track name
        """
        # create otio tracks and clips
        for ver in sequence_clip.versions:
            for track in ver.tracks:
                if len(track.segments) == 0 and track.hidden.get_value():
                    continue

                # hide tracks which are not parent track
                if track.name.get_value() != track_name:
                    track.hidden = True
                    continue

                # hidde all other segments
                for segment in track.segments:
                    if segment.name.get_value() != segment_name:
                        segment.hidden = True

    def import_clip(self, path):
        """
        Import clip from path
        """
        dir_path = os.path.dirname(path)
        media_info = MediaInfoFile(path, logger=self.log)
        file_pattern = media_info.file_pattern
        self.log.debug("__ file_pattern: {}".format(file_pattern))

        # rejoin the pattern to dir path
        new_path = os.path.join(dir_path, file_pattern)

        clips = flame.import_clips(new_path)
        self.log.info("Clips [{}] imported from `{}`".format(clips, path))

        if not clips:
            self.log.warning("Path `{}` is not having any clips".format(path))
            return None
        elif len(clips) > 1:
            self.log.warning(
                "Path `{}` is containing more that one clip".format(path)
            )
        return clips[0]
