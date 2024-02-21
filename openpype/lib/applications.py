import os
import sys
import copy
import json
import tempfile
import platform
import collections
import inspect
import subprocess
from abc import ABCMeta, abstractmethod

import six

from openpype import AYON_SERVER_ENABLED, PACKAGE_DIR
from openpype.client import get_asset_name_identifier
from openpype.settings import (
    get_system_settings,
    get_project_settings,
    get_local_settings
)
from openpype.settings.constants import (
    METADATA_KEYS,
    M_DYNAMIC_KEY_LABEL
)
from .log import Logger
from .profiles_filtering import filter_profiles
from .local_settings import get_openpype_username

from .python_module_tools import (
    modules_from_path,
    classes_from_module
)
from .execute import (
    find_executable,
    get_linux_launcher_args
)

_logger = None

PLATFORM_NAMES = {"windows", "linux", "darwin"}
DEFAULT_ENV_SUBGROUP = "standard"
CUSTOM_LAUNCH_APP_GROUPS = {
    "djvview"
}


class LaunchTypes:
    """Launch types are filters for pre/post-launch hooks.

    Please use these variables in case they'll change values.
    """

    # Local launch - application is launched on local machine
    local = "local"
    # Farm render job - application is on farm
    farm_render = "farm-render"
    # Farm publish job - integration post-render job
    farm_publish = "farm-publish"
    # Remote launch - application is launched on remote machine from which
    #     can be started publishing
    remote = "remote"
    # Automated launch - application is launched with automated publishing
    automated = "automated"


def parse_environments(env_data, env_group=None, platform_name=None):
    """Parse environment values from settings byt group and platform.

    Data may contain up to 2 hierarchical levels of dictionaries. At the end
    of the last level must be string or list. List is joined using platform
    specific joiner (';' for windows and ':' for linux and mac).

    Hierarchical levels can contain keys for subgroups and platform name.
    Platform specific values must be always last level of dictionary. Platform
    names are "windows" (MS Windows), "linux" (any linux distribution) and
    "darwin" (any MacOS distribution).

    Subgroups are helpers added mainly for standard and on farm usage. Farm
    may require different environments for e.g. licence related values or
    plugins. Default subgroup is "standard".

    Examples:
    ```
    {
        # Unchanged value
        "ENV_KEY1": "value",
        # Empty values are kept (unset environment variable)
        "ENV_KEY2": "",

        # Join list values with ':' or ';'
        "ENV_KEY3": ["value1", "value2"],

        # Environment groups
        "ENV_KEY4": {
            "standard": "DEMO_SERVER_URL",
            "farm": "LICENCE_SERVER_URL"
        },

        # Platform specific (and only for windows and mac)
        "ENV_KEY5": {
            "windows": "windows value",
            "darwin": ["value 1", "value 2"]
        },

        # Environment groups and platform combination
        "ENV_KEY6": {
            "farm": "FARM_VALUE",
            "standard": {
                "windows": ["value1", "value2"],
                "linux": "value1",
                "darwin": ""
            }
        }
    }
    ```
    """
    output = {}
    if not env_data:
        return output

    if not env_group:
        env_group = DEFAULT_ENV_SUBGROUP

    if not platform_name:
        platform_name = platform.system().lower()

    for key, value in env_data.items():
        if isinstance(value, dict):
            # Look if any key is platform key
            #   - expect that represents environment group if does not contain
            #   platform keys
            if not PLATFORM_NAMES.intersection(set(value.keys())):
                # Skip the key if group is not available
                if env_group not in value:
                    continue
                value = value[env_group]

        # Check again if value is dictionary
        #   - this time there should be only platform keys
        if isinstance(value, dict):
            value = value.get(platform_name)

        # Check if value is list and join it's values
        # QUESTION Should empty values be skipped?
        if isinstance(value, (list, tuple)):
            value = os.pathsep.join(value)

        # Set key to output if value is string
        if isinstance(value, six.string_types):
            output[key] = value
    return output


def get_logger():
    """Global lib.applications logger getter."""
    global _logger
    if _logger is None:
        _logger = Logger.get_logger(__name__)
    return _logger


class ApplicationNotFound(Exception):
    """Application was not found in ApplicationManager by name."""

    def __init__(self, app_name):
        self.app_name = app_name
        super(ApplicationNotFound, self).__init__(
            "Application \"{}\" was not found.".format(app_name)
        )


class ApplictionExecutableNotFound(Exception):
    """Defined executable paths are not available on the machine."""

    def __init__(self, application):
        self.application = application
        details = None
        if not application.executables:
            msg = (
                "Executable paths for application \"{}\"({}) are not set."
            )
        else:
            msg = (
                "Defined executable paths for application \"{}\"({})"
                " are not available on this machine."
            )
            details = "Defined paths:"
            for executable in application.executables:
                details += "\n- " + executable.executable_path

        self.msg = msg.format(application.full_label, application.full_name)
        self.details = details

        exc_mgs = str(self.msg)
        if details:
            # Is good idea to pass new line symbol to exception message?
            exc_mgs += "\n" + details
        self.exc_msg = exc_mgs
        super(ApplictionExecutableNotFound, self).__init__(exc_mgs)


class ApplicationLaunchFailed(Exception):
    """Application launch failed due to known reason.

    Message should be self explanatory as traceback won't be shown.
    """
    pass


class ApplicationGroup:
    """Hold information about application group.

    Application group wraps different versions(variants) of application.
    e.g. "maya" is group and "maya_2020" is variant.

    Group hold `host_name` which is implementation name used in pype. Also
    holds `enabled` if whole app group is enabled or `icon` for application
    icon path in resources.

    Group has also `environment` which hold same environments for all variants.

    Args:
        name (str): Groups' name.
        data (dict): Group defying data loaded from settings.
        manager (ApplicationManager): Manager that created the group.
    """

    def __init__(self, name, data, manager):
        self.name = name
        self.manager = manager
        self._data = data

        self.enabled = data.get("enabled", True)
        self.label = data.get("label") or None
        self.icon = data.get("icon") or None
        self._environment = data.get("environment") or {}

        host_name = data.get("host_name", None)
        self.is_host = host_name is not None
        self.host_name = host_name

        variants = data.get("variants") or {}
        key_label_mapping = variants.pop(M_DYNAMIC_KEY_LABEL, {})
        for variant_name, variant_data in variants.items():
            if variant_name in METADATA_KEYS:
                continue

            if "variant_label" not in variant_data:
                variant_label = key_label_mapping.get(variant_name)
                if variant_label:
                    variant_data["variant_label"] = variant_label

            variants[variant_name] = Application(
                variant_name, variant_data, self
            )

        self.variants = variants

    def __repr__(self):
        return "<{}> - {}".format(self.__class__.__name__, self.name)

    def __iter__(self):
        for variant in self.variants.values():
            yield variant

    @property
    def environment(self):
        return copy.deepcopy(self._environment)


