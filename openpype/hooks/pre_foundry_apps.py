import subprocess
from openpype.lib import PreLaunchHook


class LaunchFoundryAppsWindows(PreLaunchHook):
    """Foundry applications have specific way how to launch them.

    Nuke is executed "like" python process so it is required to pass
    `CREATE_NEW_CONSOLE` flag on windows to trigger creation of new console.
    At the same time the newly created console won't create its own stdout
    and stderr handlers so they should not be redirected to DEVNULL.
    """

    # Should be as last hook because must change launch arguments to string
    order = 1000
    app_groups = ["nuke", "nukeassist", "nukex", "hiero", "nukestudio"]
    platforms = ["windows"]

    def execute(self):
        # Change `creationflags` to CREATE_NEW_CONSOLE
        # - on Windows nuke will create new window using its console
        # Set `stdout` and `stderr` to None so new created console does not
        #   have redirected output to DEVNULL in build
        self.launch_context.kwargs.update({
            "creationflags": subprocess.CREATE_NEW_CONSOLE,
            "stdout": None,
            "stderr": None
        })
