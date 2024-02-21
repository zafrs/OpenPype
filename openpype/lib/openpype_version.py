"""Lib access to OpenPypeVersion from igniter.

Access to logic from igniter is available only for OpenPype processes.
Is meant to be able check OpenPype versions for studio. The logic is dependent
on igniter's inner logic of versions.

Keep in mind that all functions except 'get_installed_version' does not return
OpenPype version located in build but versions available in remote versions
repository or locally available.
"""

import os
import sys

import openpype.version
from openpype import AYON_SERVER_ENABLED

from .python_module_tools import import_filepath


# ----------------------------------------
# Functions independent on OpenPypeVersion
# ----------------------------------------
def get_openpype_version():
    """Version of pype that is currently used."""
    return openpype.version.__version__


def get_ayon_launcher_version():
    version_filepath = os.path.join(
        os.environ["AYON_ROOT"],
        "version.py"
    )
    if not os.path.exists(version_filepath):
        return None
    content = {}
    with open(version_filepath, "r") as stream:
        exec(stream.read(), content)
    return content["__version__"]


def get_build_version():
    """OpenPype version of build."""

    if AYON_SERVER_ENABLED:
        return get_ayon_launcher_version()

    # Return OpenPype version if is running from code
    if not is_running_from_build():
        return get_openpype_version()

    # Import `version.py` from build directory
    version_filepath = os.path.join(
        os.environ["OPENPYPE_ROOT"],
        "openpype",
        "version.py"
    )
    if not os.path.exists(version_filepath):
        return None

    module = import_filepath(version_filepath, "openpype_build_version")
    return getattr(module, "__version__", None)


def is_running_from_build():
    """Determine if current process is running from build or code.

    Returns:
        bool: True if running from build.
    """

    if AYON_SERVER_ENABLED:
        executable_path = os.environ["AYON_EXECUTABLE"]
    else:
        executable_path = os.environ["OPENPYPE_EXECUTABLE"]
    executable_filename = os.path.basename(executable_path)
    if "python" in executable_filename.lower():
        return False
    return True


def is_staging_enabled():
    if AYON_SERVER_ENABLED:
        return os.getenv("AYON_USE_STAGING") == "1"
    return os.environ.get("OPENPYPE_USE_STAGING") == "1"


def is_running_staging():
    """Currently used OpenPype is staging version.

    This function is not 100% proper check of staging version. It is possible
    to have enabled to use staging version but be in different one.

    The function is based on 4 factors:
    - env 'OPENPYPE_IS_STAGING' is set
    - current production version
    - current staging version
    - use staging is enabled

    First checks for 'OPENPYPE_IS_STAGING' environment which can be set to '1'.
    The value should be set only when a process without access to
    OpenPypeVersion is launched (e.g. in DCCs). If current version is same
    as production version it is expected that it is not staging, and it
    doesn't matter what would 'is_staging_enabled' return. If current version
    is same as staging version it is expected we're in staging. In all other
    cases 'is_staging_enabled' is used as source of outpu value.

    The function is used to decide which icon is used. To check e.g. updates
    the output should be combined with other functions from this file.

    Returns:
        bool: Using staging version or not.
    """

    if AYON_SERVER_ENABLED:
        return is_staging_enabled()

    if os.environ.get("OPENPYPE_IS_STAGING") == "1":
        return True

    if not op_version_control_available():
        return False

    from openpype.settings import get_global_settings

    global_settings = get_global_settings()
    production_version = global_settings["production_version"]
    latest_version = None
    if not production_version or production_version == "latest":
        latest_version = get_latest_version(local=False, remote=True)
        production_version = latest_version

    current_version = get_openpype_version()
    if current_version == production_version:
        return False

    staging_version = global_settings["staging_version"]
    if not staging_version or staging_version == "latest":
        if latest_version is None:
            latest_version = get_latest_version(local=False, remote=True)
        staging_version = latest_version

    if current_version == staging_version:
        return True

    return is_staging_enabled()