class Application:
    """Hold information about application.

    Object by itself does nothing special.

    Args:
        name (str): Specific version (or variant) of application.
            e.g. "maya2020", "nuke11.3", etc.
        data (dict): Data for the version containing information about
            executables, variant label or if is enabled.
            Only required key is `executables`.
        group (ApplicationGroup): App group object that created the application
            and under which application belongs.
    """

    def __init__(self, name, data, group):
        self.name = name
        self.group = group
        self._data = data

        enabled = False
        if group.enabled:
            enabled = data.get("enabled", True)
        self.enabled = enabled
        self.use_python_2 = data.get("use_python_2", False)

        self.label = data.get("variant_label") or name
        self.full_name = "/".join((group.name, name))

        if group.label:
            full_label = " ".join((group.label, self.label))
        else:
            full_label = self.label
        self.full_label = full_label
        self._environment = data.get("environment") or {}

        arguments = data.get("arguments")
        if isinstance(arguments, dict):
            arguments = arguments.get(platform.system().lower())

        if not arguments:
            arguments = []
        self.arguments = arguments

        if "executables" not in data:
            self.executables = [
                UndefinedApplicationExecutable()
            ]
            return

        _executables = data["executables"]
        if isinstance(_executables, dict):
            _executables = _executables.get(platform.system().lower())

        if not _executables:
            _executables = []

        executables = []
        for executable in _executables:
            executables.append(ApplicationExecutable(executable))

        self.executables = executables

    def __repr__(self):
        return "<{}> - {}".format(self.__class__.__name__, self.full_name)

    @property
    def environment(self):
        return copy.deepcopy(self._environment)

    @property
    def manager(self):
        return self.group.manager

    @property
    def host_name(self):
        return self.group.host_name

    @property
    def icon(self):
        return self.group.icon

    @property
    def is_host(self):
        return self.group.is_host

    def find_executable(self):
        """Try to find existing executable for application.

        Returns (str): Path to executable from `executables` or None if any
            exists.
        """
        for executable in self.executables:
            if executable.exists():
                return executable
        return None

    def launch(self, *args, **kwargs):
        """Launch the application.

        For this purpose is used manager's launch method to keep logic at one
        place.

        Arguments must match with manager's launch method. That's why *args
        **kwargs are used.

        Returns:
            subprocess.Popen: Return executed process as Popen object.
        """
        return self.manager.launch(self.full_name, *args, **kwargs)


class ApplicationManager:
    """Load applications and tools and store them by their full name.

    Args:
        system_settings (dict): Preloaded system settings. When passed manager
            will always use these values. Gives ability to create manager
            using different settings.
    """

    def __init__(self, system_settings=None):
        self.log = Logger.get_logger(self.__class__.__name__)

        self.app_groups = {}
        self.applications = {}
        self.tool_groups = {}
        self.tools = {}

        self._system_settings = system_settings

        self.refresh()

    def set_system_settings(self, system_settings):
        """Ability to change init system settings.

        This will trigger refresh of manager.
        """
        self._system_settings = system_settings

        self.refresh()

    def refresh(self):
        """Refresh applications from settings."""
        self.app_groups.clear()
        self.applications.clear()
        self.tool_groups.clear()
        self.tools.clear()

        if self._system_settings is not None:
            settings = copy.deepcopy(self._system_settings)
        else:
            settings = get_system_settings(
                clear_metadata=False, exclude_locals=False
            )

        all_app_defs = {}
        # Prepare known applications
        app_defs = settings["applications"]
        additional_apps = {}
        for group_name, variant_defs in app_defs.items():
            if group_name in METADATA_KEYS:
                continue

            if group_name == "additional_apps":
                additional_apps = variant_defs
            else:
                all_app_defs[group_name] = variant_defs

        # Prepare additional applications
        # - First find dynamic keys that can be used as labels of group
        dynamic_keys = {}
        for group_name, variant_defs in additional_apps.items():
            if group_name == M_DYNAMIC_KEY_LABEL:
                dynamic_keys = variant_defs
                break

        # Add additional apps to known applications
        for group_name, variant_defs in additional_apps.items():
            if group_name in METADATA_KEYS:
                continue

            # Determine group label
            label = variant_defs.get("label")
            if not label:
                # Look for label set in dynamic labels
                label = dynamic_keys.get(group_name)
                if not label:
                    label = group_name
                variant_defs["label"] = label

            all_app_defs[group_name] = variant_defs

        for group_name, variant_defs in all_app_defs.items():
            if group_name in METADATA_KEYS:
                continue

            group = ApplicationGroup(group_name, variant_defs, self)
            self.app_groups[group_name] = group
            for app in group:
                self.applications[app.full_name] = app

        tools_definitions = settings["tools"]["tool_groups"]
        tool_label_mapping = tools_definitions.pop(M_DYNAMIC_KEY_LABEL, {})
        for tool_group_name, tool_group_data in tools_definitions.items():
            if not tool_group_name or tool_group_name in METADATA_KEYS:
                continue

            tool_group_label = (
                tool_label_mapping.get(tool_group_name) or tool_group_name
            )
            group = EnvironmentToolGroup(
                tool_group_name, tool_group_label, tool_group_data, self
            )
            self.tool_groups[tool_group_name] = group
            for tool in group:
                self.tools[tool.full_name] = tool

    def find_latest_available_variant_for_group(self, group_name):
        group = self.app_groups.get(group_name)
        if group is None or not group.enabled:
            return None

        output = None
        for _, variant in reversed(sorted(group.variants.items())):
            executable = variant.find_executable()
            if executable:
                output = variant
                break
        return output

    def create_launch_context(self, app_name, **data):
        """Prepare launch context for application.

        Args:
            app_name (str): Name of application that should be launched.
            **data (Any): Any additional data. Data may be used during

        Returns:
            ApplicationLaunchContext: Launch context for application.

        Raises:
            ApplicationNotFound: Application was not found by entered name.
        """

        app = self.applications.get(app_name)
        if not app:
            raise ApplicationNotFound(app_name)

        executable = app.find_executable()

        return ApplicationLaunchContext(
            app, executable, **data
        )

    def launch_with_context(self, launch_context):
        """Launch application using existing launch context.

        Args:
            launch_context (ApplicationLaunchContext): Prepared launch
                context.
        """

        if not launch_context.executable:
            raise ApplictionExecutableNotFound(launch_context.application)
        return launch_context.launch()

    def launch(self, app_name, **data):
        """Launch procedure.

        For host application it's expected to contain "project_name",
        "asset_name" and "task_name".

        Args:
            app_name (str): Name of application that should be launched.
            **data (dict): Any additional data. Data may be used during
                preparation to store objects usable in multiple places.

        Raises:
            ApplicationNotFound: Application was not found by entered
                argument `app_name`.
            ApplictionExecutableNotFound: Executables in application definition
                were not found on this machine.
            ApplicationLaunchFailed: Something important for application launch
                failed. Exception should contain explanation message,
                traceback should not be needed.
        """

        context = self.create_launch_context(app_name, **data)
        return self.launch_with_context(context)



