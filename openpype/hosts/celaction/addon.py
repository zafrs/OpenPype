import os
from openpype.modules import OpenPypeModule, IHostAddon

CELACTION_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


class CelactionAddon(OpenPypeModule, IHostAddon):
    name = "celaction"
    host_name = "celaction"

    def initialize(self, module_settings):
        self.enabled = True

    def get_launch_hook_paths(self, app):
        if app.host_name != self.host_name:
            return []
        return [
            os.path.join(CELACTION_ROOT_DIR, "hooks")
        ]

    def add_implementation_envs(self, env, _app):
        # Set default values if are not already set via settings
        defaults = {
            "LOGLEVEL": "DEBUG"
        }
        for key, value in defaults.items():
            if not env.get(key):
                env[key] = value

    def get_workfile_extensions(self):
        return [".scn"]
