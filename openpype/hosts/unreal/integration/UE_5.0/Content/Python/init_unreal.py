import unreal

openpype_detected = True
try:
    from openpype.pipeline import install_host
    from openpype.hosts.unreal.api import UnrealHost

    openpype_host = UnrealHost()
except ImportError as exc:
    openpype_host = None
    openpype_detected = False
    unreal.log_error("OpenPype: cannot load OpenPype [ {} ]".format(exc))

if openpype_detected:
    install_host(openpype_host)


@unreal.uclass()
class OpenPypeIntegration(unreal.OpenPypePythonBridge):
    @unreal.ufunction(override=True)
    def RunInPython_Popup(self):
        unreal.log_warning("OpenPype: showing tools popup")
        if openpype_detected:
            openpype_host.show_tools_popup()

    @unreal.ufunction(override=True)
    def RunInPython_Dialog(self):
        unreal.log_warning("OpenPype: showing tools dialog")
        if openpype_detected:
            openpype_host.show_tools_dialog()
