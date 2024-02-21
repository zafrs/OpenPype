# -*- coding: utf-8 -*-
"""Base class for AYON addons."""
import copy
import os
import sys
import json
import time
import inspect
import logging
import platform
import threading
import collections
import traceback

from uuid import uuid4
from abc import ABCMeta, abstractmethod

import six
import appdirs

from openpype import AYON_SERVER_ENABLED
from openpype.client import get_ayon_server_api_connection
from openpype.settings import (
    get_system_settings,
    SYSTEM_SETTINGS_KEY,
    PROJECT_SETTINGS_KEY,
    SCHEMA_KEY_SYSTEM_SETTINGS,
    SCHEMA_KEY_PROJECT_SETTINGS
)

from openpype.settings.lib import (
    get_studio_system_settings_overrides,
    load_json_file,
)
from openpype.settings.ayon_settings import (
    is_dev_mode_enabled,
    get_ayon_settings,
)

from openpype.lib import (
    Logger,
    import_filepath,
    import_module_from_dirpath,
)

from .interfaces import (
    OpenPypeInterface,
    IPluginPaths,
    IHostAddon,
    ITrayModule,
    ITrayService
)

# Files that will be always ignored on addons import
IGNORED_FILENAMES = (
    "__pycache__",
)
# Files ignored on addons import from "./openpype/modules"
IGNORED_DEFAULT_FILENAMES = (
    "__init__.py",
    "base.py",
    "interfaces.py",
    "example_addons",
    "default_modules",
)
# Addons that won't be loaded in AYON mode from "./openpype/modules"
# - the same addons are ignored in "./server_addon/create_ayon_addons.py"
IGNORED_FILENAMES_IN_AYON = {
    "ftrack",
    "shotgrid",
    "sync_server",
    "slack",
    "kitsu",
}
IGNORED_HOSTS_IN_AYON = {
    "flame",
    "harmony",
}


