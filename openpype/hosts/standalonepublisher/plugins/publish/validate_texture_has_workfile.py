import pyblish.api

from openpype.pipeline.publish import (
    ValidateContentsOrder,
    PublishXmlValidationError,
)


class ValidateTextureHasWorkfile(pyblish.api.InstancePlugin):
    """Validates that textures have appropriate workfile attached.

        Workfile is optional, disable this Validator after Refresh if you are
        sure it is not needed.
    """
    label = "Validate Texture Has Workfile"
    hosts = ["standalonepublisher"]
    order = ValidateContentsOrder
    families = ["textures"]
    optional = True

    def process(self, instance):
        wfile = instance.data["versionData"].get("workfile")

        msg = "Textures are missing attached workfile"
        if not wfile:
            raise PublishXmlValidationError(self, msg)
