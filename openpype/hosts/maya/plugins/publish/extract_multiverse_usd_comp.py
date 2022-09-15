import os

from maya import cmds

from openpype.pipeline import publish
from openpype.hosts.maya.api.lib import maintained_selection


class ExtractMultiverseUsdComposition(publish.Extractor):
    """Extractor of Multiverse USD Composition data.

    This will extract settings for a Multiverse Write Composition operation:
    they are visible in the Maya set node created by a Multiverse USD
    Composition instance creator.

    The input data contained in the set is either:

    - a single hierarchy consisting of several Multiverse Compound nodes, with
      any number of layers, and Maya transform nodes
    - a single Compound node with more than one layer (in this case the "Write
      as Compound Layers" option should be set).

    Upon publish a .usda composition file will be written.
    """

    label = "Extract Multiverse USD Composition"
    hosts = ["maya"]
    families = ["mvUsdComposition"]
    scene_type = "usd"
    # Order of `fileFormat` must match create_multiverse_usd_comp.py
    file_formats = ["usda", "usd"]

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
            "flattenContent": bool,
            "writeAsCompoundLayers": bool,
            "writePendingOverrides": bool,
            "numTimeSamples": int,
            "timeSamplesSpan": float
        }

    @property
    def default_options(self):
        """The default options for Multiverse USD extraction."""

        return {
            "stripNamespaces": True,
            "mergeTransformAndShape": False,
            "flattenContent": False,
            "writeAsCompoundLayers": False,
            "writePendingOverrides": False,
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
        # Load plugin first
        cmds.loadPlugin("MultiverseForMaya", quiet=True)

        # Define output file path
        staging_dir = self.staging_dir(instance)
        file_format = instance.data.get("fileFormat", 0)
        if file_format in range(len(self.file_formats)):
            self.scene_type = self.file_formats[file_format]
        file_name = "{0}.{1}".format(instance.name, self.scene_type)
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

            comp_write_opts = multiverse.CompositionWriteOptions()

            """
            OP tells MV to write to a staging directory, and then moves the
            file to it's final publish directory. By default, MV write relative
            paths, but these paths will break when the referencing file moves.
            This option forces writes to absolute paths, which is ok within OP
            because all published assets have static paths, and MV can only
            reference published assets. When a proper UsdAssetResolver is used,
            this won't be needed.
            """
            comp_write_opts.forceAbsolutePaths = True

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
                setattr(comp_write_opts, key, value)

            multiverse.WriteComposition(file_path, members, comp_write_opts)

        if "representations" not in instance.data:
            instance.data["representations"] = []

        representation = {
            'name': self.scene_type,
            'ext': self.scene_type,
            'files': file_name,
            'stagingDir': staging_dir
        }
        instance.data["representations"].append(representation)

        self.log.info("Extracted instance {} to {}".format(
            instance.name, file_path))
