# -*- coding: utf-8 -*-
"""Collect render data.

This collector will go through render layers in maya and prepare all data
needed to create instances and their representations for submission and
publishing on farm.

Requires:
    instance    -> families
    instance    -> setMembers

    context     -> currentFile
    context     -> workspaceDir
    context     -> user

    session     -> AVALON_ASSET

Optional:

Provides:
    instance    -> label
    instance    -> subset
    instance    -> attachTo
    instance    -> setMembers
    instance    -> publish
    instance    -> frameStart
    instance    -> frameEnd
    instance    -> byFrameStep
    instance    -> renderer
    instance    -> family
    instance    -> families
    instance    -> asset
    instance    -> time
    instance    -> author
    instance    -> source
    instance    -> expectedFiles
    instance    -> resolutionWidth
    instance    -> resolutionHeight
    instance    -> pixelAspect
"""

import re
import os
import platform
import json

from maya import cmds
import maya.app.renderSetup.model.renderSetup as renderSetup

import pyblish.api

from openpype.lib import get_formatted_current_time
from openpype.pipeline import legacy_io
from openpype.hosts.maya.api.lib_renderproducts import get as get_layer_render_products  # noqa: E501
from openpype.hosts.maya.api import lib


class CollectMayaRender(pyblish.api.ContextPlugin):
    """Gather all publishable render layers from renderSetup."""

    order = pyblish.api.CollectorOrder + 0.01
    hosts = ["maya"]
    label = "Collect Render Layers"
    sync_workfile_version = False

    _aov_chars = {
        "dot": ".",
        "dash": "-",
        "underscore": "_"
    }

    def process(self, context):
        """Entry point to collector."""
        render_instance = None

        for instance in context:
            if "rendering" in instance.data["families"]:
                render_instance = instance
                render_instance.data["remove"] = True

            # make sure workfile instance publishing is enabled
            if "workfile" in instance.data["families"]:
                instance.data["publish"] = True

        if not render_instance:
            self.log.info(
                "No render instance found, skipping render "
                "layer collection."
            )
            return

        render_globals = render_instance
        collected_render_layers = render_instance.data["setMembers"]
        filepath = context.data["currentFile"].replace("\\", "/")
        asset = legacy_io.Session["AVALON_ASSET"]
        workspace = context.data["workspaceDir"]

        # Retrieve render setup layers
        rs = renderSetup.instance()
        maya_render_layers = {
            layer.name(): layer for layer in rs.getRenderLayers()
        }

        for layer in collected_render_layers:
            if layer.startswith("LAYER_"):
                # this is support for legacy mode where render layers
                # started with `LAYER_` prefix.
                layer_name_pattern = r"^LAYER_(.*)"
            else:
                # new way is to prefix render layer name with instance
                # namespace.
                layer_name_pattern = r"^.+:(.*)"

            # todo: We should have a more explicit way to link the renderlayer
            match = re.match(layer_name_pattern, layer)
            if not match:
                msg = "Invalid layer name in set [ {} ]".format(layer)
                self.log.warning(msg)
                continue

            expected_layer_name = match.group(1)
            self.log.info("Processing '{}' as layer [ {} ]"
                          "".format(layer, expected_layer_name))

            # check if layer is part of renderSetup
            if expected_layer_name not in maya_render_layers:
                msg = "Render layer [ {} ] is not in " "Render Setup".format(
                    expected_layer_name
                )
                self.log.warning(msg)
                continue

            # check if layer is renderable
            if not maya_render_layers[expected_layer_name].isRenderable():
                msg = "Render layer [ {} ] is not " "renderable".format(
                    expected_layer_name
                )
                self.log.warning(msg)
                continue

            # detect if there are sets (subsets) to attach render to
            sets = cmds.sets(layer, query=True) or []
            attach_to = []
            for s in sets:
                if not cmds.attributeQuery("family", node=s, exists=True):
                    continue

                attach_to.append(
                    {
                        "version": None,  # we need integrator for that
                        "subset": s,
                        "family": cmds.getAttr("{}.family".format(s)),
                    }
                )
                self.log.info(" -> attach render to: {}".format(s))

            layer_name = "rs_{}".format(expected_layer_name)

            # collect all frames we are expecting to be rendered
            # return all expected files for all cameras and aovs in given
            # frame range
            layer_render_products = get_layer_render_products(layer_name)
            render_products = layer_render_products.layer_data.products
            assert render_products, "no render products generated"
            exp_files = []
            multipart = False
            for product in render_products:
                if product.multipart:
                    multipart = True
                product_name = product.productName
                if product.camera and layer_render_products.has_camera_token():
                    product_name = "{}{}".format(
                        product.camera,
                        "_" + product_name if product_name else "")
                exp_files.append(
                    {
                        product_name: layer_render_products.get_files(
                            product)
                    })

            has_cameras = any(product.camera for product in render_products)
            assert has_cameras, "No render cameras found."

            self.log.info("multipart: {}".format(
                multipart))
            assert exp_files, "no file names were generated, this is bug"
            self.log.info(
                "expected files: {}".format(
                    json.dumps(exp_files, indent=4, sort_keys=True)
                )
            )

            # if we want to attach render to subset, check if we have AOV's
            # in expectedFiles. If so, raise error as we cannot attach AOV
            # (considered to be subset on its own) to another subset
            if attach_to:
                assert isinstance(exp_files, list), (
                    "attaching multiple AOVs or renderable cameras to "
                    "subset is not supported"
                )

            # append full path
            aov_dict = {}
            default_render_file = context.data.get('project_settings')\
                .get('maya')\
                .get('RenderSettings')\
                .get('default_render_image_folder') or ""
            # replace relative paths with absolute. Render products are
            # returned as list of dictionaries.
            publish_meta_path = None
            for aov in exp_files:
                full_paths = []
                aov_first_key = list(aov.keys())[0]
                for file in aov[aov_first_key]:
                    full_path = os.path.join(workspace, default_render_file,
                                             file)
                    full_path = full_path.replace("\\", "/")
                    full_paths.append(full_path)
                    publish_meta_path = os.path.dirname(full_path)
                aov_dict[aov_first_key] = full_paths
            full_exp_files = [aov_dict]

            frame_start_render = int(self.get_render_attribute(
                "startFrame", layer=layer_name))
            frame_end_render = int(self.get_render_attribute(
                "endFrame", layer=layer_name))

            if (int(context.data['frameStartHandle']) == frame_start_render
                    and int(context.data['frameEndHandle']) == frame_end_render):  # noqa: W503, E501

                handle_start = context.data['handleStart']
                handle_end = context.data['handleEnd']
                frame_start = context.data['frameStart']
                frame_end = context.data['frameEnd']
                frame_start_handle = context.data['frameStartHandle']
                frame_end_handle = context.data['frameEndHandle']
            else:
                handle_start = 0
                handle_end = 0
                frame_start = frame_start_render
                frame_end = frame_end_render
                frame_start_handle = frame_start_render
                frame_end_handle = frame_end_render

            # find common path to store metadata
            # so if image prefix is branching to many directories
            # metadata file will be located in top-most common
            # directory.
            # TODO: use `os.path.commonpath()` after switch to Python 3
            publish_meta_path = os.path.normpath(publish_meta_path)
            common_publish_meta_path = os.path.splitdrive(
                publish_meta_path)[0]
            if common_publish_meta_path:
                common_publish_meta_path += os.path.sep
            for part in publish_meta_path.replace(
                    common_publish_meta_path, "").split(os.path.sep):
                common_publish_meta_path = os.path.join(
                    common_publish_meta_path, part)
                if part == expected_layer_name:
                    break

            # TODO: replace this terrible linux hotfix with real solution :)
            if platform.system().lower() in ["linux", "darwin"]:
                common_publish_meta_path = "/" + common_publish_meta_path

            self.log.info(
                "Publish meta path: {}".format(common_publish_meta_path))

            self.log.info(full_exp_files)
            self.log.info("collecting layer: {}".format(layer_name))
            # Get layer specific settings, might be overrides
            colorspace_data = lib.get_color_management_preferences()
            data = {
                "subset": expected_layer_name,
                "attachTo": attach_to,
                "setMembers": layer_name,
                "multipartExr": multipart,
                "review": render_instance.data.get("review") or False,
                "publish": True,

                "handleStart": handle_start,
                "handleEnd": handle_end,
                "frameStart": frame_start,
                "frameEnd": frame_end,
                "frameStartHandle": frame_start_handle,
                "frameEndHandle": frame_end_handle,
                "byFrameStep": int(
                    self.get_render_attribute("byFrameStep",
                                              layer=layer_name)),
                "renderer": self.get_render_attribute(
                    "currentRenderer", layer=layer_name).lower(),
                # instance subset
                "family": "renderlayer",
                "families": ["renderlayer"],
                "asset": asset,
                "time": get_formatted_current_time(),
                "author": context.data["user"],
                # Add source to allow tracing back to the scene from
                # which was submitted originally
                "source": filepath,
                "expectedFiles": full_exp_files,
                "publishRenderMetadataFolder": common_publish_meta_path,
                "renderProducts": layer_render_products,
                "resolutionWidth": lib.get_attr_in_layer(
                    "defaultResolution.width", layer=layer_name
                ),
                "resolutionHeight": lib.get_attr_in_layer(
                    "defaultResolution.height", layer=layer_name
                ),
                "pixelAspect": lib.get_attr_in_layer(
                    "defaultResolution.pixelAspect", layer=layer_name
                ),
                "tileRendering": render_instance.data.get("tileRendering") or False,  # noqa: E501
                "tilesX": render_instance.data.get("tilesX") or 2,
                "tilesY": render_instance.data.get("tilesY") or 2,
                "priority": render_instance.data.get("priority"),
                "convertToScanline": render_instance.data.get(
                    "convertToScanline") or False,
                "useReferencedAovs": render_instance.data.get(
                    "useReferencedAovs") or render_instance.data.get(
                        "vrayUseReferencedAovs") or False,
                "aovSeparator": layer_render_products.layer_data.aov_separator,  # noqa: E501
                "renderSetupIncludeLights": render_instance.data.get(
                    "renderSetupIncludeLights"
                ),
                "colorspaceConfig": colorspace_data["config"],
                "colorspaceDisplay": colorspace_data["display"],
                "colorspaceView": colorspace_data["view"],
                "strict_error_checking": render_instance.data.get(
                    "strict_error_checking", True
                )
            }

            # Collect Deadline url if Deadline module is enabled
            deadline_settings = (
                context.data["system_settings"]["modules"]["deadline"]
            )
            if deadline_settings["enabled"]:
                data["deadlineUrl"] = render_instance.data.get("deadlineUrl")

            if self.sync_workfile_version:
                data["version"] = context.data["version"]

                for instance in context:
                    if instance.data['family'] == "workfile":
                        instance.data["version"] = context.data["version"]

            # handle standalone renderers
            if render_instance.data.get("vrayScene") is True:
                data["families"].append("vrayscene_render")

            if render_instance.data.get("assScene") is True:
                data["families"].append("assscene_render")

            # Include (optional) global settings
            # Get global overrides and translate to Deadline values
            overrides = self.parse_options(str(render_globals))
            data.update(**overrides)

            # get string values for pools
            primary_pool = overrides["renderGlobals"]["Pool"]
            secondary_pool = overrides["renderGlobals"].get("SecondaryPool")
            data["primaryPool"] = primary_pool
            data["secondaryPool"] = secondary_pool

            # Define nice label
            label = "{0} ({1})".format(expected_layer_name, data["asset"])
            label += "  [{0}-{1}]".format(
                int(data["frameStartHandle"]), int(data["frameEndHandle"])
            )

            instance = context.create_instance(expected_layer_name)
            instance.data["label"] = label
            instance.data["farm"] = True
            instance.data.update(data)

    def parse_options(self, render_globals):
        """Get all overrides with a value, skip those without.

        Here's the kicker. These globals override defaults in the submission
        integrator, but an empty value means no overriding is made.
        Otherwise, Frames would override the default frames set under globals.

        Args:
            render_globals (str): collection of render globals

        Returns:
            dict: only overrides with values

        """
        attributes = lib.read(render_globals)

        options = {"renderGlobals": {}}
        options["renderGlobals"]["Priority"] = attributes["priority"]

        # Check for specific pools
        pool_a, pool_b = self._discover_pools(attributes)
        options["renderGlobals"].update({"Pool": pool_a})
        if pool_b:
            options["renderGlobals"].update({"SecondaryPool": pool_b})

        # Machine list
        machine_list = attributes["machineList"]
        if machine_list:
            key = "Whitelist" if attributes["whitelist"] else "Blacklist"
            options["renderGlobals"][key] = machine_list

        # Suspend publish job
        state = "Suspended" if attributes["suspendPublishJob"] else "Active"
        options["publishJobState"] = state

        chunksize = attributes.get("framesPerTask", 1)
        options["renderGlobals"]["ChunkSize"] = chunksize

        # Override frames should be False if extendFrames is False. This is
        # to ensure it doesn't go off doing crazy unpredictable things
        override_frames = False
        extend_frames = attributes.get("extendFrames", False)
        if extend_frames:
            override_frames = attributes.get("overrideExistingFrame", False)

        options["extendFrames"] = extend_frames
        options["overrideExistingFrame"] = override_frames

        maya_render_plugin = "MayaBatch"

        options["mayaRenderPlugin"] = maya_render_plugin

        return options

    def _discover_pools(self, attributes):

        pool_a = None
        pool_b = None

        # Check for specific pools
        pool_b = []
        if "primaryPool" in attributes:
            pool_a = attributes["primaryPool"]
            if "secondaryPool" in attributes:
                pool_b = attributes["secondaryPool"]

        else:
            # Backwards compatibility
            pool_str = attributes.get("pools", None)
            if pool_str:
                pool_a, pool_b = pool_str.split(";")

        # Ensure empty entry token is caught
        if pool_b == "-":
            pool_b = None

        return pool_a, pool_b

    @staticmethod
    def get_render_attribute(attr, layer):
        """Get attribute from render options.

        Args:
            attr (str): name of attribute to be looked up
            layer (str): name of render layer

        Returns:
            Attribute value

        """
        return lib.get_attr_in_layer(
            "defaultRenderGlobals.{}".format(attr), layer=layer
        )
