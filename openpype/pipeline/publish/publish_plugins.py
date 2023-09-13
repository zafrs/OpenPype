import inspect
from abc import ABCMeta
import pyblish.api
from pyblish.plugin import MetaPlugin, ExplicitMetaPlugin
from openpype.lib.transcoding import VIDEO_EXTENSIONS, IMAGE_EXTENSIONS
from openpype.lib import BoolDef

from .lib import (
    load_help_content_from_plugin,
    get_errored_instances_from_context,
    get_errored_plugins_from_context,
    get_instance_staging_dir,
)

from openpype.pipeline.colorspace import (
    get_colorspace_settings_from_publish_context,
    set_colorspace_data_to_representation
)


class AbstractMetaInstancePlugin(ABCMeta, MetaPlugin):
    pass


class AbstractMetaContextPlugin(ABCMeta, ExplicitMetaPlugin):
    pass


class PublishValidationError(Exception):
    """Validation error happened during publishing.

    This exception should be used when validation publishing failed.

    Has additional UI specific attributes that may be handy for artist.

    Args:
        message(str): Message of error. Short explanation an issue.
        title(str): Title showed in UI. All instances are grouped under
            single title.
        description(str): Detailed description of an error. It is possible
            to use Markdown syntax.
    """

    def __init__(self, message, title=None, description=None, detail=None):
        self.message = message
        self.title = title
        self.description = description or message
        self.detail = detail
        super(PublishValidationError, self).__init__(message)


class PublishXmlValidationError(PublishValidationError):
    def __init__(
        self, plugin, message, key=None, formatting_data=None
    ):
        if key is None:
            key = "main"

        if not formatting_data:
            formatting_data = {}
        result = load_help_content_from_plugin(plugin)
        content_obj = result["errors"][key]
        description = content_obj.description.format(**formatting_data)
        detail = content_obj.detail
        if detail:
            detail = detail.format(**formatting_data)
        super(PublishXmlValidationError, self).__init__(
            message, content_obj.title, description, detail
        )


class KnownPublishError(Exception):
    """Publishing crashed because of known error.

    Message will be shown in UI for artist.
    """

    pass


class OpenPypePyblishPluginMixin:
    # TODO
    # executable_in_thread = False
    #
    # state_message = None
    # state_percent = None
    # _state_change_callbacks = []
    #
    # def set_state(self, percent=None, message=None):
    #     """Inner callback of plugin that would help to show in UI state.
    #
    #     Plugin have registered callbacks on state change which could trigger
    #     update message and percent in UI and repaint the change.
    #
    #     This part must be optional and should not be used to display errors
    #     or for logging.
    #
    #     Message should be short without details.
    #
    #     Args:
    #         percent(int): Percent of processing in range <1-100>.
    #         message(str): Message which will be shown to user (if in UI).
    #     """
    #     if percent is not None:
    #         self.state_percent = percent
    #
    #     if message:
    #         self.state_message = message
    #
    #     for callback in self._state_change_callbacks:
    #         callback(self)

    @classmethod
    def get_attribute_defs(cls):
        """Publish attribute definitions.

        Attributes available for all families in plugin's `families` attribute.
        Returns:
            list<AbstractAttrDef>: Attribute definitions for plugin.
        """

        return []

    @classmethod
    def convert_attribute_values(cls, attribute_values):
        if cls.__name__ not in attribute_values:
            return attribute_values

        plugin_values = attribute_values[cls.__name__]

        attr_defs = cls.get_attribute_defs()
        for attr_def in attr_defs:
            key = attr_def.key
            if key in plugin_values:
                plugin_values[key] = attr_def.convert_value(
                    plugin_values[key]
                )
        return attribute_values

    @staticmethod
    def get_attr_values_from_data_for_plugin(plugin, data):
        """Get attribute values for attribute definitions from data.

        Args:
            plugin (Union[publish.api.Plugin, Type[publish.api.Plugin]]): The
                plugin for which attributes are extracted.
            data(dict): Data from instance or context.
        """

        if not inspect.isclass(plugin):
            plugin = plugin.__class__

        return (
            data
            .get("publish_attributes", {})
            .get(plugin.__name__, {})
        )

    def get_attr_values_from_data(self, data):
        """Get attribute values for attribute definitions from data.

        Args:
            data(dict): Data from instance or context.
        """

        return self.get_attr_values_from_data_for_plugin(self.__class__, data)