class EnvironmentToolGroup:
    """Hold information about environment tool group.

    Environment tool group may hold different variants of same tool and set
    environments that are same for all of them.

    e.g. "mtoa" may have different versions but all environments except one
        are same.

    Args:
        name (str): Name of the tool group.
        data (dict): Group's information with it's variants.
        manager (ApplicationManager): Manager that creates the group.
    """

    def __init__(self, name, label, data, manager):
        self.name = name
        self.label = label
        self._data = data
        self.manager = manager
        self._environment = data["environment"]

        variants = data.get("variants") or {}
        label_by_key = variants.pop(M_DYNAMIC_KEY_LABEL, {})
        variants_by_name = {}
        for variant_name, variant_data in variants.items():
            if variant_name in METADATA_KEYS:
                continue

            variant_label = label_by_key.get(variant_name) or variant_name
            tool = EnvironmentTool(
                variant_name, variant_label, variant_data, self
            )
            variants_by_name[variant_name] = tool
        self.variants = variants_by_name

    def __repr__(self):
        return "<{}> - {}".format(self.__class__.__name__, self.name)

    def __iter__(self):
        for variant in self.variants.values():
            yield variant

    @property
    def environment(self):
        return copy.deepcopy(self._environment)


class EnvironmentTool:
    """Hold information about application tool.

    Structure of tool information.

    Args:
        name (str): Name of the tool.
        variant_data (dict): Variant data with environments and
            host and app variant filters.
        group (str): Name of group which wraps tool.
    """

    def __init__(self, name, label, variant_data, group):
        # Backwards compatibility 3.9.1 - 3.9.2
        # - 'variant_data' contained only environments but contain also host
        #   and application variant filters
        host_names = variant_data.get("host_names", [])
        app_variants = variant_data.get("app_variants", [])

        if "environment" in variant_data:
            environment = variant_data["environment"]
        else:
            environment = variant_data

        self.host_names = host_names
        self.app_variants = app_variants
        self.name = name
        self.variant_label = label
        self.label = " ".join((group.label, label))
        self.group = group

        self._environment = environment
        self.full_name = "/".join((group.name, name))

    def __repr__(self):
        return "<{}> - {}".format(self.__class__.__name__, self.full_name)

    @property
    def environment(self):
        return copy.deepcopy(self._environment)

    def is_valid_for_app(self, app):
        """Is tool valid for application.

        Args:
            app (Application): Application for which are prepared environments.
        """
        if self.app_variants and app.full_name not in self.app_variants:
            return False

        if self.host_names and app.host_name not in self.host_names:
            return False
        return True


class ApplicationExecutable:
    """Representation of executable loaded from settings."""

    def __init__(self, executable):
        # Try to format executable with environments
        try:
            executable = executable.format(**os.environ)
        except Exception:
            pass

        # On MacOS check if exists path to executable when ends with `.app`
        # - it is common that path will lead to "/Applications/Blender" but
        #   real path is "/Applications/Blender.app"
        if platform.system().lower() == "darwin":
            executable = self.macos_executable_prep(executable)

        self.executable_path = executable

    def __str__(self):
        return self.executable_path

    def __repr__(self):
        return "<{}> {}".format(self.__class__.__name__, self.executable_path)

    @staticmethod
    def macos_executable_prep(executable):
        """Try to find full path to executable file.

        Real executable is stored in '*.app/Contents/MacOS/<executable>'.

        Having path to '*.app' gives ability to read it's plist info and
        use "CFBundleExecutable" key from plist to know what is "executable."

        Plist is stored in '*.app/Contents/Info.plist'.

        This is because some '*.app' directories don't have same permissions
        as real executable.
        """
        # Try to find if there is `.app` file
        if not os.path.exists(executable):
            _executable = executable + ".app"
            if os.path.exists(_executable):
                executable = _executable

        # Try to find real executable if executable has `Contents` subfolder
        contents_dir = os.path.join(executable, "Contents")
        if os.path.exists(contents_dir):
            executable_filename = None
            # Load plist file and check for bundle executable
            plist_filepath = os.path.join(contents_dir, "Info.plist")
            if os.path.exists(plist_filepath):
                import plistlib

                if hasattr(plistlib, "load"):
                    with open(plist_filepath, "rb") as stream:
                        parsed_plist = plistlib.load(stream)
                else:
                    parsed_plist = plistlib.readPlist(plist_filepath)
                executable_filename = parsed_plist.get("CFBundleExecutable")

            if executable_filename:
                executable = os.path.join(
                    contents_dir, "MacOS", executable_filename
                )

        return executable

    def as_args(self):
        return [self.executable_path]

    def _realpath(self):
        """Check if path is valid executable path."""
        # Check for executable in PATH
        result = find_executable(self.executable_path)
        if result is not None:
            return result

        # This is not 100% validation but it is better than remove ability to
        #   launch .bat, .sh or extentionless files
        if os.path.exists(self.executable_path):
            return self.executable_path
        return None

    def exists(self):
        if not self.executable_path:
            return False
        return bool(self._realpath())


class UndefinedApplicationExecutable(ApplicationExecutable):
    """Some applications do not require executable path from settings.

    In that case this class is used to "fake" existing executable.
    """
    def __init__(self):
        pass

    def __str__(self):
        return self.__class__.__name__

    def __repr__(self):
        return "<{}>".format(self.__class__.__name__)

    def as_args(self):
        return []

    def exists(self):
        return True


