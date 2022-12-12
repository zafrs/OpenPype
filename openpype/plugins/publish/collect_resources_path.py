"""
Requires:
    context     -> anatomy
    context     -> anatomyData

Provides:
    instance    -> publishDir
    instance    -> resourcesDir
"""

import os
import copy

import pyblish.api


class CollectResourcesPath(pyblish.api.InstancePlugin):
    """Generate directory path where the files and resources will be stored.

    Collects folder name and file name from files, if exists, for in-situ
    publishing.
    """

    label = "Collect Resources Path"
    order = pyblish.api.CollectorOrder + 0.495
    families = ["workfile",
                "pointcache",
                "proxyAbc",
                "camera",
                "animation",
                "model",
                "mayaAscii",
                "mayaScene",
                "setdress",
                "layout",
                "ass",
                "vdbcache",
                "scene",
                "vrayproxy",
                "render",
                "prerender",
                "imagesequence",
                "rendersetup",
                "rig",
                "plate",
                "look",
                "mvLook",
                "yetiRig",
                "yeticache",
                "nukenodes",
                "gizmo",
                "source",
                "matchmove",
                "image",
                "source",
                "assembly",
                "fbx",
                "gltf",
                "textures",
                "action",
                "background",
                "effect",
                "staticMesh",
                "skeletalMesh"
                ]

    def process(self, instance):
        anatomy = instance.context.data["anatomy"]

        template_data = copy.deepcopy(instance.data["anatomyData"])

        # This is for cases of Deprecated anatomy without `folder`
        # TODO remove when all clients have solved this issue
        template_data.update({
            "frame": "FRAME_TEMP",
            "representation": "TEMP"
        })

        # For the first time publish
        if instance.data.get("hierarchy"):
            template_data.update({
                "hierarchy": instance.data["hierarchy"]
            })

        anatomy_filled = anatomy.format(template_data)

        if "folder" in anatomy.templates["publish"]:
            publish_folder = anatomy_filled["publish"]["folder"]
        else:
            # solve deprecated situation when `folder` key is not underneath
            # `publish` anatomy
            self.log.warning((
                "Deprecation warning: Anatomy does not have set `folder`"
                " key underneath `publish` (in global of for project `{}`)."
            ).format(anatomy.project_name))

            file_path = anatomy_filled["publish"]["path"]
            # Directory
            publish_folder = os.path.dirname(file_path)

        publish_folder = os.path.normpath(publish_folder)
        resources_folder = os.path.join(publish_folder, "resources")

        instance.data["publishDir"] = publish_folder
        instance.data["resourcesDir"] = resources_folder

        self.log.debug("publishDir: \"{}\"".format(publish_folder))
        self.log.debug("resourcesDir: \"{}\"".format(resources_folder))

        # parse folder name and file name for online and source templates
        # currentFile comes from hosts workfiles
        # source comes from Publisher
        current_file = instance.data.get("currentFile")
        source = instance.data.get("source")
        source_file = current_file or source
        if source_file and os.path.exists(source_file):
            self.log.debug("Parsing paths for {}".format(source_file))
            if not instance.data.get("originalBasename"):
                instance.data["originalBasename"] = \
                    os.path.basename(source_file)

            if not instance.data.get("originalDirname"):
                instance.data["originalDirname"] = \
                    os.path.dirname(source_file)
