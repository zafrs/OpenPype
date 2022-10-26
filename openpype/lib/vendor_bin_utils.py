import os
import logging
import platform
import subprocess

log = logging.getLogger("Vendor utils")


class CachedToolPaths:
    """Cache already used and discovered tools and their executables.

    Discovering path can take some time and can trigger subprocesses so it's
    better to cache the paths on first get.
    """

    _cached_paths = {}

    @classmethod
    def is_tool_cached(cls, tool):
        return tool in cls._cached_paths

    @classmethod
    def get_executable_path(cls, tool):
        return cls._cached_paths.get(tool)

    @classmethod
    def cache_executable_path(cls, tool, path):
        cls._cached_paths[tool] = path


def is_file_executable(filepath):
    """Filepath lead to executable file.

    Args:
        filepath(str): Full path to file.
    """
    if not filepath:
        return False

    if os.path.isfile(filepath):
        if os.access(filepath, os.X_OK):
            return True

        log.info(
            "Filepath is not available for execution \"{}\"".format(filepath)
        )
    return False


def find_executable(executable):
    """Find full path to executable.

    Also tries additional extensions if passed executable does not contain one.

    Paths where it is looked for executable is defined by 'PATH' environment
    variable, 'os.confstr("CS_PATH")' or 'os.defpath'.

    Args:
        executable(str): Name of executable with or without extension. Can be
            path to file.

    Returns:
        str: Full path to executable with extension (is file).
        None: When the executable was not found.
    """
    # Skip if passed path is file
    if is_file_executable(executable):
        return executable

    low_platform = platform.system().lower()
    _, ext = os.path.splitext(executable)

    # Prepare variants for which it will be looked
    variants = [executable]
    # Add other extension variants only if passed executable does not have one
    if not ext:
        if low_platform == "windows":
            exts = [".exe", ".ps1", ".bat"]
            for ext in os.getenv("PATHEXT", "").split(os.pathsep):
                ext = ext.lower()
                if ext and ext not in exts:
                    exts.append(ext)
        else:
            exts = [".sh"]

        for ext in exts:
            variant = executable + ext
            if is_file_executable(variant):
                return variant
            variants.append(variant)

    # Get paths where to look for executable
    path_str = os.environ.get("PATH", None)
    if path_str is None:
        if hasattr(os, "confstr"):
            path_str = os.confstr("CS_PATH")
        elif hasattr(os, "defpath"):
            path_str = os.defpath

    if path_str:
        paths = path_str.split(os.pathsep)
        for path in paths:
            for variant in variants:
                filepath = os.path.abspath(os.path.join(path, variant))
                if is_file_executable(filepath):
                    return filepath
    return None


def get_vendor_bin_path(bin_app):
    """Path to OpenPype vendorized binaries.

    Vendorized executables are expected in specific hierarchy inside build or
    in code source.

    "{OPENPYPE_ROOT}/vendor/bin/{name of vendorized app}/{platform}"

    Args:
        bin_app (str): Name of vendorized application.

    Returns:
        str: Path to vendorized binaries folder.
    """

    return os.path.join(
        os.environ["OPENPYPE_ROOT"],
        "vendor",
        "bin",
        bin_app,
        platform.system().lower()
    )


def find_tool_in_custom_paths(paths, tool, validation_func=None):
    """Find a tool executable in custom paths.

    Args:
        paths (Iterable[str]): Iterable of paths where to look for tool.
        tool (str): Name of tool (binary file) to find in passed paths.
        validation_func (Function): Custom validation function of path.
            Function must expect one argument which is path to executable.
            If not passed only 'find_executable' is used to be able identify
            if path is valid.

    Reuturns:
        Union[str, None]: Path to validated executable or None if was not
            found.
    """

    for path in paths:
        # Skip empty strings
        if not path:
            continue

        # Handle cases when path is just an executable
        #   - it allows to use executable from PATH
        #   - basename must match 'tool' value (without extension)
        extless_path, ext = os.path.splitext(path)
        if extless_path == tool:
            executable_path = find_executable(tool)
            if executable_path and (
                validation_func is None
                or validation_func(executable_path)
            ):
                return executable_path
            continue

        # Normalize path because it should be a path and check if exists
        normalized = os.path.normpath(path)
        if not os.path.exists(normalized):
            continue

        # Note: Path can be both file and directory

        # If path is a file validate it
        if os.path.isfile(normalized):
            basename, ext = os.path.splitext(os.path.basename(path))
            # Check if the filename has actually the sane bane as 'tool'
            if basename == tool:
                executable_path = find_executable(normalized)
                if executable_path and (
                    validation_func is None
                    or validation_func(executable_path)
                ):
                    return executable_path

        # Check if path is a directory and look for tool inside the dir
        if os.path.isdir(normalized):
            executable_path = find_executable(os.path.join(normalized, tool))
            if executable_path and (
                validation_func is None
                or validation_func(executable_path)
            ):
                return executable_path
    return None