@six.add_metaclass(ABCMeta)
class LaunchHook:
    """Abstract base class of launch hook."""
    # Order of prelaunch hook, will be executed as last if set to None.
    order = None
    # List of host implementations, skipped if empty.
    hosts = set()
    # Set of application groups
    app_groups = set()
    # Set of specific application names
    app_names = set()
    # Set of platform availability
    platforms = set()
    # Set of launch types for which is available
    # - if empty then is available for all launch types
    # - by default has 'local' which is most common reason for launc hooks
    launch_types = {LaunchTypes.local}

    def __init__(self, launch_context):
        """Constructor of launch hook.

        Always should be called
        """
        self.log = Logger.get_logger(self.__class__.__name__)

        self.launch_context = launch_context

        is_valid = self.class_validation(launch_context)
        if is_valid:
            is_valid = self.validate()

        self.is_valid = is_valid

    @classmethod
    def class_validation(cls, launch_context):
        """Validation of class attributes by launch context.

        Args:
            launch_context (ApplicationLaunchContext): Context of launching
                application.

        Returns:
            bool: Is launch hook valid for the context by class attributes.
        """
        if cls.platforms:
            low_platforms = tuple(
                _platform.lower()
                for _platform in cls.platforms
            )
            if platform.system().lower() not in low_platforms:
                return False

        if cls.hosts:
            if launch_context.host_name not in cls.hosts:
                return False

        if cls.app_groups:
            if launch_context.app_group.name not in cls.app_groups:
                return False

        if cls.app_names:
            if launch_context.app_name not in cls.app_names:
                return False

        if cls.launch_types:
            if launch_context.launch_type not in cls.launch_types:
                return False

        return True

    @property
    def data(self):
        return self.launch_context.data

    @property
    def application(self):
        return getattr(self.launch_context, "application", None)

    @property
    def manager(self):
        return getattr(self.application, "manager", None)

    @property
    def host_name(self):
        return getattr(self.application, "host_name", None)

    @property
    def app_group(self):
        return getattr(self.application, "group", None)

    @property
    def app_name(self):
        return getattr(self.application, "full_name", None)

    @property
    def modules_manager(self):
        return getattr(self.launch_context, "modules_manager", None)

    def validate(self):
        """Optional validation of launch hook on initialization.

        Returns:
            bool: Hook is valid (True) or invalid (False).
        """
        # QUESTION Not sure if this method has any usable potential.
        # - maybe result can be based on settings
        return True

    @abstractmethod
    def execute(self, *args, **kwargs):
        """Abstract execute method where logic of hook is."""
        pass


class PreLaunchHook(LaunchHook):
    """Abstract class of prelaunch hook.

    This launch hook will be processed before application is launched.

    If any exception will happen during processing the application won't be
    launched.
    """


class PostLaunchHook(LaunchHook):
    """Abstract class of postlaunch hook.

    This launch hook will be processed after application is launched.

    Nothing will happen if any exception will happen during processing. And
    processing of other postlaunch hooks won't stop either.
    """