# Inherit from `object` for Python 2 hosts
class _ModuleClass(object):
    """Fake module class for storing OpenPype modules.

    Object of this class can be stored to `sys.modules` and used for storing
    dynamically imported modules.
    """

    def __init__(self, name):
        # Call setattr on super class
        super(_ModuleClass, self).__setattr__("name", name)
        super(_ModuleClass, self).__setattr__("__name__", name)

        # Where modules and interfaces are stored
        super(_ModuleClass, self).__setattr__("__attributes__", dict())
        super(_ModuleClass, self).__setattr__("__defaults__", set())

        super(_ModuleClass, self).__setattr__("_log", None)

    def __getattr__(self, attr_name):
        if attr_name not in self.__attributes__:
            if attr_name in ("__path__", "__file__"):
                return None
            raise AttributeError("'{}' has not attribute '{}'".format(
                self.name, attr_name
            ))
        return self.__attributes__[attr_name]

    def __iter__(self):
        for module in self.values():
            yield module

    def __setattr__(self, attr_name, value):
        if attr_name in self.__attributes__:
            self.log.warning(
                "Duplicated name \"{}\" in {}. Overriding.".format(
                    attr_name, self.name
                )
            )
        self.__attributes__[attr_name] = value

    def __setitem__(self, key, value):
        self.__setattr__(key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    @property
    def log(self):
        if self._log is None:
            super(_ModuleClass, self).__setattr__(
                "_log", Logger.get_logger(self.name)
            )
        return self._log

    def get(self, key, default=None):
        return self.__attributes__.get(key, default)

    def keys(self):
        return self.__attributes__.keys()

    def values(self):
        return self.__attributes__.values()

    def items(self):
        return self.__attributes__.items()


class _InterfacesClass(_ModuleClass):
    """Fake module class for storing OpenPype interfaces.

    MissingInterface object is returned if interfaces does not exists.
    - this is because interfaces must be available even if are missing
        implementation
    """

    def __getattr__(self, attr_name):
        if attr_name not in self.__attributes__:
            if attr_name in ("__path__", "__file__"):
                return None

            raise AttributeError((
                "cannot import name '{}' from 'openpype_interfaces'"
            ).format(attr_name))

        if _LoadCache.interfaces_loaded and attr_name != "log":
            stack = list(traceback.extract_stack())
            stack.pop(-1)
            self.log.warning((
                "Using deprecated import of \"{}\" from 'openpype_interfaces'."
                " Please switch to use import"
                " from 'openpype.modules.interfaces'"
                " (will be removed after 3.16.x).{}"
            ).format(attr_name, "".join(traceback.format_list(stack))))
        return self.__attributes__[attr_name]


class _LoadCache:
    interfaces_lock = threading.Lock()
    modules_lock = threading.Lock()
    interfaces_loaded = False
    modules_loaded = False


def get_default_modules_dir():
    """Path to default OpenPype modules."""

    current_dir = os.path.dirname(os.path.abspath(__file__))

    output = []
    for folder_name in ("default_modules", ):
        path = os.path.join(current_dir, folder_name)
        if os.path.exists(path) and os.path.isdir(path):
            output.append(path)

    return output


def get_dynamic_modules_dirs():
    """Possible paths to OpenPype Addons of Modules.

    Paths are loaded from studio settings under:
        `modules -> addon_paths -> {platform name}`

    Path may contain environment variable as a formatting string.

    They are not validated or checked their existence.

    Returns:
        list: Paths loaded from studio overrides.
    """

    output = []
    if AYON_SERVER_ENABLED:
        return output

    value = get_studio_system_settings_overrides()
    for key in ("modules", "addon_paths", platform.system().lower()):
        if key not in value:
            return output
        value = value[key]

    for path in value:
        if not path:
            continue

        try:
            path = path.format(**os.environ)
        except Exception:
            pass
        output.append(path)
    return output


def get_module_dirs():
    """List of paths where OpenPype modules can be found."""
    _dirpaths = []
    _dirpaths.extend(get_default_modules_dir())
    _dirpaths.extend(get_dynamic_modules_dirs())

    dirpaths = []
    for path in _dirpaths:
        if not path:
            continue
        normalized = os.path.normpath(path)
        if normalized not in dirpaths:
            dirpaths.append(normalized)
    return dirpaths


def load_interfaces(force=False):
    """Load interfaces from modules into `openpype_interfaces`.

    Only classes which inherit from `OpenPypeInterface` are loaded and stored.

    Args:
        force(bool): Force to load interfaces even if are already loaded.
            This won't update already loaded and used (cached) interfaces.
    """

    if _LoadCache.interfaces_loaded and not force:
        return

    if not _LoadCache.interfaces_lock.locked():
        with _LoadCache.interfaces_lock:
            _load_interfaces()
            _LoadCache.interfaces_loaded = True
    else:
        # If lock is locked wait until is finished
        while _LoadCache.interfaces_lock.locked():
            time.sleep(0.1)


def _load_interfaces():
    # Key under which will be modules imported in `sys.modules`
    modules_key = "openpype_interfaces"

    sys.modules[modules_key] = openpype_interfaces = (
        _InterfacesClass(modules_key)
    )

    from . import interfaces

    for attr_name in dir(interfaces):
        attr = getattr(interfaces, attr_name)
        if (
            not inspect.isclass(attr)
            or attr is OpenPypeInterface
            or not issubclass(attr, OpenPypeInterface)
        ):
            continue
        setattr(openpype_interfaces, attr_name, attr)


def load_modules(force=False):
    """Load OpenPype modules as python modules.

    Modules does not load only classes (like in Interfaces) because there must
    be ability to use inner code of module and be able to import it from one
    defined place.

    With this it is possible to import module's content from predefined module.

    Function makes sure that `load_interfaces` was triggered. Modules import
    has specific order which can't be changed.

    Args:
        force(bool): Force to load modules even if are already loaded.
            This won't update already loaded and used (cached) modules.
    """

    if _LoadCache.modules_loaded and not force:
        return

    # First load interfaces
    # - modules must not be imported before interfaces
    load_interfaces(force)

    if not _LoadCache.modules_lock.locked():
        with _LoadCache.modules_lock:
            _load_modules()
            _LoadCache.modules_loaded = True
    else:
        # If lock is locked wait until is finished
        while _LoadCache.modules_lock.locked():
            time.sleep(0.1)


def _get_ayon_bundle_data():
    con = get_ayon_server_api_connection()
    bundles = con.get_bundles()["bundles"]

    bundle_name = os.getenv("AYON_BUNDLE_NAME")

    return next(
        (
            bundle
            for bundle in bundles
            if bundle["name"] == bundle_name
        ),
        None
    )


def _get_ayon_addons_information(bundle_info):
    """Receive information about addons to use from server.

    Todos:
        Actually ask server for the information.
        Allow project name as optional argument to be able to query information
            about used addons for specific project.

    Returns:
        List[Dict[str, Any]]: List of addon information to use.
    """

    output = []
    bundle_addons = bundle_info["addons"]
    con = get_ayon_server_api_connection()
    addons = con.get_addons_info()["addons"]
    for addon in addons:
        name = addon["name"]
        versions = addon.get("versions")
        addon_version = bundle_addons.get(name)
        if addon_version is None or not versions:
            continue
        version = versions.get(addon_version)
        if version:
            version = copy.deepcopy(version)
            version["name"] = name
            version["version"] = addon_version
            output.append(version)
    return output


def _load_ayon_addons(openpype_modules, modules_key, log):
    """Load AYON addons based on information from server.

    This function should not trigger downloading of any addons but only use
    what is already available on the machine (at least in first stages of
    development).

    Args:
        openpype_modules (_ModuleClass): Module object where modules are
            stored.
        log (logging.Logger): Logger object.

    Returns:
        List[str]: List of v3 addons to skip to load because v4 alternative is
            imported.
    """

    v3_addons_to_skip = []

    bundle_info = _get_ayon_bundle_data()
    addons_info = _get_ayon_addons_information(bundle_info)
    if not addons_info:
        return v3_addons_to_skip

    addons_dir = os.environ.get("AYON_ADDONS_DIR")
    if not addons_dir:
        addons_dir = os.path.join(
            appdirs.user_data_dir("AYON", "Ynput"),
            "addons"
        )

    dev_mode_enabled = is_dev_mode_enabled()
    dev_addons_info = {}
    if dev_mode_enabled:
        # Get dev addons info only when dev mode is enabled
        dev_addons_info = bundle_info.get("addonDevelopment", dev_addons_info)

    addons_dir_exists = os.path.exists(addons_dir)
    if not addons_dir_exists:
        log.warning("Addons directory does not exists. Path \"{}\"".format(
            addons_dir
        ))

    for addon_info in addons_info:
        addon_name = addon_info["name"]
        addon_version = addon_info["version"]

        # OpenPype addon does not have any addon object
        if addon_name == "openpype":
            continue

        dev_addon_info = dev_addons_info.get(addon_name, {})
        use_dev_path = dev_addon_info.get("enabled", False)

        addon_dir = None
        if use_dev_path:
            addon_dir = dev_addon_info["path"]
            if not addon_dir or not os.path.exists(addon_dir):
                log.warning((
                    "Dev addon {} {} path does not exists. Path \"{}\""
                ).format(addon_name, addon_version, addon_dir))
                continue

        elif addons_dir_exists:
            folder_name = "{}_{}".format(addon_name, addon_version)
            addon_dir = os.path.join(addons_dir, folder_name)
            if not os.path.exists(addon_dir):
                log.debug((
                    "No localized client code found for addon {} {}."
                ).format(addon_name, addon_version))
                continue

        if not addon_dir:
            continue

        sys.path.insert(0, addon_dir)
        imported_modules = []
        for name in os.listdir(addon_dir):
            # Ignore of files is implemented to be able to run code from code
            #   where usually is more files than just the addon
            # Ignore start and setup scripts
            if name in ("setup.py", "start.py", "__pycache__"):
                continue

            path = os.path.join(addon_dir, name)
            basename, ext = os.path.splitext(name)
            # Ignore folders/files with dot in name
            #   - dot names cannot be imported in Python
            if "." in basename:
                continue
            is_dir = os.path.isdir(path)
            is_py_file = ext.lower() == ".py"
            if not is_py_file and not is_dir:
                continue

            try:
                mod = __import__(basename, fromlist=("",))
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        inspect.isclass(attr)
                        and issubclass(attr, AYONAddon)
                    ):
                        imported_modules.append(mod)
                        break

            except BaseException:
                log.warning(
                    "Failed to import \"{}\"".format(basename),
                    exc_info=True
                )

        if not imported_modules:
            log.warning("Addon {} {} has no content to import".format(
                addon_name, addon_version
            ))
            continue

        if len(imported_modules) > 1:
            log.warning((
                "Skipping addon '{}'."
                " Multiple modules were found ({}) in dir {}."
            ).format(
                addon_name,
                ", ".join([m.__name__ for m in imported_modules]),
                addon_dir,
            ))
            continue

        mod = imported_modules[0]
        addon_alias = getattr(mod, "V3_ALIAS", None)
        if not addon_alias:
            addon_alias = addon_name
        v3_addons_to_skip.append(addon_alias)
        new_import_str = "{}.{}".format(modules_key, addon_alias)

        sys.modules[new_import_str] = mod
        setattr(openpype_modules, addon_alias, mod)

    return v3_addons_to_skip


