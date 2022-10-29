# -*- coding: utf-8 -*-
"""Convert exrs in representation to tiled exrs usin oiio tools."""
import os
import shutil

import pyblish.api

from openpype.lib import run_subprocess, get_oiio_tools_path


class ExtractScanlineExr(pyblish.api.InstancePlugin):
    """Convert tiled EXRs to scanline using OIIO tool."""

    label = "Extract Scanline EXR"
    hosts = ["shell"]
    order = pyblish.api.ExtractorOrder
    families = ["imagesequence", "render", "render2d", "source"]

    def process(self, instance):
        """Plugin entry point."""
        # get representation and loop them
        representations = instance.data["representations"]

        representations_new = []

        for repre in representations:
            self.log.info(
                "Processing representation {}".format(repre.get("name")))
            tags = repre.get("tags", [])
            if "toScanline" not in tags:
                self.log.info(" - missing toScanline tag")
                continue

            # run only on exrs
            if repre.get("ext") != "exr":
                self.log.info("- not EXR files")
                continue

            if not isinstance(repre['files'], (list, tuple)):
                input_files = [repre['files']]
                self.log.info("We have a single frame")
            else:
                input_files = repre['files']
                self.log.info("We have a sequence")

            stagingdir = os.path.normpath(repre.get("stagingDir"))

            oiio_tool_path = get_oiio_tools_path()
            if not os.path.exists(oiio_tool_path):
                self.log.error(
                    "OIIO tool not found in {}".format(oiio_tool_path))
                raise AssertionError("OIIO tool not found")

            for file in input_files:

                original_name = os.path.join(stagingdir, file)
                temp_name = os.path.join(stagingdir, "__{}".format(file))
                # move original render to temp location
                shutil.move(original_name, temp_name)
                oiio_cmd = [
                    oiio_tool_path,
                    os.path.join(stagingdir, temp_name), "--scanline", "-o",
                    os.path.join(stagingdir, original_name)
                ]

                subprocess_exr = " ".join(oiio_cmd)
                self.log.info(f"running: {subprocess_exr}")
                run_subprocess(subprocess_exr, logger=self.log)

                # raise error if there is no ouptput
                if not os.path.exists(os.path.join(stagingdir, original_name)):
                    self.log.error(
                        ("File {} was not converted "
                         "by oiio tool!").format(original_name))
                    raise AssertionError("OIIO tool conversion failed")
                else:
                    try:
                        os.remove(temp_name)
                    except OSError as e:
                        self.log.warning("Unable to delete temp file")
                        self.log.warning(e)

            repre['name'] = 'exr'
            try:
                repre['tags'].remove('toScanline')
            except ValueError:
                # no `toScanline` tag present
                pass

        instance.data["representations"] += representations_new