class ApplicationLaunchContext:
    """Context of launching application.

    Main purpose of context is to prepare launch arguments and keyword
    arguments for new process. Most important part of keyword arguments
    preparations are environment variables.

    During the whole process is possible to use `data` attribute to store
    object usable in multiple places.

    Launch arguments are strings in list. It is possible to "chain" argument
    when order of them matters. That is possible to do with adding list where
    order is right and should not change.
    NOTE: This is recommendation, not requirement.
    e.g.: `["nuke.exe", "--NukeX"]` -> In this case any part of process may
    insert argument between `nuke.exe` and `--NukeX`. To keep them together
    it is better to wrap them in another list: `[["nuke.exe", "--NukeX"]]`.

    Notes:
        It is possible to use launch context only to prepare environment
            variables. In that case `executable` may be None and can be used
            'run_prelaunch_hooks' method to run prelaunch hooks which prepare
            them.

    Args:
        application (Application): Application definition.
        executable (ApplicationExecutable): Object with path to executable.
        env_group (Optional[str]): Environment variable group. If not set
            'DEFAULT_ENV_SUBGROUP' is used.
        launch_type (Optional[str]): Launch type. If not set 'local' is used.
        **data (dict): Any additional data. Data may be used during
            preparation to store objects usable in multiple places.
    """

    def __init__(
        self,
        application,
        executable,
        env_group=None,
        launch_type=None,
        **data
    ):
        from openpype.modules import ModulesManager

        # Application object
        self.application = application

        self.modules_manager = ModulesManager()

        # Logger
        logger_name = "{}-{}".format(self.__class__.__name__,
                                     self.application.full_name)
        self.log = Logger.get_logger(logger_name)

        self.executable = executable

        if launch_type is None:
            launch_type = LaunchTypes.local
        self.launch_type = launch_type

        if env_group is None:
            env_group = DEFAULT_ENV_SUBGROUP

        self.env_group = env_group

        self.data = dict(data)

        launch_args = []
        if executable is not None:
            launch_args = executable.as_args()
        # subprocess.Popen launch arguments (first argument in constructor)
        self.launch_args = launch_args
        self.launch_args.extend(application.arguments)
        if self.data.get("app_args"):
            self.launch_args.extend(self.data.pop("app_args"))

        # Handle launch environemtns
        src_env = self.data.pop("env", None)
        if src_env is not None and not isinstance(src_env, dict):
            self.log.warning((
                "Passed `env` kwarg has invalid type: {}. Expected: `dict`."
                " Using `os.environ` instead."
            ).format(str(type(src_env))))
            src_env = None

        if src_env is None:
            src_env = os.environ

        ignored_env = {"QT_API", }
        env = {
            key: str(value)
            for key, value in src_env.items()
            if key not in ignored_env
        }
        # subprocess.Popen keyword arguments
        self.kwargs = {"env": env}

        if platform.system().lower() == "windows":
            # Detach new process from currently running process on Windows
            flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
            )
            self.kwargs["creationflags"] = flags

        if not sys.stdout:
            self.kwargs["stdout"] = subprocess.DEVNULL
            self.kwargs["stderr"] = subprocess.DEVNULL

        self.prelaunch_hooks = None
        self.postlaunch_hooks = None

        self.process = None
        self._prelaunch_hooks_executed = False

    @property
    def env(self):
        if (
            "env" not in self.kwargs
            or self.kwargs["env"] is None
        ):
            self.kwargs["env"] = {}
        return self.kwargs["env"]

    @env.setter
    def env(self, value):
        if not isinstance(value, dict):
            raise ValueError(
                "'env' attribute expect 'dict' object. Got: {}".format(
                    str(type(value))
                )
            )
        self.kwargs["env"] = value

    def _collect_addons_launch_hook_paths(self):
        """Helper to collect application launch hooks from addons.

        Module have to have implemented 'get_launch_hook_paths' method which
        can expect application as argument or nothing.

        Returns:
            List[str]: Paths to launch hook directories.
        """

        expected_types = (list, tuple, set)

        output = []
        for module in self.modules_manager.get_enabled_modules():
            # Skip module if does not have implemented 'get_launch_hook_paths'
            func = getattr(module, "get_launch_hook_paths", None)
            if func is None:
                continue

            func = module.get_launch_hook_paths
            if hasattr(inspect, "signature"):
                sig = inspect.signature(func)
                expect_args = len(sig.parameters) > 0
            else:
                expect_args = len(inspect.getargspec(func)[0]) > 0

            # Pass application argument if method expect it.
            try:
                if expect_args:
                    hook_paths = func(self.application)
                else:
                    hook_paths = func()
            except Exception:
                self.log.warning(
                    "Failed to call 'get_launch_hook_paths'",
                    exc_info=True
                )
                continue

            if not hook_paths:
                continue

            # Convert string to list
            if isinstance(hook_paths, six.string_types):
                hook_paths = [hook_paths]

            # Skip invalid types
            if not isinstance(hook_paths, expected_types):
                self.log.warning((
                    "Result of `get_launch_hook_paths`"
                    " has invalid type {}. Expected {}"
                ).format(type(hook_paths), expected_types))
                continue

            output.extend(hook_paths)
        return output

    def paths_to_launch_hooks(self):
        """Directory paths where to look for launch hooks."""
        # This method has potential to be part of application manager (maybe).
        paths = []

        # TODO load additional studio paths from settings
        import openpype
        openpype_dir = os.path.dirname(os.path.abspath(openpype.__file__))

        global_hooks_dir = os.path.join(openpype_dir, "hooks")

        hooks_dirs = [
            global_hooks_dir
        ]
        if self.host_name:
            # If host requires launch hooks and is module then launch hooks
            #   should be collected using 'collect_launch_hook_paths'
            #   - module have to implement 'get_launch_hook_paths'
            host_module = self.modules_manager.get_host_module(self.host_name)
            if not host_module:
                hooks_dirs.append(os.path.join(
                    openpype_dir, "hosts", self.host_name, "hooks"
                ))

        for path in hooks_dirs:
            if (
                os.path.exists(path)
                and os.path.isdir(path)
                and path not in paths
            ):
                paths.append(path)

        # Load modules paths
        paths.extend(self._collect_addons_launch_hook_paths())

        return paths

    def discover_launch_hooks(self, force=False):
        """Load and prepare launch hooks."""
        if (
            self.prelaunch_hooks is not None
            or self.postlaunch_hooks is not None
        ):
            if not force:
                self.log.info("Launch hooks were already discovered.")
                return

            self.prelaunch_hooks.clear()
            self.postlaunch_hooks.clear()

        self.log.debug("Discovery of launch hooks started.")

        paths = self.paths_to_launch_hooks()
        self.log.debug("Paths searched for launch hooks:\n{}".format(
            "\n".join("- {}".format(path) for path in paths)
        ))

        all_classes = {
            "pre": [],
            "post": []
        }
        for path in paths:
            if not os.path.exists(path):
                self.log.info(
                    "Path to launch hooks does not exist: \"{}\"".format(path)
                )
                continue

            modules, _crashed = modules_from_path(path)
            for _filepath, module in modules:
                all_classes["pre"].extend(
                    classes_from_module(PreLaunchHook, module)
                )
                all_classes["post"].extend(
                    classes_from_module(PostLaunchHook, module)
                )

        for launch_type, classes in all_classes.items():
            hooks_with_order = []
            hooks_without_order = []
            for klass in classes:
                try:
                    hook = klass(self)
                    if not hook.is_valid:
                        self.log.debug(
                            "Skipped hook invalid for current launch context: "
                            "{}".format(klass.__name__)
                        )
                        continue

                    if inspect.isabstract(hook):
                        self.log.debug("Skipped abstract hook: {}".format(
                            klass.__name__
                        ))
                        continue

                    # Separate hooks by pre/post class
                    if hook.order is None:
                        hooks_without_order.append(hook)
                    else:
                        hooks_with_order.append(hook)

                except Exception:
                    self.log.warning(
                        "Initialization of hook failed: "
                        "{}".format(klass.__name__),
                        exc_info=True
                    )

            # Sort hooks with order by order
            ordered_hooks = list(sorted(
                hooks_with_order, key=lambda obj: obj.order
            ))
            # Extend ordered hooks with hooks without defined order
            ordered_hooks.extend(hooks_without_order)

            if launch_type == "pre":
                self.prelaunch_hooks = ordered_hooks
            else:
                self.postlaunch_hooks = ordered_hooks

        self.log.debug("Found {} prelaunch and {} postlaunch hooks.".format(
            len(self.prelaunch_hooks), len(self.postlaunch_hooks)
        ))

    @property
    def app_name(self):
        return self.application.name

    @property
    def host_name(self):
        return self.application.host_name

    @property
    def app_group(self):
        return self.application.group

    @property
    def manager(self):
        return self.application.manager

    def _run_process(self):
        # Windows and MacOS have easier process start
        low_platform = platform.system().lower()
        if low_platform in ("windows", "darwin"):
            return subprocess.Popen(self.launch_args, **self.kwargs)

        # Linux uses mid process
        # - it is possible that the mid process executable is not
        #   available for this version of OpenPype in that case use standard
        #   launch
        launch_args = get_linux_launcher_args()
        if launch_args is None:
            return subprocess.Popen(self.launch_args, **self.kwargs)

        # Prepare data that will be passed to midprocess
        # - store arguments to a json and pass path to json as last argument
        # - pass environments to set
        app_env = self.kwargs.pop("env", {})
        json_data = {
            "args": self.launch_args,
            "env": app_env
        }
        if app_env:
            # Filter environments of subprocess
            self.kwargs["env"] = {
                key: value
                for key, value in os.environ.items()
                if key in app_env
            }

        # Create temp file
        json_temp = tempfile.NamedTemporaryFile(
            mode="w", prefix="op_app_args", suffix=".json", delete=False
        )
        json_temp.close()
        json_temp_filpath = json_temp.name
        with open(json_temp_filpath, "w") as stream:
            json.dump(json_data, stream)

        launch_args.append(json_temp_filpath)

        # Create mid-process which will launch application
        process = subprocess.Popen(launch_args, **self.kwargs)
        # Wait until the process finishes
        #   - This is important! The process would stay in "open" state.
        process.wait()
        # Remove the temp file
        os.remove(json_temp_filpath)
        # Return process which is already terminated
        return process

    def run_prelaunch_hooks(self):
        """Run prelaunch hooks.

        This method will be executed only once, any future calls will skip
            the processing.
        """

        if self._prelaunch_hooks_executed:
            self.log.warning("Prelaunch hooks were already executed.")
            return
        # Discover launch hooks
        self.discover_launch_hooks()

        # Execute prelaunch hooks
        for prelaunch_hook in self.prelaunch_hooks:
            self.log.debug("Executing prelaunch hook: {}".format(
                str(prelaunch_hook.__class__.__name__)
            ))
            prelaunch_hook.execute()
        self._prelaunch_hooks_executed = True

    def launch(self):
        """Collect data for new process and then create it.

        This method must not be executed more than once.

        Returns:
            subprocess.Popen: Created process as Popen object.
        """
        if self.process is not None:
            self.log.warning("Application was already launched.")
            return

        if not self._prelaunch_hooks_executed:
            self.run_prelaunch_hooks()

        self.log.debug("All prelaunch hook executed. Starting new process.")

        # Prepare subprocess args
        args_len_str = ""
        if isinstance(self.launch_args, str):
            args = self.launch_args
        else:
            args = self.clear_launch_args(self.launch_args)
            args_len_str = " ({})".format(len(args))
        self.log.info(
            "Launching \"{}\" with args{}: {}".format(
                self.application.full_name, args_len_str, args
            )
        )
        self.launch_args = args

        # Run process
        self.process = self._run_process()

        # Process post launch hooks
        for postlaunch_hook in self.postlaunch_hooks:
            self.log.debug("Executing postlaunch hook: {}".format(
                str(postlaunch_hook.__class__.__name__)
            ))

            # TODO how to handle errors?
            # - store to variable to let them accessible?
            try:
                postlaunch_hook.execute()

            except Exception:
                self.log.warning(
                    "After launch procedures were not successful.",
                    exc_info=True
                )

        self.log.debug("Launch of {} finished.".format(
            self.application.full_name
        ))

        return self.process

    @staticmethod
    def clear_launch_args(args):
        """Collect launch arguments to final order.

        Launch argument should be list that may contain another lists this
        function will upack inner lists and keep ordering.

        ```
        # source
        [ [ arg1, [ arg2, arg3 ] ], arg4, [arg5, arg6]]
        # result
        [ arg1, arg2, arg3, arg4, arg5, arg6]

        Args:
            args (list): Source arguments in list may contain inner lists.

        Return:
            list: Unpacked arguments.
        """
        if isinstance(args, str):
            return args
        all_cleared = False
        while not all_cleared:
            all_cleared = True
            new_args = []
            for arg in args:
                if isinstance(arg, (list, tuple, set)):
                    all_cleared = False
                    for _arg in arg:
                        new_args.append(_arg)
                else:
                    new_args.append(arg)
            args = new_args

        return args