def _load_modules():
    # Key under which will be modules imported in `sys.modules`
    modules_key = "openpype_modules"

    # Change `sys.modules`
    sys.modules[modules_key] = openpype_modules = _ModuleClass(modules_key)

    log = Logger.get_logger("ModulesLoader")

    ignore_addon_names = []
    if AYON_SERVER_ENABLED:
        ignore_addon_names = _load_ayon_addons(
            openpype_modules, modules_key, log
        )

    # Look for OpenPype modules in paths defined with `get_module_dirs`
    #   - dynamically imported OpenPype modules and addons
    module_dirs = get_module_dirs()

    # Add current directory at first place
    #   - has small differences in import logic
    current_dir = os.path.abspath(os.path.dirname(__file__))
    hosts_dir = os.path.join(os.path.dirname(current_dir), "hosts")
    module_dirs.insert(0, hosts_dir)
    module_dirs.insert(0, current_dir)

    addons_dir = os.path.join(os.path.dirname(current_dir), "addons")
    if os.path.exists(addons_dir):
        module_dirs.append(addons_dir)

    ignored_host_names = set(IGNORED_HOSTS_IN_AYON)
    ignored_current_dir_filenames = set(IGNORED_DEFAULT_FILENAMES)
    if AYON_SERVER_ENABLED:
        ignored_current_dir_filenames |= IGNORED_FILENAMES_IN_AYON

    processed_paths = set()
    for dirpath in frozenset(module_dirs):
        # Skip already processed paths
        if dirpath in processed_paths:
            continue
        processed_paths.add(dirpath)

        if not os.path.exists(dirpath):
            log.warning((
                "Could not find path when loading OpenPype modules \"{}\""
            ).format(dirpath))
            continue

        is_in_current_dir = dirpath == current_dir
        is_in_host_dir = dirpath == hosts_dir

        for filename in os.listdir(dirpath):
            # Ignore filenames
            if filename in IGNORED_FILENAMES:
                continue

            if (
                is_in_current_dir
                and filename in ignored_current_dir_filenames
            ):
                continue

            if (
                is_in_host_dir
                and filename in ignored_host_names
            ):
                continue

            fullpath = os.path.join(dirpath, filename)
            basename, ext = os.path.splitext(filename)

            if basename in ignore_addon_names:
                continue

            # Validations
            if os.path.isdir(fullpath):
                # Check existence of init file
                init_path = os.path.join(fullpath, "__init__.py")
                if not os.path.exists(init_path):
                    log.debug((
                        "Module directory does not contain __init__.py"
                        " file {}"
                    ).format(fullpath))
                    continue

            elif ext not in (".py", ):
                continue

            # TODO add more logic how to define if folder is module or not
            # - check manifest and content of manifest
            try:
                # Don't import dynamically current directory modules
                if is_in_current_dir:
                    import_str = "openpype.modules.{}".format(basename)
                    new_import_str = "{}.{}".format(modules_key, basename)
                    default_module = __import__(import_str, fromlist=("", ))
                    sys.modules[new_import_str] = default_module
                    setattr(openpype_modules, basename, default_module)

                elif is_in_host_dir:
                    import_str = "openpype.hosts.{}".format(basename)
                    new_import_str = "{}.{}".format(modules_key, basename)
                    # Until all hosts are converted to be able use them as
                    #   modules is this error check needed
                    try:
                        default_module = __import__(
                            import_str, fromlist=("", )
                        )
                        sys.modules[new_import_str] = default_module
                        setattr(openpype_modules, basename, default_module)

                    except Exception:
                        log.warning(
                            "Failed to import host folder {}".format(basename),
                            exc_info=True
                        )

                elif os.path.isdir(fullpath):
                    import_module_from_dirpath(dirpath, filename, modules_key)

                else:
                    module = import_filepath(fullpath)
                    setattr(openpype_modules, basename, module)

            except Exception:
                if is_in_current_dir:
                    msg = "Failed to import default module '{}'.".format(
                        basename
                    )
                else:
                    msg = "Failed to import module '{}'.".format(fullpath)
                log.error(msg, exc_info=True)


