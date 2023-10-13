# Test for backward compatibility of restructure of lib.py into lib library
# Contains simple imports that should still work


def test_backward_compatibility(printer):
    printer("Test if imports still work")
    try:
        from openpype.lib import execute_hook
        from openpype.lib import PypeHook

        from openpype.lib import ApplicationLaunchFailed

        from openpype.lib import get_ffmpeg_tool_path
        from openpype.lib import get_last_version_from_path
        from openpype.lib import get_paths_from_environ
        from openpype.lib import get_version_from_path
        from openpype.lib import version_up

        from openpype.lib import get_ffprobe_streams

        from openpype.lib import source_hash
        from openpype.lib import run_subprocess

    except ImportError as e:
        raise
