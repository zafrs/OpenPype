# -*- coding: utf-8 -*-
"""Validator for correct file naming."""
import re
import pyblish.api

from openpype.pipeline.publish import (
    ValidateContentsOrder,
    PublishXmlValidationError,
)


class ValidateSimpleUnrealTextureNaming(pyblish.api.InstancePlugin):
    label = "Validate Unreal Texture Names"
    hosts = ["standalonepublisher"]
    families = ["simpleUnrealTexture"]
    order = ValidateContentsOrder
    regex = "^T_{asset}.*"

    def process(self, instance):
        file_name = instance.data.get("originalBasename")
        self.log.info(file_name)
        pattern = self.regex.format(asset=instance.data.get("asset"))
        if not re.match(pattern, file_name):
            msg = f"Invalid file name {file_name}"
            raise PublishXmlValidationError(
                self, msg, formatting_data={
                    "invalid_file": file_name,
                    "asset": instance.data.get("asset")
                })