@six.add_metaclass(ABCMeta)
class AYONAddon(object):
    """Base class of AYON addon.

    Attributes:
        id (UUID): Addon object id.
        enabled (bool): Is addon enabled.
        name (str): Addon name.

    Args:
        manager (ModulesManager): Manager object who discovered addon.
        settings (dict[str, Any]): AYON settings.
    """

    enabled = True
    _id = None

    def __init__(self, manager, settings):
        self.manager = manager

        self.log = Logger.get_logger(self.name)

        self.initialize(settings)

    @property
    def id(self):
        """Random id of addon object.

        Returns:
            str: Object id.
        """

        if self._id is None:
            self._id = uuid4()
        return self._id

    @property
    @abstractmethod
    def name(self):
        """Addon name.

        Returns:
            str: Addon name.
        """

        pass

    def initialize(self, settings):
        """Initialization of module attributes.

        It is not recommended to override __init__ that's why specific method
        was implemented.

        Args:
            settings (dict[str, Any]): Settings.
        """

        pass

    def connect_with_modules(self, enabled_addons):
        """Connect with other enabled addons.

        Args:
            enabled_addons (list[AYONAddon]): Addons that are enabled.
        """

        pass

    def get_global_environments(self):
        """Get global environments values of module.

        Environment variables that can be get only from system settings.

        Returns:
            dict[str, str]: Environment variables.
        """

        return {}

    def modify_application_launch_arguments(self, application, env):
        """Give option to modify launch environments before application launch.

        Implementation is optional. To change environments modify passed
        dictionary of environments.

        Args:
            application (Application): Application that is launched.
            env (dict[str, str]): Current environment variables.
        """

        pass

    def on_host_install(self, host, host_name, project_name):
        """Host was installed which gives option to handle in-host logic.

        It is a good option to register in-host event callbacks which are
        specific for the module. The module is kept in memory for rest of
        the process.

        Arguments may change in future. E.g. 'host_name' should be possible
        to receive from 'host' object.

        Args:
            host (Union[ModuleType, HostBase]): Access to installed/registered
                host object.
            host_name (str): Name of host.
            project_name (str): Project name which is main part of host
                context.
        """

        pass

    def cli(self, module_click_group):
        """Add commands to click group.

        The best practise is to create click group for whole module which is
        used to separate commands.

        Example:
            class MyPlugin(AYONAddon):
                ...
                def cli(self, module_click_group):
                    module_click_group.add_command(cli_main)


            @click.group(<module name>, help="<Any help shown in cmd>")
            def cli_main():
                pass

            @cli_main.command()
            def mycommand():
                print("my_command")

        Args:
            module_click_group (click.Group): Group to which can be added
                commands.
        """

        pass


class OpenPypeModule(AYONAddon):
    """Base class of OpenPype module.

    Instead of 'AYONAddon' are passed in module settings.

    Args:
        manager (ModulesManager): Manager object who discovered addon.
        settings (dict[str, Any]): OpenPype settings.
    """

    # Disable by default
    enabled = False


class OpenPypeAddOn(OpenPypeModule):
    # Enable Addon by default
    enabled = True