class MissingRequiredKey(KeyError):
    pass


class EnvironmentPrepData(dict):
    """Helper dictionary for storin temp data during environment prep.

    Args:
        data (dict): Data must contain required keys.
    """
    required_keys = (
        "project_doc", "asset_doc", "task_name", "app", "anatomy"
    )

    def __init__(self, data):
        for key in self.required_keys:
            if key not in data:
                raise MissingRequiredKey(key)

        if not data.get("log"):
            data["log"] = get_logger()

        if data.get("env") is None:
            data["env"] = os.environ.copy()

        if "system_settings" not in data:
            data["system_settings"] = get_system_settings()

        super(EnvironmentPrepData, self).__init__(data)


def get_app_environments_for_context(
    project_name,
    asset_name,
    task_name,
    app_name,
    env_group=None,
    launch_type=None,
    env=None,
    modules_manager=None
):
    """Prepare environment variables by context.
    Args:
        project_name (str): Name of project.
        asset_name (str): Name of asset.
        task_name (str): Name of task.
        app_name (str): Name of application that is launched and can be found
            by ApplicationManager.
        env_group (Optional[str]): Name of environment group. If not passed
            default group is used.
        launch_type (Optional[str]): Type for which prelaunch hooks are
            executed.
        env (Optional[dict[str, str]]): Initial environment variables.
            `os.environ` is used when not passed.
        modules_manager (Optional[ModulesManager]): Initialized modules
            manager.

    Returns:
        dict: Environments for passed context and application.
    """

    # Prepare app object which can be obtained only from ApplicationManager
    app_manager = ApplicationManager()
    context = app_manager.create_launch_context(
        app_name,
        project_name=project_name,
        asset_name=asset_name,
        task_name=task_name,
        env_group=env_group,
        launch_type=launch_type,
        env=env,
        modules_manager=modules_manager,
    )
    context.run_prelaunch_hooks()
    return context.env


def _merge_env(env, current_env):
    """Modified function(merge) from acre module."""
    import acre

    result = current_env.copy()
    for key, value in env.items():
        # Keep missing keys by not filling `missing` kwarg
        value = acre.lib.partial_format(value, data=current_env)
        result[key] = value
    return result


def _add_python_version_paths(app, env, logger, modules_manager):
    """Add vendor packages specific for a Python version."""

    for module in modules_manager.get_enabled_modules():
        module.modify_application_launch_arguments(app, env)

    # Skip adding if host name is not set
    if not app.host_name:
        return

    # Add Python 2/3 modules
    python_vendor_dir = os.path.join(
        PACKAGE_DIR,
        "vendor",
        "python"
    )
    if app.use_python_2:
        pythonpath = os.path.join(python_vendor_dir, "python_2")
    else:
        pythonpath = os.path.join(python_vendor_dir, "python_3")

    if not os.path.exists(pythonpath):
        return

    logger.debug("Adding Python version specific paths to PYTHONPATH")
    python_paths = [pythonpath]

    # Load PYTHONPATH from current launch context
    python_path = env.get("PYTHONPATH")
    if python_path:
        python_paths.append(python_path)

    # Set new PYTHONPATH to launch context environments
    env["PYTHONPATH"] = os.pathsep.join(python_paths)


