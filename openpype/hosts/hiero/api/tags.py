import json
import re
import os
import hiero

from openpype.client import get_project, get_assets
from openpype.lib import Logger
from openpype.pipeline import legacy_io

log = Logger.get_logger(__name__)


def tag_data():
    return {
        "[Lenses]": {
            "Set lense here": {
                "editable": "1",
                "note": "Adjust parameters of your lense and then drop to clip. Remember! You can always overwrite on clip",  # noqa
                "icon": "lense.png",
                "metadata": {
                    "focalLengthMm": 57

                }
            }
        },
        # "NukeScript": {
        #     "editable": "1",
        #     "note": "Collecting track items to Nuke scripts.",
        #     "icon": "icons:TagNuke.png",
        #     "metadata": {
        #         "family": "nukescript",
        #         "subset": "main"
        #     }
        # },
        "Comment": {
            "editable": "1",
            "note": "Comment on a shot.",
            "icon": "icons:TagComment.png",
            "metadata": {
                "family": "comment",
                "subset": "main"
            }
        },
        "FrameMain": {
            "editable": "1",
            "note": "Publishing a frame subset.",
            "icon": "z_layer_main.png",
            "metadata": {
                "family": "frame",
                "subset": "main",
                "format": "png"
            }
        }
    }


def create_tag(key, data):
    """
    Creating Tag object.

    Args:
        key (str): name of tag
        data (dict): parameters of tag

    Returns:
        object: Tag object
    """
    tag = hiero.core.Tag(str(key))
    return update_tag(tag, data)


def update_tag(tag, data):
    """
    Fixing Tag object.

    Args:
        tag (obj): Tag object
        data (dict): parameters of tag
    """
    # set icon if any available in input data
    if data.get("icon"):
        tag.setIcon(str(data["icon"]))

    # get metadata of tag
    mtd = tag.metadata()
    # get metadata key from data
    data_mtd = data.get("metadata", {})

    # set all data metadata to tag metadata
    for _k, _v in data_mtd.items():
        value = str(_v)
        if type(_v) == dict:
            value = json.dumps(_v)

        # set the value
        mtd.setValue(
            "tag.{}".format(str(_k)),
            value
        )

    # set note description of tag
    tag.setNote(str(data["note"]))
    return tag


def add_tags_to_workfile():
    """
    Will create default tags from presets.
    """
    from .lib import get_current_project

    def add_tag_to_bin(root_bin, name, data):
        # for Tags to be created in root level Bin
        # at first check if any of input data tag is not already created
        done_tag = next((t for t in root_bin.items()
                        if str(name) in t.name()), None)

        if not done_tag:
            # create Tag
            tag = create_tag(name, data)
            tag.setName(str(name))

            log.debug("__ creating tag: {}".format(tag))
            # adding Tag to Root Bin
            root_bin.addItem(tag)
        else:
            # update only non hierarchy tags
            update_tag(done_tag, data)
            done_tag.setName(str(name))
            log.debug("__ updating tag: {}".format(done_tag))

    # get project and root bin object
    project = get_current_project()
    root_bin = project.tagsBin()

    if "Tag Presets" in project.name():
        return

    log.debug("Setting default tags on project: {}".format(project.name()))

    # get hiero tags.json
    nks_pres_tags = tag_data()

    # Get project task types.
    project_name = legacy_io.active_project()
    project_doc = get_project(project_name)
    tasks = project_doc["config"]["tasks"]
    nks_pres_tags["[Tasks]"] = {}
    log.debug("__ tasks: {}".format(tasks))
    for task_type in tasks.keys():
        nks_pres_tags["[Tasks]"][task_type.lower()] = {
            "editable": "1",
            "note": task_type,
            "icon": "icons:TagGood.png",
            "metadata": {
                "family": "task",
                "type": task_type
            }
        }

    # Get project assets. Currently Ftrack specific to differentiate between
    # asset builds and shots.
    if int(os.getenv("TAG_ASSETBUILD_STARTUP", 0)) == 1:
        nks_pres_tags["[AssetBuilds]"] = {}
        for asset in get_assets(
            project_name, fields=["name", "data.entityType"]
        ):
            if asset["data"]["entityType"] == "AssetBuild":
                nks_pres_tags["[AssetBuilds]"][asset["name"]] = {
                    "editable": "1",
                    "note": "",
                    "icon": {
                        "path": "icons:TagActor.png"
                    },
                    "metadata": {
                        "family": "assetbuild"
                    }
                }

    # loop through tag data dict and create deep tag structure
    for _k, _val in nks_pres_tags.items():
        # check if key is not decorated with [] so it is defined as bin
        bin_find = None
        pattern = re.compile(r"\[(.*)\]")
        _bin_finds = pattern.findall(_k)
        # if there is available any then pop it to string
        if _bin_finds:
            bin_find = _bin_finds.pop()

        # if bin was found then create or update
        if bin_find:
            root_add = False
            # first check if in root lever is not already created bins
            bins = [b for b in root_bin.items()
                    if b.name() in str(bin_find)]

            if bins:
                bin = bins.pop()
            else:
                root_add = True
                # create Bin object for processing
                bin = hiero.core.Bin(str(bin_find))

            # update or create tags in the bin
            for __k, __v in _val.items():
                add_tag_to_bin(bin, __k, __v)

            # finally add the Bin object to the root level Bin
            if root_add:
                # adding Tag to Root Bin
                root_bin.addItem(bin)
        else:
            add_tag_to_bin(root_bin, _k, _val)

    log.info("Default Tags were set...")