# ----------------------------------------
# Functions dependent on OpenPypeVersion
#   - Make sense to call only in OpenPype process
# ----------------------------------------
def get_OpenPypeVersion():
    """Access to OpenPypeVersion class stored in sys modules."""
    return sys.modules.get("OpenPypeVersion")


def op_version_control_available():
    """Check if current process has access to OpenPypeVersion."""
    if get_OpenPypeVersion() is None:
        return False
    return True


def get_installed_version():
    """Get OpenPype version inside build.

    This version is not returned by any other functions here.
    """
    if op_version_control_available():
        return get_OpenPypeVersion().get_installed_version()
    return None


def get_available_versions(*args, **kwargs):
    """Get list of available versions."""
    if op_version_control_available():
        return get_OpenPypeVersion().get_available_versions(
            *args, **kwargs
        )
    return None


def openpype_path_is_set():
    """OpenPype repository path is set in settings."""
    if op_version_control_available():
        return get_OpenPypeVersion().openpype_path_is_set()
    return None


def openpype_path_is_accessible():
    """OpenPype version repository path can be accessed."""
    if op_version_control_available():
        return get_OpenPypeVersion().openpype_path_is_accessible()
    return None


def get_local_versions(*args, **kwargs):
    """OpenPype versions available on this workstation."""
    if op_version_control_available():
        return get_OpenPypeVersion().get_local_versions(*args, **kwargs)
    return None


def get_remote_versions(*args, **kwargs):
    """OpenPype versions in repository path."""
    if op_version_control_available():
        return get_OpenPypeVersion().get_remote_versions(*args, **kwargs)
    return None


def get_latest_version(local=None, remote=None):
    """Get latest version from repository path."""

    if op_version_control_available():
        return get_OpenPypeVersion().get_latest_version(
            local=local,
            remote=remote
        )
    return None


def get_expected_studio_version(staging=None):
    """Expected production or staging version in studio."""
    if op_version_control_available():
        if staging is None:
            staging = is_staging_enabled()
        return get_OpenPypeVersion().get_expected_studio_version(staging)
    return None


def get_expected_version(staging=None):
    expected_version = get_expected_studio_version(staging)
    if expected_version is None:
        # Look for latest if expected version is not set in settings
        expected_version = get_latest_version(
            local=False,
            remote=True
        )
    return expected_version


def is_current_version_studio_latest():
    """Is currently running OpenPype version which is defined by studio.

    It is not recommended to ask in each process as there may be situations
    when older OpenPype should be used. For example on farm. But it does make
    sense in processes that can run for a long time.

    Returns:
        None: Can't determine. e.g. when running from code or the build is
            too old.
        bool: True when is using studio
    """
    output = None
    # Skip if is not running from build or build does not support version
    #   control or path to folder with zip files is not accessible
    if (
        not is_running_from_build()
        or not op_version_control_available()
        or not openpype_path_is_accessible()
    ):
        return output

    # Get OpenPypeVersion class
    OpenPypeVersion = get_OpenPypeVersion()
    # Convert current version to OpenPypeVersion object
    current_version = OpenPypeVersion(version=get_openpype_version())

    # Get expected version (from settings)
    expected_version = get_expected_version()
    # Check if current version is expected version
    return current_version == expected_version


def is_current_version_higher_than_expected():
    """Is current OpenPype version higher than version defined by studio.

    Returns:
        None: Can't determine. e.g. when running from code or the build is
            too old.
        bool: True when is higher than studio version.
    """
    output = None
    # Skip if is not running from build or build does not support version
    #   control or path to folder with zip files is not accessible
    if (
        not is_running_from_build()
        or not op_version_control_available()
        or not openpype_path_is_accessible()
    ):
        return output

    # Get OpenPypeVersion class
    OpenPypeVersion = get_OpenPypeVersion()
    # Convert current version to OpenPypeVersion object
    current_version = OpenPypeVersion(version=get_openpype_version())

    # Get expected version (from settings)
    expected_version = get_expected_version()
    # Check if current version is expected version
    return current_version > expected_version