def prepare_app_environments(
    data, env_group=None, implementation_envs=True, modules_manager=None
):
    """Modify launch environments based on launched app and context.

    Args:
        data (EnvironmentPrepData): Dictionary where result and intermediate
            result will be stored.
    """
    import acre

    app = data["app"]
    log = data["log"]
    source_env = data["env"].copy()

    if modules_manager is None:
        from openpype.modules import ModulesManager

        modules_manager = ModulesManager()

    _add_python_version_paths(app, source_env, log, modules_manager)

    # Use environments from local settings
    filtered_local_envs = {}
    system_settings = data["system_settings"]
    whitelist_envs = system_settings["general"].get("local_env_white_list")
    if whitelist_envs:
        local_settings = get_local_settings()
        local_envs = local_settings.get("environments") or {}
        filtered_local_envs = {
            key: value
            for key, value in local_envs.items()
            if key in whitelist_envs
        }

    # Apply local environment variables for already existing values
    for key, value in filtered_local_envs.items():
        if key in source_env:
            source_env[key] = value

    # `app_and_tool_labels` has debug purpose
    app_and_tool_labels = [app.full_name]
    # Environments for application
    environments = [
        app.group.environment,
        app.environment
    ]

    asset_doc = data.get("asset_doc")
    # Add tools environments
    groups_by_name = {}
    tool_by_group_name = collections.defaultdict(dict)
    if asset_doc:
        # Make sure each tool group can be added only once
        for key in asset_doc["data"].get("tools_env") or []:
            tool = app.manager.tools.get(key)
            if not tool or not tool.is_valid_for_app(app):
                continue
            groups_by_name[tool.group.name] = tool.group
            tool_by_group_name[tool.group.name][tool.name] = tool

        for group_name in sorted(groups_by_name.keys()):
            group = groups_by_name[group_name]
            environments.append(group.environment)
            for tool_name in sorted(tool_by_group_name[group_name].keys()):
                tool = tool_by_group_name[group_name][tool_name]
                environments.append(tool.environment)
                app_and_tool_labels.append(tool.full_name)

    log.debug(
        "Will add environments for apps and tools: {}".format(
            ", ".join(app_and_tool_labels)
        )
    )

    env_values = {}
    for _env_values in environments:
        if not _env_values:
            continue

        # Choose right platform
        tool_env = parse_environments(_env_values, env_group)

        # Apply local environment variables
        # - must happen between all values because they may be used during
        #   merge
        for key, value in filtered_local_envs.items():
            if key in tool_env:
                tool_env[key] = value

        # Merge dictionaries
        env_values = _merge_env(tool_env, env_values)

    merged_env = _merge_env(env_values, source_env)

    loaded_env = acre.compute(merged_env, cleanup=False)

    final_env = None
    # Add host specific environments
    if app.host_name and implementation_envs:
        host_module = modules_manager.get_host_module(app.host_name)
        if not host_module:
            module = __import__("openpype.hosts", fromlist=[app.host_name])
            host_module = getattr(module, app.host_name, None)
        add_implementation_envs = None
        if host_module:
            add_implementation_envs = getattr(
                host_module, "add_implementation_envs", None
            )
        if add_implementation_envs:
            # Function may only modify passed dict without returning value
            final_env = add_implementation_envs(loaded_env, app)

    if final_env is None:
        final_env = loaded_env

    keys_to_remove = set(source_env.keys()) - set(final_env.keys())

    # Update env
    data["env"].update(final_env)
    for key in keys_to_remove:
        data["env"].pop(key, None)


def apply_project_environments_value(
    project_name, env, project_settings=None, env_group=None
):
    """Apply project specific environments on passed environments.

    The environments are applied on passed `env` argument value so it is not
    required to apply changes back.

    Args:
        project_name (str): Name of project for which environments should be
            received.
        env (dict): Environment values on which project specific environments
            will be applied.
        project_settings (dict): Project settings for passed project name.
            Optional if project settings are already prepared.

    Returns:
        dict: Passed env values with applied project environments.

    Raises:
        KeyError: If project settings do not contain keys for project specific
            environments.
    """
    import acre

    if project_settings is None:
        project_settings = get_project_settings(project_name)

    env_value = project_settings["global"]["project_environments"]
    if env_value:
        parsed_value = parse_environments(env_value, env_group)
        env.update(acre.compute(
            _merge_env(parsed_value, env),
            cleanup=False
        ))
    return env


def prepare_context_environments(data, env_group=None, modules_manager=None):
    """Modify launch environments with context data for launched host.

    Args:
        data (EnvironmentPrepData): Dictionary where result and intermediate
            result will be stored.
    """

    from openpype.pipeline.template_data import get_template_data

    # Context environments
    log = data["log"]

    project_doc = data["project_doc"]
    asset_doc = data["asset_doc"]
    task_name = data["task_name"]
    if not project_doc:
        log.info(
            "Skipping context environments preparation."
            " Launch context does not contain required data."
        )
        return

    # Load project specific environments
    project_name = project_doc["name"]
    project_settings = get_project_settings(project_name)
    system_settings = get_system_settings()
    data["project_settings"] = project_settings
    data["system_settings"] = system_settings

    app = data["app"]
    context_env = {
        "AVALON_PROJECT": project_doc["name"],
        "AVALON_APP_NAME": app.full_name
    }
    if asset_doc:
        asset_name = get_asset_name_identifier(asset_doc)
        context_env["AVALON_ASSET"] = asset_name

        if task_name:
            context_env["AVALON_TASK"] = task_name

    log.debug(
        "Context environments set:\n{}".format(
            json.dumps(context_env, indent=4)
        )
    )
    data["env"].update(context_env)

    # Apply project specific environments on current env value
    # - apply them once the context environments are set
    apply_project_environments_value(
        project_name, data["env"], project_settings, env_group
    )

    if not app.is_host:
        return

    data["env"]["AVALON_APP"] = app.host_name

    if not asset_doc or not task_name:
        # QUESTION replace with log.info and skip workfile discovery?
        # - technically it should be possible to launch host without context
        raise ApplicationLaunchFailed(
            "Host launch require asset and task context."
        )

    workdir_data = get_template_data(
        project_doc, asset_doc, task_name, app.host_name, system_settings
    )
    data["workdir_data"] = workdir_data

    anatomy = data["anatomy"]

    task_type = workdir_data["task"]["type"]
    # Temp solution how to pass task type to `_prepare_last_workfile`
    data["task_type"] = task_type

    try:
        from openpype.pipeline.workfile import get_workdir_with_workdir_data

        workdir = get_workdir_with_workdir_data(
            workdir_data,
            anatomy.project_name,
            anatomy,
            project_settings=project_settings
        )

    except Exception as exc:
        raise ApplicationLaunchFailed(
            "Error in anatomy.format: {}".format(str(exc))
        )

    if not os.path.exists(workdir):
        log.debug(
            "Creating workdir folder: \"{}\"".format(workdir)
        )
        try:
            os.makedirs(workdir)
        except Exception as exc:
            raise ApplicationLaunchFailed(
                "Couldn't create workdir because: {}".format(str(exc))
            )

    data["env"]["AVALON_WORKDIR"] = workdir

    _prepare_last_workfile(data, workdir, modules_manager)