class ModulesManager:
    """Manager of Pype modules helps to load and prepare them to work.

    Args:
        system_settings (Optional[dict[str, Any]]): OpenPype system settings.
        ayon_settings (Optional[dict[str, Any]]): AYON studio settings.
    """

    # Helper attributes for report
    _report_total_key = "Total"
    _system_settings = None
    _ayon_settings = None

    def __init__(self, system_settings=None, ayon_settings=None):
        self.log = logging.getLogger(self.__class__.__name__)

        self._system_settings = system_settings
        self._ayon_settings = ayon_settings

        self.modules = []
        self.modules_by_id = {}
        self.modules_by_name = {}
        # For report of time consumption
        self._report = {}

        self.initialize_modules()
        self.connect_modules()

    def __getitem__(self, module_name):
        return self.modules_by_name[module_name]

    def get(self, module_name, default=None):
        """Access module by name.

        Args:
            module_name (str): Name of module which should be returned.
            default (Any): Default output if module is not available.

        Returns:
            Union[AYONAddon, None]: Module found by name or None.
        """

        return self.modules_by_name.get(module_name, default)

    def get_enabled_module(self, module_name, default=None):
        """Fast access to enabled module.

        If module is available but is not enabled default value is returned.

        Args:
            module_name (str): Name of module which should be returned.
            default (Any): Default output if module is not available or is
                not enabled.

        Returns:
            Union[AYONAddon, None]: Enabled module found by name or None.
        """

        module = self.get(module_name)
        if module is not None and module.enabled:
            return module
        return default

    def initialize_modules(self):
        """Import and initialize modules."""
        # Make sure modules are loaded
        load_modules()

        import openpype_modules

        self.log.debug("*** {} initialization.".format(
            "AYON addons"
            if AYON_SERVER_ENABLED
            else "OpenPype modules"
        ))
        # Prepare settings for modules
        system_settings = self._system_settings
        if system_settings is None:
            system_settings = get_system_settings()

        ayon_settings = self._ayon_settings
        if AYON_SERVER_ENABLED and ayon_settings is None:
            ayon_settings = get_ayon_settings()

        modules_settings = system_settings["modules"]

        report = {}
        time_start = time.time()
        prev_start_time = time_start

        module_classes = []
        for module in openpype_modules:
            # Go through globals in `pype.modules`
            for name in dir(module):
                modules_item = getattr(module, name, None)
                # Filter globals that are not classes which inherit from
                #   AYONAddon
                if (
                    not inspect.isclass(modules_item)
                    or modules_item is AYONAddon
                    or modules_item is OpenPypeModule
                    or modules_item is OpenPypeAddOn
                    or not issubclass(modules_item, AYONAddon)
                ):
                    continue

                # Check if class is abstract (Developing purpose)
                if inspect.isabstract(modules_item):
                    # Find abstract attributes by convention on `abc` module
                    not_implemented = []
                    for attr_name in dir(modules_item):
                        attr = getattr(modules_item, attr_name, None)
                        abs_method = getattr(
                            attr, "__isabstractmethod__", None
                        )
                        if attr and abs_method:
                            not_implemented.append(attr_name)

                    # Log missing implementations
                    self.log.warning((
                        "Skipping abstract Class: {}."
                        " Missing implementations: {}"
                    ).format(name, ", ".join(not_implemented)))
                    continue
                module_classes.append(modules_item)

        for modules_item in module_classes:
            is_openpype_module = issubclass(modules_item, OpenPypeModule)
            settings = (
                modules_settings if is_openpype_module else ayon_settings
            )
            name = modules_item.__name__
            try:
                # Try initialize module
                module = modules_item(self, settings)
                # Store initialized object
                self.modules.append(module)
                self.modules_by_id[module.id] = module
                self.modules_by_name[module.name] = module
                enabled_str = "X"
                if not module.enabled:
                    enabled_str = " "
                self.log.debug("[{}] {}".format(enabled_str, name))

                now = time.time()
                report[module.__class__.__name__] = now - prev_start_time
                prev_start_time = now

            except Exception:
                self.log.warning(
                    "Initialization of module {} failed.".format(name),
                    exc_info=True
                )

        if self._report is not None:
            report[self._report_total_key] = time.time() - time_start
            self._report["Initialization"] = report

    def connect_modules(self):
        """Trigger connection with other enabled modules.

        Modules should handle their interfaces in `connect_with_modules`.
        """
        report = {}
        time_start = time.time()
        prev_start_time = time_start
        enabled_modules = self.get_enabled_modules()
        self.log.debug("Has {} enabled modules.".format(len(enabled_modules)))
        for module in enabled_modules:
            try:
                module.connect_with_modules(enabled_modules)
            except Exception:
                self.log.error(
                    "BUG: Module failed on connection with other modules.",
                    exc_info=True
                )

            now = time.time()
            report[module.__class__.__name__] = now - prev_start_time
            prev_start_time = now

        if self._report is not None:
            report[self._report_total_key] = time.time() - time_start
            self._report["Connect modules"] = report

    def get_enabled_modules(self):
        """Enabled modules initialized by the manager.

        Returns:
            list[AYONAddon]: Initialized and enabled modules.
        """

        return [
            module
            for module in self.modules
            if module.enabled
        ]

    def collect_global_environments(self):
        """Helper to collect global environment variabled from modules.

        Returns:
            dict: Global environment variables from enabled modules.

        Raises:
            AssertionError: Global environment variables must be unique for
                all modules.
        """
        module_envs = {}
        for module in self.get_enabled_modules():
            # Collect global module's global environments
            _envs = module.get_global_environments()
            for key, value in _envs.items():
                if key in module_envs:
                    # TODO better error message
                    raise AssertionError(
                        "Duplicated environment key {}".format(key)
                    )
                module_envs[key] = value
        return module_envs

    def collect_plugin_paths(self):
        """Helper to collect all plugins from modules inherited IPluginPaths.

        Unknown keys are logged out.

        Returns:
            dict: Output is dictionary with keys "publish", "create", "load",
                "actions" and "inventory" each containing list of paths.
        """
        # Output structure
        output = {
            "publish": [],
            "create": [],
            "load": [],
            "actions": [],
            "inventory": []
        }
        unknown_keys_by_module = {}
        for module in self.get_enabled_modules():
            # Skip module that do not inherit from `IPluginPaths`
            if not isinstance(module, IPluginPaths):
                continue
            plugin_paths = module.get_plugin_paths()
            for key, value in plugin_paths.items():
                # Filter unknown keys
                if key not in output:
                    if module.name not in unknown_keys_by_module:
                        unknown_keys_by_module[module.name] = []
                    unknown_keys_by_module[module.name].append(key)
                    continue

                # Skip if value is empty
                if not value:
                    continue

                # Convert to list if value is not list
                if not isinstance(value, (list, tuple, set)):
                    value = [value]
                output[key].extend(value)

        # Report unknown keys (Developing purposes)
        if unknown_keys_by_module:
            expected_keys = ", ".join([
                "\"{}\"".format(key) for key in output.keys()
            ])
            msg_template = "Module: \"{}\" - got key {}"
            msg_items = []
            for module_name, keys in unknown_keys_by_module.items():
                joined_keys = ", ".join([
                    "\"{}\"".format(key) for key in keys
                ])
                msg_items.append(msg_template.format(module_name, joined_keys))
            self.log.warning((
                "Expected keys from `get_plugin_paths` are {}. {}"
            ).format(expected_keys, " | ".join(msg_items)))
        return output

    def _collect_plugin_paths(self, method_name, *args, **kwargs):
        output = []
        for module in self.get_enabled_modules():
            # Skip module that do not inherit from `IPluginPaths`
            if not isinstance(module, IPluginPaths):
                continue

            method = getattr(module, method_name)
            try:
                paths = method(*args, **kwargs)
            except Exception:
                self.log.warning(
                    (
                        "Failed to get plugin paths from module"
                        " '{}' using '{}'."
                    ).format(module.__class__.__name__, method_name),
                    exc_info=True
                )
                continue

            if paths:
                # Convert to list if value is not list
                if not isinstance(paths, (list, tuple, set)):
                    paths = [paths]
                output.extend(paths)
        return output

    def collect_create_plugin_paths(self, host_name):
        """Helper to collect creator plugin paths from modules.

        Args:
            host_name (str): For which host are creators meant.

        Returns:
            list: List of creator plugin paths.
        """

        return self._collect_plugin_paths(
            "get_create_plugin_paths",
            host_name
        )

    collect_creator_plugin_paths = collect_create_plugin_paths

    def collect_load_plugin_paths(self, host_name):
        """Helper to collect load plugin paths from modules.

        Args:
            host_name (str): For which host are load plugins meant.

        Returns:
            list: List of load plugin paths.
        """

        return self._collect_plugin_paths(
            "get_load_plugin_paths",
            host_name
        )

    def collect_publish_plugin_paths(self, host_name):
        """Helper to collect load plugin paths from modules.

        Args:
            host_name (str): For which host are load plugins meant.

        Returns:
            list: List of pyblish plugin paths.
        """

        return self._collect_plugin_paths(
            "get_publish_plugin_paths",
            host_name
        )

    def collect_inventory_action_paths(self, host_name):
        """Helper to collect load plugin paths from modules.

        Args:
            host_name (str): For which host are load plugins meant.

        Returns:
            list: List of pyblish plugin paths.
        """

        return self._collect_plugin_paths(
            "get_inventory_action_paths",
            host_name
        )

    def get_host_module(self, host_name):
        """Find host module by host name.

        Args:
            host_name (str): Host name for which is found host module.

        Returns:
            AYONAddon: Found host module by name.
            None: There was not found module inheriting IHostAddon which has
                host name set to passed 'host_name'.
        """

        for module in self.get_enabled_modules():
            if (
                isinstance(module, IHostAddon)
                and module.host_name == host_name
            ):
                return module
        return None

    def get_host_names(self):
        """List of available host names based on host modules.

        Returns:
            Iterable[str]: All available host names based on enabled modules
                inheriting 'IHostAddon'.
        """

        return {
            module.host_name
            for module in self.get_enabled_modules()
            if isinstance(module, IHostAddon)
        }

    def print_report(self):
        """Print out report of time spent on modules initialization parts.

        Reporting is not automated must be implemented for each initialization
        part separatelly. Reports must be stored to `_report` attribute.
        Print is skipped if `_report` is empty.

        Attribute `_report` is dictionary where key is "label" describing
        the processed part and value is dictionary where key is module's
        class name and value is time delta of it's processing.

        It is good idea to add total time delta on processed part under key
        which is defined in attribute `_report_total_key`. By default has value
        `"Total"` but use the attribute please.

        ```javascript
        {
            "Initialization": {
                "FtrackModule": 0.003,
                ...
                "Total": 1.003,
            },
            ...
        }
        ```
        """
        if not self._report:
            return

        available_col_names = set()
        for module_names in self._report.values():
            available_col_names |= set(module_names.keys())

        # Prepare ordered dictionary for columns
        cols = collections.OrderedDict()
        # Add module names to first columnt
        cols["Module name"] = list(sorted(
            module.__class__.__name__
            for module in self.modules
            if module.__class__.__name__ in available_col_names
        ))
        # Add total key (as last module)
        cols["Module name"].append(self._report_total_key)

        # Add columns from report
        for label in self._report.keys():
            cols[label] = []

        total_module_times = {}
        for module_name in cols["Module name"]:
            total_module_times[module_name] = 0

        for label, reported in self._report.items():
            for module_name in cols["Module name"]:
                col_time = reported.get(module_name)
                if col_time is None:
                    cols[label].append("N/A")
                    continue
                cols[label].append("{:.3f}".format(col_time))
                total_module_times[module_name] += col_time

        # Add to also total column that should sum the row
        cols[self._report_total_key] = []
        for module_name in cols["Module name"]:
            cols[self._report_total_key].append(
                "{:.3f}".format(total_module_times[module_name])
            )

        # Prepare column widths and total row count
        # - column width is by
        col_widths = {}
        total_rows = None
        for key, values in cols.items():
            if total_rows is None:
                total_rows = 1 + len(values)
            max_width = len(key)
            for value in values:
                value_length = len(value)
                if value_length > max_width:
                    max_width = value_length
            col_widths[key] = max_width

        rows = []
        for _idx in range(total_rows):
            rows.append([])

        for key, values in cols.items():
            width = col_widths[key]
            idx = 0
            rows[idx].append(key.ljust(width))
            for value in values:
                idx += 1
                rows[idx].append(value.ljust(width))

        filler_parts = []
        for width in col_widths.values():
            filler_parts.append(width * "-")
        filler = "+".join(filler_parts)

        formatted_rows = [filler]
        last_row_idx = len(rows) - 1
        for idx, row in enumerate(rows):
            # Add filler before last row
            if idx == last_row_idx:
                formatted_rows.append(filler)

            formatted_rows.append("|".join(row))

            # Add filler after first row
            if idx == 0:
                formatted_rows.append(filler)

        # Join rows with newline char and add new line at the end
        output = "\n".join(formatted_rows) + "\n"
        print(output)


