import os
import subprocess
import collections
import asyncio

from wsrpc_aiohttp import (
    WebSocketRoute,
    WebSocketAsync
)

from qtpy import QtCore

from openpype.lib import Logger, StringTemplate
from openpype.pipeline import (
    registered_host,
    Anatomy,
)
from openpype.pipeline.workfile import (
    get_workfile_template_key_from_context,
    get_last_workfile,
)
from openpype.pipeline.template_data import get_template_data_with_names
from openpype.tools.utils import host_tools
from openpype.tools.adobe_webserver.app import WebServerTool
from openpype.pipeline.context_tools import change_current_context
from openpype.client import get_asset_by_name

from .ws_stub import PhotoshopServerStub

log = Logger.get_logger(__name__)


class ConnectionNotEstablishedYet(Exception):
    pass


class MainThreadItem:
    """Structure to store information about callback in main thread.

    Item should be used to execute callback in main thread which may be needed
    for execution of Qt objects.

    Item store callback (callable variable), arguments and keyword arguments
    for the callback. Item hold information about it's process.
    """
    not_set = object()

    def __init__(self, callback, *args, **kwargs):
        self._done = False
        self._exception = self.not_set
        self._result = self.not_set
        self._callback = callback
        self._args = args
        self._kwargs = kwargs

    @property
    def done(self):
        return self._done

    @property
    def exception(self):
        return self._exception

    @property
    def result(self):
        return self._result

    def execute(self):
        """Execute callback and store its result.

        Method must be called from main thread. Item is marked as `done`
        when callback execution finished. Store output of callback of exception
        information when callback raises one.
        """
        log.debug("Executing process in main thread")
        if self.done:
            log.warning("- item is already processed")
            return

        log.info("Running callback: {}".format(str(self._callback)))
        try:
            result = self._callback(*self._args, **self._kwargs)
            self._result = result

        except Exception as exc:
            self._exception = exc

        finally:
            self._done = True


def stub():
    """
        Convenience function to get server RPC stub to call methods directed
        for host (Photoshop).
        It expects already created connection, started from client.
        Currently created when panel is opened (PS: Window>Extensions>Avalon)
    :return: <PhotoshopClientStub> where functions could be called from
    """
    ps_stub = PhotoshopServerStub()
    if not ps_stub.client:
        raise ConnectionNotEstablishedYet("Connection is not created yet")

    return ps_stub


def show_tool_by_name(tool_name):
    kwargs = {}
    if tool_name == "loader":
        kwargs["use_context"] = True

    host_tools.show_tool_by_name(tool_name, **kwargs)


