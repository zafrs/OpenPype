"""Collect Anatomy and global anatomy data.

Requires:
    session -> AVALON_PROJECT, AVALON_ASSET

Provides:
    context -> projectEntity - project entity from database
    context -> assetEntity - asset entity from database
"""

import pyblish.api

from openpype.pipeline import legacy_io


class CollectAvalonEntities(pyblish.api.ContextPlugin):
    """Collect Anatomy into Context"""

    order = pyblish.api.CollectorOrder - 0.1
    label = "Collect Avalon Entities"

    def process(self, context):
        legacy_io.install()
        project_name = legacy_io.Session["AVALON_PROJECT"]
        asset_name = legacy_io.Session["AVALON_ASSET"]
        task_name = legacy_io.Session["AVALON_TASK"]

        project_entity = legacy_io.find_one({
            "type": "project",
            "name": project_name
        })
        assert project_entity, (
            "Project '{0}' was not found."
        ).format(project_name)
        self.log.debug("Collected Project \"{}\"".format(project_entity))

        context.data["projectEntity"] = project_entity

        if not asset_name:
            self.log.info("Context is not set. Can't collect global data.")
            return
        asset_entity = legacy_io.find_one({
            "type": "asset",
            "name": asset_name,
            "parent": project_entity["_id"]
        })
        assert asset_entity, (
            "No asset found by the name '{0}' in project '{1}'"
        ).format(asset_name, project_name)

        self.log.debug("Collected Asset \"{}\"".format(asset_entity))

        context.data["assetEntity"] = asset_entity

        data = asset_entity['data']

        # Task type
        asset_tasks = data.get("tasks") or {}
        task_info = asset_tasks.get(task_name) or {}
        task_type = task_info.get("type")
        context.data["taskType"] = task_type

        frame_start = data.get("frameStart")
        if frame_start is None:
            frame_start = 1
            self.log.warning("Missing frame start. Defaulting to 1.")

        frame_end = data.get("frameEnd")
        if frame_end is None:
            frame_end = 2
            self.log.warning("Missing frame end. Defaulting to 2.")

        context.data["frameStart"] = frame_start
        context.data["frameEnd"] = frame_end

        handles = data.get("handles") or 0
        handle_start = data.get("handleStart")
        if handle_start is None:
            handle_start = handles
            self.log.info((
                "Key \"handleStart\" is not set."
                " Using value from \"handles\" key {}."
            ).format(handle_start))

        handle_end = data.get("handleEnd")
        if handle_end is None:
            handle_end = handles
            self.log.info((
                "Key \"handleEnd\" is not set."
                " Using value from \"handles\" key {}."
            ).format(handle_end))

        context.data["handles"] = int(handles)
        context.data["handleStart"] = int(handle_start)
        context.data["handleEnd"] = int(handle_end)

        frame_start_h = frame_start - context.data["handleStart"]
        frame_end_h = frame_end + context.data["handleEnd"]
        context.data["frameStartHandle"] = frame_start_h
        context.data["frameEndHandle"] = frame_end_h

        context.data["fps"] = data["fps"]
