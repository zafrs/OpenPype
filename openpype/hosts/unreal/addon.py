import os
from openpype.modules import OpenPypeModule, IHostAddon

UNREAL_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


class UnrealAddon(OpenPypeModule, IHostAddon):
    name = "unreal"
    host_name = "unreal"

    def initialize(self, module_settings):
        self.enabled = True

    def add_implementation_envs(self, env, app):
        """Modify environments to contain all required for implementation."""
        # Set OPENPYPE_UNREAL_PLUGIN required for Unreal implementation

        ue_plugin = "UE_5.0" if app.name[:1] == "5" else "UE_4.7"
        unreal_plugin_path = os.path.join(
            UNREAL_ROOT_DIR, "integration", ue_plugin, "OpenPype"
        )
        if not env.get("OPENPYPE_UNREAL_PLUGIN") or \
                env.get("OPENPYPE_UNREAL_PLUGIN") != unreal_plugin_path:
            env["OPENPYPE_UNREAL_PLUGIN"] = unreal_plugin_path

        # Set default environments if are not set via settings
        defaults = {
            "OPENPYPE_LOG_NO_COLORS": "True"
        }
        for key, value in defaults.items():
            if not env.get(key):
                env[key] = value

    def get_launch_hook_paths(self, app):
        if app.host_name != self.host_name:
            return []
        return [
            os.path.join(UNREAL_ROOT_DIR, "hooks")
        ]

    def get_workfile_extensions(self):
        return [".uproject"]