class ProcessLauncher(QtCore.QObject):
    route_name = "Photoshop"
    _main_thread_callbacks = collections.deque()

    def __init__(self, subprocess_args):
        self._subprocess_args = subprocess_args
        self._log = None

        super(ProcessLauncher, self).__init__()

        # Keep track if launcher was already started
        self._started = False

        self._process = None
        self._websocket_server = None

        start_process_timer = QtCore.QTimer()
        start_process_timer.setInterval(100)

        loop_timer = QtCore.QTimer()
        loop_timer.setInterval(200)

        start_process_timer.timeout.connect(self._on_start_process_timer)
        loop_timer.timeout.connect(self._on_loop_timer)

        self._start_process_timer = start_process_timer
        self._loop_timer = loop_timer

    @property
    def log(self):
        if self._log is None:
            self._log = Logger.get_logger(
                "{}-launcher".format(self.route_name)
            )
        return self._log

    @property
    def websocket_server_is_running(self):
        if self._websocket_server is not None:
            return self._websocket_server.is_running
        return False

    @property
    def is_process_running(self):
        if self._process is not None:
            return self._process.poll() is None
        return False

    @property
    def is_host_connected(self):
        """Returns True if connected, False if app is not running at all."""
        if not self.is_process_running:
            return False

        try:
            _stub = stub()
            if _stub:
                return True
        except Exception:
            pass

        return None

    @classmethod
    def execute_in_main_thread(cls, callback, *args, **kwargs):
        item = MainThreadItem(callback, *args, **kwargs)
        cls._main_thread_callbacks.append(item)
        return item

    def start(self):
        if self._started:
            return
        self.log.info("Started launch logic of Photoshop")
        self._started = True
        self._start_process_timer.start()

    def exit(self):
        """ Exit whole application. """
        if self._start_process_timer.isActive():
            self._start_process_timer.stop()
        if self._loop_timer.isActive():
            self._loop_timer.stop()

        if self._websocket_server is not None:
            self._websocket_server.stop()

        if self._process:
            self._process.kill()
            self._process.wait()

        QtCore.QCoreApplication.exit()

    def _on_loop_timer(self):
        # TODO find better way and catch errors
        # Run only callbacks that are in queue at the moment
        cls = self.__class__
        for _ in range(len(cls._main_thread_callbacks)):
            if cls._main_thread_callbacks:
                item = cls._main_thread_callbacks.popleft()
                item.execute()

        if not self.is_process_running:
            self.log.info("Host process is not running. Closing")
            self.exit()

        elif not self.websocket_server_is_running:
            self.log.info("Websocket server is not running. Closing")
            self.exit()

    def _on_start_process_timer(self):
        # TODO add try except validations for each part in this method
        # Start server as first thing
        if self._websocket_server is None:
            self._init_server()
            return

        # TODO add waiting time
        # Wait for webserver
        if not self.websocket_server_is_running:
            return

        # Start application process
        if self._process is None:
            self._start_process()
            self.log.info("Waiting for host to connect")
            return

        # TODO add waiting time
        # Wait until host is connected
        if self.is_host_connected:
            self._start_process_timer.stop()
            self._loop_timer.start()
        elif (
            not self.is_process_running
            or not self.websocket_server_is_running
        ):
            self.exit()

    def _init_server(self):
        if self._websocket_server is not None:
            return

        self.log.debug(
            "Initialization of websocket server for host communication"
        )

        self._websocket_server = websocket_server = WebServerTool()
        if websocket_server.port_occupied(
            websocket_server.host_name,
            websocket_server.port
        ):
            self.log.info(
                "Server already running, sending actual context and exit."
            )
            asyncio.run(websocket_server.send_context_change(self.route_name))
            self.exit()
            return

        # Add Websocket route
        websocket_server.add_route("*", "/ws/", WebSocketAsync)
        # Add after effects route to websocket handler

        print("Adding {} route".format(self.route_name))
        WebSocketAsync.add_route(
            self.route_name, PhotoshopRoute
        )
        self.log.info("Starting websocket server for host communication")
        websocket_server.start_server()

    def _start_process(self):
        if self._process is not None:
            return
        self.log.info("Starting host process")
        try:
            self._process = subprocess.Popen(
                self._subprocess_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            self.log.info("exce", exc_info=True)
            self.exit()


class PhotoshopRoute(WebSocketRoute):
    """
        One route, mimicking external application (like Harmony, etc).
        All functions could be called from client.
        'do_notify' function calls function on the client - mimicking
            notification after long running job on the server or similar
    """
    instance = None

    def init(self, **kwargs):
        # Python __init__ must be return "self".
        # This method might return anything.
        log.debug("someone called Photoshop route")
        self.instance = self
        return kwargs

    # server functions
    async def ping(self):
        log.debug("someone called Photoshop route ping")

    # This method calls function on the client side
    # client functions
    async def set_context(self, project, asset, task):
        """
            Sets 'project' and 'asset' to envs, eg. setting context.

        Opens last workile from that context if exists.

        Args:
            project (str)
            asset (str)
            task (str
        """
        log.info("Setting context change")
        log.info(f"project {project} asset {asset} task {task}")

        asset_doc = get_asset_by_name(project, asset)
        change_current_context(asset_doc, task)

        last_workfile_path = self._get_last_workfile_path(project,
                                                          asset,
                                                          task)
        if last_workfile_path and os.path.exists(last_workfile_path):
            ProcessLauncher.execute_in_main_thread(
                lambda: stub().open(last_workfile_path))


    async def read(self):
        log.debug("photoshop.read client calls server server calls "
                  "photoshop client")
        return await self.socket.call('photoshop.read')

    # panel routes for tools
    async def workfiles_route(self):
        self._tool_route("workfiles")

    async def loader_route(self):
        self._tool_route("loader")

    async def publish_route(self):
        self._tool_route("publisher")

    async def sceneinventory_route(self):
        self._tool_route("sceneinventory")

    async def experimental_tools_route(self):
        self._tool_route("experimental_tools")

    def _tool_route(self, _tool_name):
        """The address accessed when clicking on the buttons."""

        ProcessLauncher.execute_in_main_thread(show_tool_by_name, _tool_name)

        # Required return statement.
        return "nothing"

    def _get_last_workfile_path(self, project_name, asset_name, task_name):
        """Returns last workfile path if exists"""
        host = registered_host()
        host_name = "photoshop"
        template_key = get_workfile_template_key_from_context(
            asset_name,
            task_name,
            host_name,
            project_name=project_name
        )
        anatomy = Anatomy(project_name)

        data = get_template_data_with_names(
            project_name, asset_name, task_name, host_name
        )
        data["root"] = anatomy.roots

        file_template = anatomy.templates[template_key]["file"]

        # Define saving file extension
        extensions = host.get_workfile_extensions()

        folder_template = anatomy.templates[template_key]["folder"]
        work_root = StringTemplate.format_strict_template(
            folder_template, data
        )
        last_workfile_path = get_last_workfile(
            work_root, file_template, data, extensions, True
        )

        return last_workfile_path
