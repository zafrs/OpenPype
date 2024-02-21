# -*- coding: utf-8 -*-
"""Validate model nodes names."""
import os
import platform
import re

import gridfs
import pyblish.api
from maya import cmds

import openpype.hosts.maya.api.action
from openpype.client.mongo import OpenPypeMongoConnection
from openpype.hosts.maya.api.shader_definition_editor import (
    DEFINITION_FILENAME)
from openpype.pipeline import legacy_io
from openpype.pipeline.publish import (
    OptionalPyblishPluginMixin, PublishValidationError, ValidateContentsOrder)


class ValidateModelName(pyblish.api.InstancePlugin,
                        OptionalPyblishPluginMixin):
    """Validate name of model

    starts with (somename)_###_(materialID)_GEO
    materialID must be present in list
    padding number doesn't have limit

    """
    optional = True
    order = ValidateContentsOrder
    hosts = ["maya"]
    families = ["model"]
    label = "Model Name"
    actions = [openpype.hosts.maya.api.action.SelectInvalidAction]
    material_file = None
    database_file = DEFINITION_FILENAME

    @classmethod
    def get_invalid(cls, instance):
        """Get invalid nodes."""
        use_db = cls.database

        def is_group(group_name):
            """Find out if supplied transform is group or not."""
            try:
                children = cmds.listRelatives(group_name, children=True)
                for child in children:
                    if not cmds.ls(child, transforms=True):
                        return False
                return True
            except Exception:
                return False

        invalid = []
        content_instance = instance.data.get("setMembers", None)
        if not content_instance:
            cls.log.error("Instance has no nodes!")
            return True
        pass

        # validate top level group name
        assemblies = cmds.ls(content_instance, assemblies=True, long=True)
        if len(assemblies) != 1:
            cls.log.error("Must have exactly one top group")
            return assemblies or True
        top_group = assemblies[0]
        regex = cls.top_level_regex
        r = re.compile(regex)
        m = r.match(top_group)
        project_name = instance.context.data["projectName"]
        current_asset_name = instance.context.data["asset"]
        if m is None:
            cls.log.error("invalid name on: {}".format(top_group))
            cls.log.error("name doesn't match regex {}".format(regex))
            invalid.append(top_group)
        else:
            if "asset" in r.groupindex:
                if m.group("asset") != current_asset_name:
                    cls.log.error("Invalid asset name in top level group.")
                    return top_group
            if "subset" in r.groupindex:
                if m.group("subset") != instance.data.get("subset"):
                    cls.log.error("Invalid subset name in top level group.")
                    return top_group
            if "project" in r.groupindex:
                if m.group("project") != project_name:
                    cls.log.error("Invalid project name in top level group.")
                    return top_group

        descendants = cmds.listRelatives(content_instance,
                                         allDescendents=True,
                                         fullPath=True) or []

        descendants = cmds.ls(descendants, noIntermediate=True, long=True)
        trns = cmds.ls(descendants, long=False, type='transform')

        # filter out groups
        filtered = [node for node in trns if not is_group(node)]

        # load shader list file as utf-8
        shaders = []
        if not use_db:
            material_file = cls.material_file[platform.system().lower()]
            if material_file:
                if os.path.isfile(material_file):
                    shader_file = open(material_file, "r")
                    shaders = shader_file.readlines()
                    shader_file.close()
            else:
                cls.log.error("Missing shader name definition file.")
                return True
        else:
            client = OpenPypeMongoConnection.get_mongo_client()
            fs = gridfs.GridFS(client[os.getenv("OPENPYPE_DATABASE_NAME")])
            shader_file = fs.find_one({"filename": cls.database_file})
            if not shader_file:
                cls.log.error("Missing shader name definition in database.")
                return True
            shaders = shader_file.read().splitlines()
            shader_file.close()

        # strip line endings from list
        shaders = [s.rstrip() for s in shaders if s.rstrip()]

        # compile regex for testing names
        regex = cls.regex
        r = re.compile(regex)

        for obj in filtered:
            cls.log.debug("testing: {}".format(obj))
            m = r.match(obj)
            if m is None:
                cls.log.error("invalid name on: {}".format(obj))
                invalid.append(obj)
            else:
                # if we have shader files and shader named group is in
                # regex, test this group against names in shader file
                if "shader" in r.groupindex and shaders:
                    try:
                        if not m.group('shader') in shaders:
                            cls.log.error(
                                "invalid materialID on: {0} ({1})".format(
                                    obj, m.group('shader')))
                            invalid.append(obj)
                    except IndexError:
                        # shader named group doesn't match
                        cls.log.error(
                            "shader group doesn't match: {}".format(obj))
                        invalid.append(obj)

        return invalid

    def process(self, instance):
        """Plugin entry point."""
        if not self.is_active(instance.data):
            return

        invalid = self.get_invalid(instance)

        if invalid:
            raise PublishValidationError(
                "Model naming is invalid. See the log.")