class OptionalPyblishPluginMixin(OpenPypePyblishPluginMixin):
    """Prepare mixin for optional plugins.

    Defined active attribute definition prepared for published and
    prepares method which will check if is active or not.

    ```
    class ValidateScene(
        pyblish.api.InstancePlugin, OptionalPyblishPluginMixin
    ):
        def process(self, instance):
            # Skip the instance if is not active by data on the instance
            if not self.is_active(instance.data):
                return
    ```
    """

    @classmethod
    def get_attribute_defs(cls):
        """Attribute definitions based on plugin's optional attribute."""

        # Empty list if plugin is not optional
        if not getattr(cls, "optional", None):
            return []

        # Get active value from class as default value
        active = getattr(cls, "active", True)
        # Return boolean stored under 'active' key with label of the class name
        label = cls.label or cls.__name__
        return [
            BoolDef("active", default=active, label=label)
        ]

    def is_active(self, data):
        """Check if plugins is active for instance/context based on their data.

        Args:
            data(dict): Data from instance or context.
        """
        # Skip if is not optional and return True
        if not getattr(self, "optional", None):
            return True
        attr_values = self.get_attr_values_from_data(data)
        active = attr_values.get("active")
        if active is None:
            active = getattr(self, "active", True)
        return active


class RepairAction(pyblish.api.Action):
    """Repairs the action

    To process the repairing this requires a static `repair(instance)` method
    is available on the plugin.
    """

    label = "Repair"
    on = "failed"  # This action is only available on a failed plug-in
    icon = "wrench"  # Icon from Awesome Icon

    def process(self, context, plugin):
        if not hasattr(plugin, "repair"):
            raise RuntimeError("Plug-in does not have repair method.")

        # Get the errored instances
        self.log.debug("Finding failed instances..")
        errored_instances = get_errored_instances_from_context(context,
                                                               plugin=plugin)
        for instance in errored_instances:
            self.log.debug(
                "Attempting repair for instance: {} ...".format(instance)
            )
            plugin.repair(instance)


class RepairContextAction(pyblish.api.Action):
    """Repairs the action

    To process the repairing this requires a static `repair(context)` method
    is available on the plugin.
    """

    label = "Repair"
    on = "failed"  # This action is only available on a failed plug-in
    icon = "wrench"  # Icon from Awesome Icon

    def process(self, context, plugin):
        if not hasattr(plugin, "repair"):
            raise RuntimeError("Plug-in does not have repair method.")

        # Get the failed instances
        self.log.debug("Finding failed plug-ins..")
        failed_plugins = get_errored_plugins_from_context(context)

        # Apply pyblish.logic to get the instances for the plug-in
        if plugin in failed_plugins:
            self.log.debug("Attempting repair ...")
            plugin.repair(context)


class Extractor(pyblish.api.InstancePlugin):
    """Extractor base class.

    The extractor base class implements a "staging_dir" function used to
    generate a temporary directory for an instance to extract to.

    This temporary directory is generated through `tempfile.mkdtemp()`

    """

    order = 2.0

    def staging_dir(self, instance):
        """Provide a temporary directory in which to store extracted files

        Upon calling this method the staging directory is stored inside
        the instance.data['stagingDir']
        """

        return get_instance_staging_dir(instance)


class ColormanagedPyblishPluginMixin(object):
    """Mixin for colormanaged plugins.

    This class is used to set colorspace data to a publishing
    representation. It contains a static method,
    get_colorspace_settings, which returns config and
    file rules data for the host context.
    It also contains a method, set_representation_colorspace,
    which sets colorspace data to the representation.
    The allowed file extensions are listed in the allowed_ext variable.
    The method first checks if the file extension is in
    the list of allowed extensions. If it is, it then gets the
    colorspace settings from the host context and gets a
    matching colorspace from rules. Finally, it infuses this
    data into the representation.
    """

    def get_colorspace_settings(self, context):
        """Returns solved settings for the host context.

        Args:
            context (publish.Context): publishing context

        Returns:
            tuple | bool: config, file rules or None
        """
        return get_colorspace_settings_from_publish_context(context.data)

    def set_representation_colorspace(
        self, representation, context,
        colorspace=None,
    ):
        """Sets colorspace data to representation.

        Args:
            representation (dict): publishing representation
            context (publish.Context): publishing context
            colorspace (str, optional): colorspace name. Defaults to None.

        Example:
            ```
            {
                # for other publish plugins and loaders
                "colorspace": "linear",
                "config": {
                    # for future references in case need
                    "path": "/abs/path/to/config.ocio",
                    # for other plugins within remote publish cases
                    "template": "{project[root]}/path/to/config.ocio"
                }
            }
            ```

        """

        # using cached settings if available
        set_colorspace_data_to_representation(
            representation, context.data,
            colorspace,
            log=self.log
        )
