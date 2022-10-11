import pyblish.api

from maya import cmds

import openpype.hosts.maya.api.action


class ValidateVrayProxyMembers(pyblish.api.InstancePlugin):
    """Validate whether the V-Ray Proxy instance has shape members"""

    order = pyblish.api.ValidatorOrder
    label = 'VRay Proxy Members'
    hosts = ['maya']
    families = ['vrayproxy']
    actions = [openpype.hosts.maya.api.action.SelectInvalidAction]

    def process(self, instance):

        invalid = self.get_invalid(instance)

        if invalid:
            raise RuntimeError("'%s' is invalid VRay Proxy for "
                               "export!" % instance.name)

    @classmethod
    def get_invalid(cls, instance):

        shapes = cmds.ls(instance,
                         shapes=True,
                         noIntermediate=True,
                         long=True)

        if not shapes:
            cls.log.error("'%s' contains no shapes." % instance.name)

            # Return the instance itself
            return [instance.name]