class TrayModulesManager(ModulesManager):
    # Define order of modules in menu
    modules_menu_order = (
        "user",
        "ftrack",
        "kitsu",
        "launcher_tool",
        "avalon",
        "clockify",
        "standalonepublish_tool",
        "traypublish_tool",
        "log_viewer",
        "local_settings",
        "settings"
    )

    def __init__(self):
        self.log = Logger.get_logger(self.__class__.__name__)

        self.modules = []
        self.modules_by_id = {}
        self.modules_by_name = {}
        self._report = {}

        self.tray_manager = None

        self.doubleclick_callbacks = {}
        self.doubleclick_callback = None

    def add_doubleclick_callback(self, module, callback):
        """Register doubleclick callbacks on tray icon.

        Currently there is no way how to determine which is launched. Name of
        callback can be defined with `doubleclick_callback` attribute.

        Missing feature how to define default callback.

        Args:
            addon (AYONAddon): Addon object.
            callback (FunctionType): Function callback.
        """
        callback_name = "_".join([module.name, callback.__name__])
        if callback_name not in self.doubleclick_callbacks:
            self.doubleclick_callbacks[callback_name] = callback
            if self.doubleclick_callback is None:
                self.doubleclick_callback = callback_name
            return

        self.log.warning((
            "Callback with name \"{}\" is already registered."
        ).format(callback_name))

    def initialize(self, tray_manager, tray_menu):
        self.tray_manager = tray_manager
        self.initialize_modules()
        self.tray_init()
        self.connect_modules()
        self.tray_menu(tray_menu)

    def get_enabled_tray_modules(self):
        """Enabled tray modules.

        Returns:
            list[AYONAddon]: Enabled addons that inherit from tray interface.
        """

        return [
            module
            for module in self.modules
            if module.enabled and isinstance(module, ITrayModule)
        ]

    def restart_tray(self):
        if self.tray_manager:
            self.tray_manager.restart()

    def tray_init(self):
        report = {}
        time_start = time.time()
        prev_start_time = time_start
        for module in self.get_enabled_tray_modules():
            try:
                module._tray_manager = self.tray_manager
                module.tray_init()
                module.tray_initialized = True
            except Exception:
                self.log.warning(
                    "Module \"{}\" crashed on `tray_init`.".format(
                        module.name
                    ),
                    exc_info=True
                )

            now = time.time()
            report[module.__class__.__name__] = now - prev_start_time
            prev_start_time = now

        if self._report is not None:
            report[self._report_total_key] = time.time() - time_start
            self._report["Tray init"] = report

    def tray_menu(self, tray_menu):
        ordered_modules = []
        enabled_by_name = {
            module.name: module
            for module in self.get_enabled_tray_modules()
        }

        for name in self.modules_menu_order:
            module_by_name = enabled_by_name.pop(name, None)
            if module_by_name:
                ordered_modules.append(module_by_name)
        ordered_modules.extend(enabled_by_name.values())

        report = {}
        time_start = time.time()
        prev_start_time = time_start
        for module in ordered_modules:
            if not module.tray_initialized:
                continue

            try:
                module.tray_menu(tray_menu)
            except Exception:
                # Unset initialized mark
                module.tray_initialized = False
                self.log.warning(
                    "Module \"{}\" crashed on `tray_menu`.".format(
                        module.name
                    ),
                    exc_info=True
                )
            now = time.time()
            report[module.__class__.__name__] = now - prev_start_time
            prev_start_time = now

        if self._report is not None:
            report[self._report_total_key] = time.time() - time_start
            self._report["Tray menu"] = report

    def start_modules(self):
        report = {}
        time_start = time.time()
        prev_start_time = time_start
        for module in self.get_enabled_tray_modules():
            if not module.tray_initialized:
                if isinstance(module, ITrayService):
                    module.set_service_failed_icon()
                continue

            try:
                module.tray_start()
            except Exception:
                self.log.warning(
                    "Module \"{}\" crashed on `tray_start`.".format(
                        module.name
                    ),
                    exc_info=True
                )
            now = time.time()
            report[module.__class__.__name__] = now - prev_start_time
            prev_start_time = now

        if self._report is not None:
            report[self._report_total_key] = time.time() - time_start
            self._report["Modules start"] = report

    def on_exit(self):
        for module in self.get_enabled_tray_modules():
            if module.tray_initialized:
                try:
                    module.tray_exit()
                except Exception:
                    self.log.warning(
                        "Module \"{}\" crashed on `tray_exit`.".format(
                            module.name
                        ),
                        exc_info=True
                    )


