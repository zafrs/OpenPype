from abc import ABCMeta, abstractmethod, abstractproperty

import six

from openpype import resources


class _OpenPypeInterfaceMeta(ABCMeta):
    """OpenPypeInterface meta class to print proper string."""

    def __str__(self):
        return "<'OpenPypeInterface.{}'>".format(self.__name__)

    def __repr__(self):
        return str(self)


@six.add_metaclass(_OpenPypeInterfaceMeta)
class OpenPypeInterface:
    """Base class of Interface that can be used as Mixin with abstract parts.

    This is way how OpenPype module or addon can tell OpenPype that contain
    implementation for specific functionality.

    Child classes of OpenPypeInterface may be used as mixin in different
    OpenPype modules which means they have to have implemented methods defined
    in the interface. By default, interface does not have any abstract parts.
    """

    pass


class IPluginPaths(OpenPypeInterface):
    """Module has plugin paths to return.

    Expected result is dictionary with keys "publish", "create", "load" or
    "actions" and values as list or string.
    {
        "publish": ["path/to/publish_plugins"]
    }
    """

    @abstractmethod
    def get_plugin_paths(self):
        pass

    def _get_plugin_paths_by_type(self, plugin_type):
        paths = self.get_plugin_paths()
        if not paths or plugin_type not in paths:
            return []

        paths = paths[plugin_type]
        if not paths:
            return []

        if not isinstance(paths, (list, tuple, set)):
            paths = [paths]
        return paths

    def get_create_plugin_paths(self, host_name):
        """Receive create plugin paths.

        Give addons ability to add create plugin paths based on host name.

        Notes:
            Default implementation uses 'get_plugin_paths' and always return
                all create plugin paths.

        Args:
            host_name (str): For which host are the plugins meant.
        """

        if hasattr(self, "get_creator_plugin_paths"):
            # TODO remove in 3.16
            self.log.warning((
                "DEPRECATION WARNING: Using method 'get_creator_plugin_paths'"
                " which was renamed to 'get_create_plugin_paths'."
            ))
            return self.get_creator_plugin_paths(host_name)
        return self._get_plugin_paths_by_type("create")

    def get_load_plugin_paths(self, host_name):
        """Receive load plugin paths.

        Give addons ability to add load plugin paths based on host name.

        Notes:
            Default implementation uses 'get_plugin_paths' and always return
                all load plugin paths.

        Args:
            host_name (str): For which host are the plugins meant.
        """

        return self._get_plugin_paths_by_type("load")

    def get_publish_plugin_paths(self, host_name):
        """Receive publish plugin paths.

        Give addons ability to add publish plugin paths based on host name.

        Notes:
           Default implementation uses 'get_plugin_paths' and always return
               all publish plugin paths.

        Args:
           host_name (str): For which host are the plugins meant.
        """

        return self._get_plugin_paths_by_type("publish")


class ILaunchHookPaths(OpenPypeInterface):
    """Module has launch hook paths to return.

    Modules don't have to inherit from this interface (changed 8.11.2022).
    Module just have to have implemented 'get_launch_hook_paths' to be able to
    use the advantage.

    Expected result is list of paths.
    ["path/to/launch_hooks_dir"]

    Deprecated:
        This interface is not needed since OpenPype 3.14.*. Addon just have to
        implement 'get_launch_hook_paths' which can expect Application object
        or nothing as argument.

        Interface class will be removed after 3.16.*.
    """

    @abstractmethod
    def get_launch_hook_paths(self, app):
        """Paths to directory with application launch hooks.

        Method can be also defined without arguments.
        ```python
        def get_launch_hook_paths(self):
            return []
        ```

        Args:
            app (Application): Application object which can be used for
                filtering of which launch hook paths are returned.

        Returns:
            Iterable[str]: Path to directories where launch hooks can be found.
        """

        pass


class ITrayModule(OpenPypeInterface):
    """Module has special procedures when used in Pype Tray.

    IMPORTANT:
    The module still must be usable if is not used in tray even if
    would do nothing.
    """

    tray_initialized = False
    _tray_manager = None

    @abstractmethod
    def tray_init(self):
        """Initialization part of tray implementation.

        Triggered between `initialization` and `connect_with_modules`.

        This is where GUIs should be loaded or tray specific parts should be
        prepared.
        """

        pass

    @abstractmethod
    def tray_menu(self, tray_menu):
        """Add module's action to tray menu."""

        pass

    @abstractmethod
    def tray_start(self):
        """Start procedure in Pype tray."""

        pass

    @abstractmethod
    def tray_exit(self):
        """Cleanup method which is executed on tray shutdown.

        This is place where all threads should be shut.
        """

        pass

    def execute_in_main_thread(self, callback):
        """ Pushes callback to the queue or process 'callback' on a main thread

            Some callbacks need to be processed on main thread (menu actions
            must be added on main thread or they won't get triggered etc.)
        """

        if not self.tray_initialized:
            # TODO Called without initialized tray, still main thread needed
            try:
                callback()

            except Exception:
                self.log.warning(
                    "Failed to execute {} in main thread".format(callback),
                    exc_info=True)

            return
        self.manager.tray_manager.execute_in_main_thread(callback)

    def show_tray_message(self, title, message, icon=None, msecs=None):
        """Show tray message.

        Args:
            title (str): Title of message.
            message (str): Content of message.
            icon (QSystemTrayIcon.MessageIcon): Message's icon. Default is
                Information icon, may differ by Qt version.
            msecs (int): Duration of message visibility in milliseconds.
                Default is 10000 msecs, may differ by Qt version.
        """

        if self._tray_manager:
            self._tray_manager.show_tray_message(title, message, icon, msecs)

    def add_doubleclick_callback(self, callback):
        if hasattr(self.manager, "add_doubleclick_callback"):
            self.manager.add_doubleclick_callback(self, callback)


