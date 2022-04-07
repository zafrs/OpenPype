import os
import six

from maya import cmds

import openpype.api
from openpype.hosts.maya.api.lib import maintained_selection


class ExtractMultiverseUsd(openpype.api.Extractor):
    """Extractor for USD by Multiverse."""

    label = "Extract Multiverse USD"
    hosts = ["maya"]
    families = ["usd"]

    @property
    def options(self):
        """Overridable options for Multiverse USD Export

        Given in the following format
            - {NAME: EXPECTED TYPE}

        If the overridden option's type does not match,
        the option is not included and a warning is logged.

        """

        return {
            "stripNamespaces": bool,
            "mergeTransformAndShape": bool,
            "writeAncestors": bool,
            "flattenParentXforms": bool,
            "writeSparseOverrides": bool,
            "useMetaPrimPath": bool,
            "customRootPath": str,
            "customAttributes": str,
            "nodeTypesToIgnore": str,
            "writeMeshes": bool,
            "writeCurves": bool,
            "writeParticles": bool,
            "writeCameras": bool,
            "writeLights": bool,
            "writeJoints": bool,
            "writeCollections": bool,
            "writePositions": bool,
            "writeNormals": bool,
            "writeUVs": bool,
            "writeColorSets": bool,
            "writeTangents": bool,
            "writeRefPositions": bool,
            "writeBlendShapes": bool,
            "writeDisplayColor": bool,
            "writeSkinWeights": bool,
            "writeMaterialAssignment": bool,
            "writeHardwareShader": bool,
            "writeShadingNetworks": bool,
            "writeTransformMatrix": bool,
            "writeUsdAttributes": bool,
            "timeVaryingTopology": bool,
            "customMaterialNamespace": str,
            "numTimeSamples": int,
            "timeSamplesSpan": float
        }

    @property
    def default_options(self):
        """The default options for Multiverse USD extraction."""

        return {
            "stripNamespaces": False,
            "mergeTransformAndShape": False,
            "writeAncestors": True,
            "flattenParentXforms": False,
            "writeSparseOverrides": False,
            "useMetaPrimPath": False,
            "customRootPath": str(),
            "customAttributes": str(),
            "nodeTypesToIgnore": str(),
            "writeMeshes": True,
            "writeCurves": True,
            "writeParticles": True,
            "writeCameras": False,
            "writeLights": False,
            "writeJoints": False,
            "writeCollections": False,
            "writePositions": True,
            "writeNormals": True,
            "writeUVs": True,
            "writeColorSets": False,
            "writeTangents": False,
            "writeRefPositions": False,
            "writeBlendShapes": False,
            "writeDisplayColor": False,
            "writeSkinWeights": False,
            "writeMaterialAssignment": False,
            "writeHardwareShader": False,
            "writeShadingNetworks": False,
            "writeTransformMatrix": True,
            "writeUsdAttributes": False,
            "timeVaryingTopology": False,
            "customMaterialNamespace": str(),
            "numTimeSamples": 1,
            "timeSamplesSpan": 0.0
        }

    def parse_overrides(self, instance, options):
        """Inspect data of instance to determine overridden options"""

        for key in instance.data:
            if key not in self.options:
                continue

            # Ensure the data is of correct type
            value = instance.data[key]
            if isinstance(value, six.text_type):
                value = str(value)
            if not isinstance(value, self.options[key]):
                self.log.warning(
                    "Overridden attribute {key} was of "
                    "the wrong type: {invalid_type} "
                    "- should have been {valid_type}".format(
                        key=key,
                        invalid_type=type(value).__name__,
                        valid_type=self.options[key].__name__))
                continue

            options[key] = value

        return options

    def process(self, instance):
        # Load plugin firstly
        cmds.loadPlugin("MultiverseForMaya", quiet=True)

        # Define output file path
        staging_dir = self.staging_dir(instance)
        file_name = "{}.usd".format(instance.name)
        file_path = os.path.join(staging_dir, file_name)
        file_path = file_path.replace('\\', '/')

        # Parse export options
        options = self.default_options
        options = self.parse_overrides(instance, options)
        self.log.info("Export options: {0}".format(options))

        # Perform extraction
        self.log.info("Performing extraction ...")

        with maintained_selection():
            members = instance.data("setMembers")
            members = cmds.ls(members,
                              dag=True,
                              shapes=True,
                              type=("mesh"),
                              noIntermediate=True,
                              long=True)
            self.log.info('Collected object {}'.format(members))

            import multiverse

            time_opts = None
            frame_start = instance.data['frameStart']
            frame_end = instance.data['frameEnd']
            handle_start = instance.data['handleStart']
            handle_end = instance.data['handleEnd']
            step = instance.data['step']
            fps = instance.data['fps']
            if frame_end != frame_start:
                time_opts = multiverse.TimeOptions()

                time_opts.writeTimeRange = True
                time_opts.frameRange = (
                    frame_start - handle_start, frame_end + handle_end)
                time_opts.frameIncrement = step
                time_opts.numTimeSamples = instance.data["numTimeSamples"]
                time_opts.timeSamplesSpan = instance.data["timeSamplesSpan"]
                time_opts.framePerSecond = fps

            asset_write_opts = multiverse.AssetWriteOptions(time_opts)
            options_discard_keys = {
                'numTimeSamples',
                'timeSamplesSpan',
                'frameStart',
                'frameEnd',
                'handleStart',
                'handleEnd',
                'step',
                'fps'
            }
            for key, value in options.items():
                if key in options_discard_keys:
                    continue
                setattr(asset_write_opts, key, value)

            multiverse.WriteAsset(file_path, members, asset_write_opts)

        if "representations" not in instance.data:
            instance.data["representations"] = []

        representation = {
            'name': 'usd',
            'ext': 'usd',
            'files': file_name,
            "stagingDir": staging_dir
        }
        instance.data["representations"].append(representation)

        self.log.info("Extracted instance {} to {}".format(
            instance.name, file_path))