def get_module_settings_defs():
    """Check loaded addons/modules for existence of their settings definition.

    Check if OpenPype addon/module as python module has class that inherit
    from `ModuleSettingsDef` in python module variables (imported
    in `__init__py`).

    Returns:
        list: All valid and not abstract settings definitions from imported
            openpype addons and modules.
    """
    # Make sure modules are loaded
    load_modules()

    import openpype_modules

    settings_defs = []

    log = Logger.get_logger("ModuleSettingsLoad")

    for raw_module in openpype_modules:
        for attr_name in dir(raw_module):
            attr = getattr(raw_module, attr_name)
            if (
                not inspect.isclass(attr)
                or attr is ModuleSettingsDef
                or not issubclass(attr, ModuleSettingsDef)
            ):
                continue

            if inspect.isabstract(attr):
                # Find missing implementations by convention on `abc` module
                not_implemented = []
                for attr_name in dir(attr):
                    attr = getattr(attr, attr_name, None)
                    abs_method = getattr(
                        attr, "__isabstractmethod__", None
                    )
                    if attr and abs_method:
                        not_implemented.append(attr_name)

                # Log missing implementations
                log.warning((
                    "Skipping abstract Class: {} in module {}."
                    " Missing implementations: {}"
                ).format(
                    attr_name, raw_module.__name__, ", ".join(not_implemented)
                ))
                continue

            settings_defs.append(attr)

    return settings_defs


@six.add_metaclass(ABCMeta)
class BaseModuleSettingsDef:
    """Definition of settings for OpenPype module or AddOn."""
    _id = None

    @property
    def id(self):
        """ID created on initialization.

        ID should be per created object. Helps to store objects.
        """
        if self._id is None:
            self._id = uuid4()
        return self._id

    @abstractmethod
    def get_settings_schemas(self, schema_type):
        """Setting schemas for passed schema type.

        These are main schemas by dynamic schema keys. If they're using
        sub schemas or templates they should be loaded with
        `get_dynamic_schemas`.

        Returns:
            dict: Schema by `dynamic_schema` keys.
        """
        pass

    @abstractmethod
    def get_dynamic_schemas(self, schema_type):
        """Settings schemas and templates that can be used anywhere.

        It is recommended to add prefix specific for addon/module to keys
        (e.g. "my_addon/real_schema_name").

        Returns:
            dict: Schemas and templates by their keys.
        """
        pass

    @abstractmethod
    def get_defaults(self, top_key):
        """Default values for passed top key.

        Top keys are (currently) "system_settings" or "project_settings".

        Should return exactly what was passed with `save_defaults`.

        Returns:
            dict: Default values by path to first key in OpenPype defaults.
        """
        pass

    @abstractmethod
    def save_defaults(self, top_key, data):
        """Save default values for passed top key.

        Top keys are (currently) "system_settings" or "project_settings".

        Passed data are by path to first key defined in main schemas.
        """
        pass


class ModuleSettingsDef(BaseModuleSettingsDef):
    """Settings definition with separated system and procect settings parts.

    Reduce conditions that must be checked and adds predefined methods for
    each case.
    """
    def get_defaults(self, top_key):
        """Split method into 2 methods by top key."""
        if top_key == SYSTEM_SETTINGS_KEY:
            return self.get_default_system_settings() or {}
        elif top_key == PROJECT_SETTINGS_KEY:
            return self.get_default_project_settings() or {}
        return {}

    def save_defaults(self, top_key, data):
        """Split method into 2 methods by top key."""
        if top_key == SYSTEM_SETTINGS_KEY:
            self.save_system_defaults(data)
        elif top_key == PROJECT_SETTINGS_KEY:
            self.save_project_defaults(data)

    def get_settings_schemas(self, schema_type):
        """Split method into 2 methods by schema type."""
        if schema_type == SCHEMA_KEY_SYSTEM_SETTINGS:
            return self.get_system_settings_schemas() or {}
        elif schema_type == SCHEMA_KEY_PROJECT_SETTINGS:
            return self.get_project_settings_schemas() or {}
        return {}

    def get_dynamic_schemas(self, schema_type):
        """Split method into 2 methods by schema type."""
        if schema_type == SCHEMA_KEY_SYSTEM_SETTINGS:
            return self.get_system_dynamic_schemas() or {}
        elif schema_type == SCHEMA_KEY_PROJECT_SETTINGS:
            return self.get_project_dynamic_schemas() or {}
        return {}

    @abstractmethod
    def get_system_settings_schemas(self):
        """Schemas and templates usable in system settings schemas.

        Returns:
            dict: Schemas and templates by it's names. Names must be unique
                across whole OpenPype.
        """
        pass

    @abstractmethod
    def get_project_settings_schemas(self):
        """Schemas and templates usable in project settings schemas.

        Returns:
            dict: Schemas and templates by it's names. Names must be unique
                across whole OpenPype.
        """
        pass

    @abstractmethod
    def get_system_dynamic_schemas(self):
        """System schemas by dynamic schema name.

        If dynamic schema name is not available in then schema will not used.

        Returns:
            dict: Schemas or list of schemas by dynamic schema name.
        """
        pass

    @abstractmethod
    def get_project_dynamic_schemas(self):
        """Project schemas by dynamic schema name.

        If dynamic schema name is not available in then schema will not used.

        Returns:
            dict: Schemas or list of schemas by dynamic schema name.
        """
        pass

    @abstractmethod
    def get_default_system_settings(self):
        """Default system settings values.

        Returns:
            dict: Default values by path to first key.
        """
        pass

    @abstractmethod
    def get_default_project_settings(self):
        """Default project settings values.

        Returns:
            dict: Default values by path to first key.
        """
        pass

    @abstractmethod
    def save_system_defaults(self, data):
        """Save default system settings values.

        Passed data are by path to first key defined in main schemas.
        """
        pass

    @abstractmethod
    def save_project_defaults(self, data):
        """Save default project settings values.

        Passed data are by path to first key defined in main schemas.
        """
        pass


