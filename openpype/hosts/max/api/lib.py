# -*- coding: utf-8 -*-
"""Library of functions useful for 3dsmax pipeline."""
import json
import six
from pymxs import runtime as rt
from typing import Union
import contextlib

from openpype.pipeline.context_tools import (
    get_current_project_asset,
    get_current_project
)


JSON_PREFIX = "JSON::"


def imprint(node_name: str, data: dict) -> bool:
    node = rt.getNodeByName(node_name)
    if not node:
        return False

    for k, v in data.items():
        if isinstance(v, (dict, list)):
            rt.setUserProp(node, k, f'{JSON_PREFIX}{json.dumps(v)}')
        else:
            rt.setUserProp(node, k, v)

    return True


def lsattr(
        attr: str,
        value: Union[str, None] = None,
        root: Union[str, None] = None) -> list:
    """List nodes having attribute with specified value.

    Args:
        attr (str): Attribute name to match.
        value (str, Optional): Value to match, of omitted, all nodes
            with specified attribute are returned no matter of value.
        root (str, Optional): Root node name. If omitted, scene root is used.

    Returns:
        list of nodes.
    """
    root = rt.rootnode if root is None else rt.getNodeByName(root)

    def output_node(node, nodes):
        nodes.append(node)
        for child in node.Children:
            output_node(child, nodes)

    nodes = []
    output_node(root, nodes)
    return [
        n for n in nodes
        if rt.getUserProp(n, attr) == value
    ] if value else [
        n for n in nodes
        if rt.getUserProp(n, attr)
    ]


def read(container) -> dict:
    data = {}
    props = rt.getUserPropBuffer(container)
    # this shouldn't happen but let's guard against it anyway
    if not props:
        return data

    for line in props.split("\r\n"):
        try:
            key, value = line.split("=")
        except ValueError:
            # if the line cannot be split we can't really parse it
            continue

        value = value.strip()
        if isinstance(value.strip(), six.string_types) and \
                value.startswith(JSON_PREFIX):
            try:
                value = json.loads(value[len(JSON_PREFIX):])
            except json.JSONDecodeError:
                # not a json
                pass

        data[key.strip()] = value

    data["instance_node"] = container.name

    return data


@contextlib.contextmanager
def maintained_selection():
    previous_selection = rt.getCurrentSelection()
    try:
        yield
    finally:
        if previous_selection:
            rt.select(previous_selection)
        else:
            rt.select()


def get_all_children(parent, node_type=None):
    """Handy function to get all the children of a given node

    Args:
        parent (3dsmax Node1): Node to get all children of.
        node_type (None, runtime.class): give class to check for
            e.g. rt.FFDBox/rt.GeometryClass etc.

    Returns:
        list: list of all children of the parent node
    """
    def list_children(node):
        children = []
        for c in node.Children:
            children.append(c)
            children = children + list_children(c)
        return children
    child_list = list_children(parent)

    return ([x for x in child_list if rt.superClassOf(x) == node_type]
            if node_type else child_list)


def get_current_renderer():
    """get current renderer"""
    return rt.renderers.production


def get_default_render_folder(project_setting=None):
    return (project_setting["max"]
                           ["RenderSettings"]
                           ["default_render_image_folder"])


def set_framerange(start_frame, end_frame):
    """
    Note:
        Frame range can be specified in different types. Possible values are:
        * `1` - Single frame.
        * `2` - Active time segment ( animationRange ).
        * `3` - User specified Range.
        * `4` - User specified Frame pickup string (for example `1,3,5-12`).

    Todo:
        Current type is hard-coded, there should be a custom setting for this.
    """
    rt.rendTimeType = 4
    if start_frame is not None and end_frame is not None:
        frame_range = "{0}-{1}".format(start_frame, end_frame)
        rt.rendPickupFrames = frame_range


def get_multipass_setting(project_setting=None):
    return (project_setting["max"]
                           ["RenderSettings"]
                           ["multipass"])


def set_scene_resolution(width: int, height: int):
    """Set the render resolution

    Args:
        width(int): value of the width
        height(int): value of the height

    Returns:
        None

    """
    rt.renderWidth = width
    rt.renderHeight = height


def reset_scene_resolution():
    """Apply the scene resolution from the project definition

    scene resolution can be overwritten by an asset if the asset.data contains
    any information regarding scene resolution .
    Returns:
        None
    """
    data = ["data.resolutionWidth", "data.resolutionHeight"]
    project_resolution = get_current_project(fields=data)
    project_resolution_data = project_resolution["data"]
    asset_resolution = get_current_project_asset(fields=data)
    asset_resolution_data = asset_resolution["data"]
    # Set project resolution
    project_width = int(project_resolution_data.get("resolutionWidth", 1920))
    project_height = int(project_resolution_data.get("resolutionHeight", 1080))
    width = int(asset_resolution_data.get("resolutionWidth", project_width))
    height = int(asset_resolution_data.get("resolutionHeight", project_height))

    set_scene_resolution(width, height)


def get_frame_range() -> dict:
    """Get the current assets frame range and handles.

    Returns:
        dict: with frame start, frame end, handle start, handle end.
    """
    # Set frame start/end
    asset = get_current_project_asset()
    frame_start = asset["data"].get("frameStart")
    frame_end = asset["data"].get("frameEnd")

    if frame_start is None or frame_end is None:
        return

    handle_start = asset["data"].get("handleStart", 0)
    handle_end = asset["data"].get("handleEnd", 0)
    return {
        "frameStart": frame_start,
        "frameEnd": frame_end,
        "handleStart": handle_start,
        "handleEnd": handle_end
    }


def reset_frame_range(fps: bool = True):
    """Set frame range to current asset.
    This is part of 3dsmax documentation:

    animationRange: A System Global variable which lets you get and
        set an Interval value that defines the start and end frames
        of the Active Time Segment.
    frameRate: A System Global variable which lets you get
            and set an Integer value that defines the current
            scene frame rate in frames-per-second.
    """
    if fps:
        data_fps = get_current_project(fields=["data.fps"])
        fps_number = float(data_fps["data"]["fps"])
        rt.frameRate = fps_number
    frame_range = get_frame_range()
    frame_start = frame_range["frameStart"] - int(frame_range["handleStart"])
    frame_end = frame_range["frameEnd"] + int(frame_range["handleEnd"])
    frange_cmd = f"animationRange = interval {frame_start} {frame_end}"
    rt.execute(frange_cmd)


def set_context_setting():
    """Apply the project settings from the project definition

    Settings can be overwritten by an asset if the asset.data contains
    any information regarding those settings.

    Examples of settings:
        frame range
        resolution

    Returns:
        None
    """
    reset_scene_resolution()


def get_max_version():
    """
    Args:
    get max version date for deadline

    Returns:
        #(25000, 62, 0, 25, 0, 0, 997, 2023, "")
        max_info[7] = max version date
    """
    max_info = rt.maxversion()
    return max_info[7]