def _check_args_returncode(args):
    try:
        # Python 2 compatibility where DEVNULL is not available
        if hasattr(subprocess, "DEVNULL"):
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait()
        else:
            with open(os.devnull, "w") as devnull:
                proc = subprocess.Popen(
                    args, stdout=devnull, stderr=devnull,
                )
                proc.wait()

    except Exception:
        return False
    return proc.returncode == 0


def _oiio_executable_validation(filepath):
    """Validate oiio tool executable if can be executed.

    Validation has 2 steps. First is using 'find_executable' to fill possible
    missing extension or fill directory then launch executable and validate
    that it can be executed. For that is used '--help' argument which is fast
    and does not need any other inputs.

    Any possible crash of missing libraries or invalid build should be catched.

    Main reason is to validate if executable can be executed on OS just running
    which can be issue ob linux machines.

    Note:
        It does not validate if the executable is really a oiio tool which
            should be used.

    Args:
        filepath (str): Path to executable.

    Returns:
        bool: Filepath is valid executable.
    """

    filepath = find_executable(filepath)
    if not filepath:
        return False

    return _check_args_returncode([filepath, "--help"])


def get_oiio_tools_path(tool="oiiotool"):
    """Path to vendorized OpenImageIO tool executables.

    On Window it adds .exe extension if missing from tool argument.

    Args:
        tool (string): Tool name (oiiotool, maketx, ...).
            Default is "oiiotool".
    """

    if CachedToolPaths.is_tool_cached(tool):
        return CachedToolPaths.get_executable_path(tool)

    custom_paths_str = os.environ.get("OPENPYPE_OIIO_PATHS") or ""
    tool_executable_path = find_tool_in_custom_paths(
        custom_paths_str.split(os.pathsep),
        tool,
        _oiio_executable_validation
    )

    if not tool_executable_path:
        oiio_dir = get_vendor_bin_path("oiio")
        if platform.system().lower() == "linux":
            oiio_dir = os.path.join(oiio_dir, "bin")
        default_path = os.path.join(oiio_dir, tool)
        if _oiio_executable_validation(default_path):
            tool_executable_path = default_path

    # Look to PATH for the tool
    if not tool_executable_path:
        from_path = find_executable(tool)
        if from_path and _oiio_executable_validation(from_path):
            tool_executable_path = from_path

    CachedToolPaths.cache_executable_path(tool, tool_executable_path)
    return tool_executable_path


def _ffmpeg_executable_validation(filepath):
    """Validate ffmpeg tool executable if can be executed.

    Validation has 2 steps. First is using 'find_executable' to fill possible
    missing extension or fill directory then launch executable and validate
    that it can be executed. For that is used '-version' argument which is fast
    and does not need any other inputs.

    Any possible crash of missing libraries or invalid build should be catched.

    Main reason is to validate if executable can be executed on OS just running
    which can be issue ob linux machines.

    Note:
        It does not validate if the executable is really a ffmpeg tool.

    Args:
        filepath (str): Path to executable.

    Returns:
        bool: Filepath is valid executable.
    """

    filepath = find_executable(filepath)
    if not filepath:
        return False

    return _check_args_returncode([filepath, "-version"])


def get_ffmpeg_tool_path(tool="ffmpeg"):
    """Path to vendorized FFmpeg executable.

    Args:
        tool (string): Tool name (ffmpeg, ffprobe, ...).
            Default is "ffmpeg".

    Returns:
        str: Full path to ffmpeg executable.
    """

    if CachedToolPaths.is_tool_cached(tool):
        return CachedToolPaths.get_executable_path(tool)

    custom_paths_str = os.environ.get("OPENPYPE_FFMPEG_PATHS") or ""
    tool_executable_path = find_tool_in_custom_paths(
        custom_paths_str.split(os.pathsep),
        tool,
        _ffmpeg_executable_validation
    )

    if not tool_executable_path:
        ffmpeg_dir = get_vendor_bin_path("ffmpeg")
        if platform.system().lower() == "windows":
            ffmpeg_dir = os.path.join(ffmpeg_dir, "bin")
        tool_path = find_executable(os.path.join(ffmpeg_dir, tool))
        if tool_path and _ffmpeg_executable_validation(tool_path):
            tool_executable_path = tool_path

    # Look to PATH for the tool
    if not tool_executable_path:
        from_path = find_executable(tool)
        if from_path and _oiio_executable_validation(from_path):
            tool_executable_path = from_path

    CachedToolPaths.cache_executable_path(tool, tool_executable_path)
    return tool_executable_path


def is_oiio_supported():
    """Checks if oiiotool is configured for this platform.

    Returns:
        bool: OIIO tool executable is available.
    """
    loaded_path = oiio_path = get_oiio_tools_path()
    if oiio_path:
        oiio_path = find_executable(oiio_path)

    if not oiio_path:
        log.debug("OIIOTool is not configured or not present at {}".format(
            loaded_path
        ))
        return False
    return True