def _prepare_last_workfile(data, workdir, modules_manager):
    """last workfile workflow preparation.

    Function check if should care about last workfile workflow and tries
    to find the last workfile. Both information are stored to `data` and
    environments.

    Last workfile is filled always (with version 1) even if any workfile
    exists yet.

    Args:
        data (EnvironmentPrepData): Dictionary where result and intermediate
            result will be stored.
        workdir (str): Path to folder where workfiles should be stored.
    """

    from openpype.modules import ModulesManager
    from openpype.pipeline import HOST_WORKFILE_EXTENSIONS

    if not modules_manager:
        modules_manager = ModulesManager()

    log = data["log"]

    _workdir_data = data.get("workdir_data")
    if not _workdir_data:
        log.info(
            "Skipping last workfile preparation."
            " Key `workdir_data` not filled."
        )
        return

    app = data["app"]
    workdir_data = copy.deepcopy(_workdir_data)
    project_name = data["project_name"]
    task_name = data["task_name"]
    task_type = data["task_type"]

    start_last_workfile = data.get("start_last_workfile")
    if start_last_workfile is None:
        start_last_workfile = should_start_last_workfile(
            project_name, app.host_name, task_name, task_type
        )
    else:
        log.info("Opening of last workfile was disabled by user")

    data["start_last_workfile"] = start_last_workfile

    workfile_startup = should_workfile_tool_start(
        project_name, app.host_name, task_name, task_type
    )
    data["workfile_startup"] = workfile_startup

    # Store boolean as "0"(False) or "1"(True)
    data["env"]["AVALON_OPEN_LAST_WORKFILE"] = (
        str(int(bool(start_last_workfile)))
    )
    data["env"]["OPENPYPE_WORKFILE_TOOL_ON_START"] = (
        str(int(bool(workfile_startup)))
    )

    _sub_msg = "" if start_last_workfile else " not"
    log.debug(
        "Last workfile should{} be opened on start.".format(_sub_msg)
    )

    # Last workfile path
    last_workfile_path = data.get("last_workfile_path") or ""
    if not last_workfile_path:
        host_module = modules_manager.get_host_module(app.host_name)
        if host_module:
            extensions = host_module.get_workfile_extensions()
        else:
            extensions = HOST_WORKFILE_EXTENSIONS.get(app.host_name)

        if extensions:
            from openpype.pipeline.workfile import (
                get_workfile_template_key,
                get_last_workfile
            )

            anatomy = data["anatomy"]
            project_settings = data["project_settings"]
            task_type = workdir_data["task"]["type"]
            template_key = get_workfile_template_key(
                task_type,
                app.host_name,
                project_name,
                project_settings=project_settings
            )
            # Find last workfile
            file_template = str(anatomy.templates[template_key]["file"])

            workdir_data.update({
                "version": 1,
                "user": get_openpype_username(),
                "ext": extensions[0]
            })

            last_workfile_path = get_last_workfile(
                workdir, file_template, workdir_data, extensions, True
            )

    if os.path.exists(last_workfile_path):
        log.debug((
            "Workfiles for launch context does not exists"
            " yet but path will be set."
        ))
    log.debug(
        "Setting last workfile path: {}".format(last_workfile_path)
    )

    data["env"]["AVALON_LAST_WORKFILE"] = last_workfile_path
    data["last_workfile_path"] = last_workfile_path


def should_start_last_workfile(
    project_name, host_name, task_name, task_type, default_output=False
):
    """Define if host should start last version workfile if possible.

    Default output is `False`. Can be overridden with environment variable
    `AVALON_OPEN_LAST_WORKFILE`, valid values without case sensitivity are
    `"0", "1", "true", "false", "yes", "no"`.

    Args:
        project_name (str): Name of project.
        host_name (str): Name of host which is launched. In avalon's
            application context it's value stored in app definition under
            key `"application_dir"`. Is not case sensitive.
        task_name (str): Name of task which is used for launching the host.
            Task name is not case sensitive.

    Returns:
        bool: True if host should start workfile.

    """

    project_settings = get_project_settings(project_name)
    profiles = (
        project_settings
        ["global"]
        ["tools"]
        ["Workfiles"]
        ["last_workfile_on_startup"]
    )

    if not profiles:
        return default_output

    filter_data = {
        "tasks": task_name,
        "task_types": task_type,
        "hosts": host_name
    }
    matching_item = filter_profiles(profiles, filter_data)

    output = None
    if matching_item:
        output = matching_item.get("enabled")

    if output is None:
        return default_output
    return output


def should_workfile_tool_start(
    project_name, host_name, task_name, task_type, default_output=False
):
    """Define if host should start workfile tool at host launch.

    Default output is `False`. Can be overridden with environment variable
    `OPENPYPE_WORKFILE_TOOL_ON_START`, valid values without case sensitivity are
    `"0", "1", "true", "false", "yes", "no"`.

    Args:
        project_name (str): Name of project.
        host_name (str): Name of host which is launched. In avalon's
            application context it's value stored in app definition under
            key `"application_dir"`. Is not case sensitive.
        task_name (str): Name of task which is used for launching the host.
            Task name is not case sensitive.

    Returns:
        bool: True if host should start workfile.

    """

    project_settings = get_project_settings(project_name)
    profiles = (
        project_settings
        ["global"]
        ["tools"]
        ["Workfiles"]
        ["open_workfile_tool_on_startup"]
    )

    if not profiles:
        return default_output

    filter_data = {
        "tasks": task_name,
        "task_types": task_type,
        "hosts": host_name
    }
    matching_item = filter_profiles(profiles, filter_data)

    output = None
    if matching_item:
        output = matching_item.get("enabled")

    if output is None:
        return default_output
    return output


def get_non_python_host_kwargs(kwargs, allow_console=True):
    """Explicit setting of kwargs for Popen for AE/PS/Harmony.

    Expected behavior
    - openpype_console opens window with logs
    - openpype_gui has stdout/stderr available for capturing

    Args:
        kwargs (dict) or None
        allow_console (bool): use False for inner Popen opening app itself or
           it will open additional console (at least for Harmony)
    """

    if kwargs is None:
        kwargs = {}

    if platform.system().lower() != "windows":
        return kwargs

    if AYON_SERVER_ENABLED:
        executable_path = os.environ.get("AYON_EXECUTABLE")
    else:
        executable_path = os.environ.get("OPENPYPE_EXECUTABLE")

    executable_filename = ""
    if executable_path:
        executable_filename = os.path.basename(executable_path)

    if AYON_SERVER_ENABLED:
        is_gui_executable = "ayon_console" not in executable_filename
    else:
        is_gui_executable = "openpype_gui" in executable_filename

    if is_gui_executable:
        kwargs.update({
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL
        })
    elif allow_console:
        kwargs.update({
            "creationflags": subprocess.CREATE_NEW_CONSOLE
        })
    return kwargs
