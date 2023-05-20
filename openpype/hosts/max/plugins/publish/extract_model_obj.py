import os
import pyblish.api
from openpype.pipeline import (
    publish,
    OptionalPyblishPluginMixin
)
from pymxs import runtime as rt
from openpype.hosts.max.api import (
    maintained_selection,
    get_all_children
)


class ExtractModelObj(publish.Extractor,
                      OptionalPyblishPluginMixin):
    """
    Extract Geometry in OBJ Format
    """

    order = pyblish.api.ExtractorOrder - 0.05
    label = "Extract OBJ"
    hosts = ["max"]
    families = ["model"]
    optional = True

    def process(self, instance):
        if not self.is_active(instance.data):
            return

        container = instance.data["instance_node"]

        self.log.info("Extracting Geometry ...")

        stagingdir = self.staging_dir(instance)
        filename = "{name}.obj".format(**instance.data)
        filepath = os.path.join(stagingdir,
                                filename)
        self.log.info("Writing OBJ '%s' to '%s'" % (filepath,
                                                    stagingdir))

        with maintained_selection():
            # select and export
            rt.select(get_all_children(rt.getNodeByName(container)))
            rt.execute(f'exportFile @"{filepath}" #noPrompt selectedOnly:true using:ObjExp')    # noqa

        self.log.info("Performing Extraction ...")
        if "representations" not in instance.data:
            instance.data["representations"] = []

        representation = {
            'name': 'obj',
            'ext': 'obj',
            'files': filename,
            "stagingDir": stagingdir,
        }

        instance.data["representations"].append(representation)
        self.log.info("Extracted instance '%s' to: %s" % (instance.name,
                                                          filepath))