class ITrayAction(ITrayModule):
    """Implementation of Tray action.

    Add action to tray menu which will trigger `on_action_trigger`.
    It is expected to be used for showing tools.

    Methods `tray_start`, `tray_exit` and `connect_with_modules` are overridden
    as it's not expected that action will use them. But it is possible if
    necessary.
    """

    admin_action = False
    _admin_submenu = None
    _action_item = None

    @property
    @abstractmethod
    def label(self):
        """Service label showed in menu."""
        pass

    @abstractmethod
    def on_action_trigger(self):
        """What happens on actions click."""
        pass

    def tray_menu(self, tray_menu):
        from qtpy import QtWidgets

        if self.admin_action:
            menu = self.admin_submenu(tray_menu)
            action = QtWidgets.QAction(self.label, menu)
            menu.addAction(action)
            if not menu.menuAction().isVisible():
                menu.menuAction().setVisible(True)

        else:
            action = QtWidgets.QAction(self.label, tray_menu)
            tray_menu.addAction(action)

        action.triggered.connect(self.on_action_trigger)
        self._action_item = action

    def tray_start(self):
        return

    def tray_exit(self):
        return

    @staticmethod
    def admin_submenu(tray_menu):
        if ITrayAction._admin_submenu is None:
            from qtpy import QtWidgets

            admin_submenu = QtWidgets.QMenu("Admin", tray_menu)
            admin_submenu.menuAction().setVisible(False)
            ITrayAction._admin_submenu = admin_submenu
        return ITrayAction._admin_submenu


class ITrayService(ITrayModule):
    # Module's property
    menu_action = None

    # Class properties
    _services_submenu = None
    _icon_failed = None
    _icon_running = None
    _icon_idle = None

    @property
    @abstractmethod
    def label(self):
        """Service label showed in menu."""
        pass

    # TODO be able to get any sort of information to show/print
    # @abstractmethod
    # def get_service_info(self):
    #     pass

    @staticmethod
    def services_submenu(tray_menu):
        if ITrayService._services_submenu is None:
            from qtpy import QtWidgets

            services_submenu = QtWidgets.QMenu("Services", tray_menu)
            services_submenu.menuAction().setVisible(False)
            ITrayService._services_submenu = services_submenu
        return ITrayService._services_submenu

    @staticmethod
    def add_service_action(action):
        ITrayService._services_submenu.addAction(action)
        if not ITrayService._services_submenu.menuAction().isVisible():
            ITrayService._services_submenu.menuAction().setVisible(True)

    @staticmethod
    def _load_service_icons():
        from qtpy import QtGui

        ITrayService._failed_icon = QtGui.QIcon(
            resources.get_resource("icons", "circle_red.png")
        )
        ITrayService._icon_running = QtGui.QIcon(
            resources.get_resource("icons", "circle_green.png")
        )
        ITrayService._icon_idle = QtGui.QIcon(
            resources.get_resource("icons", "circle_orange.png")
        )

    @staticmethod
    def get_icon_running():
        if ITrayService._icon_running is None:
            ITrayService._load_service_icons()
        return ITrayService._icon_running

    @staticmethod
    def get_icon_idle():
        if ITrayService._icon_idle is None:
            ITrayService._load_service_icons()
        return ITrayService._icon_idle

    @staticmethod
    def get_icon_failed():
        if ITrayService._failed_icon is None:
            ITrayService._load_service_icons()
        return ITrayService._failed_icon

    def tray_menu(self, tray_menu):
        from qtpy import QtWidgets

        action = QtWidgets.QAction(
            self.label,
            self.services_submenu(tray_menu)
        )
        self.menu_action = action

        self.add_service_action(action)

        self.set_service_running_icon()

    def set_service_running_icon(self):
        """Change icon of an QAction to green circle."""

        if self.menu_action:
            self.menu_action.setIcon(self.get_icon_running())

    def set_service_failed_icon(self):
        """Change icon of an QAction to red circle."""

        if self.menu_action:
            self.menu_action.setIcon(self.get_icon_failed())

    def set_service_idle_icon(self):
        """Change icon of an QAction to orange circle."""

        if self.menu_action:
            self.menu_action.setIcon(self.get_icon_idle())


class ISettingsChangeListener(OpenPypeInterface):
    """Module has plugin paths to return.

    Expected result is dictionary with keys "publish", "create", "load" or
    "actions" and values as list or string.
    {
        "publish": ["path/to/publish_plugins"]
    }
    """

    @abstractmethod
    def on_system_settings_save(
        self, old_value, new_value, changes, new_value_metadata
    ):
        pass

    @abstractmethod
    def on_project_settings_save(
        self, old_value, new_value, changes, project_name, new_value_metadata
    ):
        pass

    @abstractmethod
    def on_project_anatomy_save(
        self, old_value, new_value, changes, project_name, new_value_metadata
    ):
        pass


class IHostAddon(OpenPypeInterface):
    """Addon which also contain a host implementation."""

    @abstractproperty
    def host_name(self):
        """Name of host which module represents."""

        pass

    def get_workfile_extensions(self):
        """Define workfile extensions for host.

        Not all hosts support workfiles thus this is optional implementation.

        Returns:
            List[str]: Extensions used for workfiles with dot.
        """

        return []