class JsonFilesSettingsDef(ModuleSettingsDef):
    """Preimplemented settings definition using json files and file structure.

    Expected file structure:
    ┕ root
      │
      │ # Default values
      ┝ defaults
      │ ┝ system_settings.json
      │ ┕ project_settings.json
      │
      │ # Schemas for `dynamic_template` type
      ┝ dynamic_schemas
      │ ┝ system_dynamic_schemas.json
      │ ┕ project_dynamic_schemas.json
      │
      │ # Schemas that can be used anywhere (enhancement for `dynamic_schemas`)
      ┕ schemas
        ┝ system_schemas
        │ ┝ <system schema.json> # Any schema or template files
        │ ┕ ...
        ┕ project_schemas
          ┝ <system schema.json> # Any schema or template files
          ┕ ...

    Schemas can be loaded with prefix to avoid duplicated schema/template names
    across all OpenPype addons/modules. Prefix can be defined with class
    attribute `schema_prefix`.

    Only think which must be implemented in `get_settings_root_path` which
    should return directory path to `root` (in structure graph above).
    """
    # Possible way how to define `schemas` prefix
    schema_prefix = ""

    @abstractmethod
    def get_settings_root_path(self):
        """Directory path where settings and it's schemas are located."""
        pass

    def __init__(self):
        settings_root_dir = self.get_settings_root_path()
        defaults_dir = os.path.join(
            settings_root_dir, "defaults"
        )
        dynamic_schemas_dir = os.path.join(
            settings_root_dir, "dynamic_schemas"
        )
        schemas_dir = os.path.join(
            settings_root_dir, "schemas"
        )

        self.system_defaults_filepath = os.path.join(
            defaults_dir, "system_settings.json"
        )
        self.project_defaults_filepath = os.path.join(
            defaults_dir, "project_settings.json"
        )

        self.system_dynamic_schemas_filepath = os.path.join(
            dynamic_schemas_dir, "system_dynamic_schemas.json"
        )
        self.project_dynamic_schemas_filepath = os.path.join(
            dynamic_schemas_dir, "project_dynamic_schemas.json"
        )

        self.system_schemas_dir = os.path.join(
            schemas_dir, "system_schemas"
        )
        self.project_schemas_dir = os.path.join(
            schemas_dir, "project_schemas"
        )

    def _load_json_file_data(self, path):
        if os.path.exists(path):
            return load_json_file(path)
        return {}

    def get_default_system_settings(self):
        """Default system settings values.

        Returns:
            dict: Default values by path to first key.
        """
        return self._load_json_file_data(self.system_defaults_filepath)

    def get_default_project_settings(self):
        """Default project settings values.

        Returns:
            dict: Default values by path to first key.
        """
        return self._load_json_file_data(self.project_defaults_filepath)

    def _save_data_to_filepath(self, path, data):
        dirpath = os.path.dirname(path)
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)

        with open(path, "w") as file_stream:
            json.dump(data, file_stream, indent=4)

    def save_system_defaults(self, data):
        """Save default system settings values.

        Passed data are by path to first key defined in main schemas.
        """
        self._save_data_to_filepath(self.system_defaults_filepath, data)

    def save_project_defaults(self, data):
        """Save default project settings values.

        Passed data are by path to first key defined in main schemas.
        """
        self._save_data_to_filepath(self.project_defaults_filepath, data)

    def get_system_dynamic_schemas(self):
        """System schemas by dynamic schema name.

        If dynamic schema name is not available in then schema will not used.

        Returns:
            dict: Schemas or list of schemas by dynamic schema name.
        """
        return self._load_json_file_data(self.system_dynamic_schemas_filepath)

    def get_project_dynamic_schemas(self):
        """Project schemas by dynamic schema name.

        If dynamic schema name is not available in then schema will not used.

        Returns:
            dict: Schemas or list of schemas by dynamic schema name.
        """
        return self._load_json_file_data(self.project_dynamic_schemas_filepath)

    def _load_files_from_path(self, path):
        output = {}
        if not path or not os.path.exists(path):
            return output

        if os.path.isfile(path):
            filename = os.path.basename(path)
            basename, ext = os.path.splitext(filename)
            if ext == ".json":
                if self.schema_prefix:
                    key = "{}/{}".format(self.schema_prefix, basename)
                else:
                    key = basename
                output[key] = self._load_json_file_data(path)
            return output

        path = os.path.normpath(path)
        for root, _, files in os.walk(path, topdown=False):
            for filename in files:
                basename, ext = os.path.splitext(filename)
                if ext != ".json":
                    continue

                json_path = os.path.join(root, filename)
                store_key = os.path.join(
                    root.replace(path, ""), basename
                ).replace("\\", "/")
                if self.schema_prefix:
                    store_key = "{}/{}".format(self.schema_prefix, store_key)
                output[store_key] = self._load_json_file_data(json_path)

        return output

    def get_system_settings_schemas(self):
        """Schemas and templates usable in system settings schemas.

        Returns:
            dict: Schemas and templates by it's names. Names must be unique
                across whole OpenPype.
        """
        return self._load_files_from_path(self.system_schemas_dir)

    def get_project_settings_schemas(self):
        """Schemas and templates usable in project settings schemas.

        Returns:
            dict: Schemas and templates by it's names. Names must be unique
                across whole OpenPype.
        """
        return self._load_files_from_path(self.project_schemas_dir)
