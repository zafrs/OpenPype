import os
import re
import sys
import logging

# Pipeline imports
from openpype.pipeline import (
    legacy_io,
    install_host,
    registered_host,
)
from openpype.lib import version_up
from openpype.hosts.fusion import api
from openpype.hosts.fusion.api import lib
from openpype.lib.avalon_context import get_workdir_from_session

log = logging.getLogger("Update Slap Comp")

self = sys.modules[__name__]
self._project = None


def _format_version_folder(folder):
    """Format a version folder based on the filepath

    Assumption here is made that, if the path does not exists the folder
    will be "v001"

    Args:
        folder: file path to a folder

    Returns:
        str: new version folder name
    """

    new_version = 1
    if os.path.isdir(folder):
        re_version = re.compile(r"v\d+$")
        versions = [i for i in os.listdir(folder) if os.path.isdir(i)
                    and re_version.match(i)]
        if versions:
            # ensure the "v" is not included
            new_version = int(max(versions)[1:]) + 1

    version_folder = "v{:03d}".format(new_version)

    return version_folder


def _get_fusion_instance():
    fusion = getattr(sys.modules["__main__"], "fusion", None)
    if fusion is None:
        try:
            # Support for FuScript.exe, BlackmagicFusion module for py2 only
            import BlackmagicFusion as bmf
            fusion = bmf.scriptapp("Fusion")
        except ImportError:
            raise RuntimeError("Could not find a Fusion instance")
    return fusion


def _format_filepath(session):

    project = session["AVALON_PROJECT"]
    asset = session["AVALON_ASSET"]

    # Save updated slap comp
    work_path = get_workdir_from_session(session)
    walk_to_dir = os.path.join(work_path, "scenes", "slapcomp")
    slapcomp_dir = os.path.abspath(walk_to_dir)

    # Ensure destination exists
    if not os.path.isdir(slapcomp_dir):
        log.warning("Folder did not exist, creating folder structure")
        os.makedirs(slapcomp_dir)

    # Compute output path
    new_filename = "{}_{}_slapcomp_v001.comp".format(project, asset)
    new_filepath = os.path.join(slapcomp_dir, new_filename)

    # Create new unique filepath
    if os.path.exists(new_filepath):
        new_filepath = version_up(new_filepath)

    return new_filepath


def _update_savers(comp, session):
    """Update all savers of the current comp to ensure the output is correct

    This will refactor the Saver file outputs to the renders of the new session
    that is provided.

    In the case the original saver path had a path set relative to a /fusion/
    folder then that relative path will be matched with the exception of all
    "version" (e.g. v010) references will be reset to v001. Otherwise only a
    version folder will be computed in the new session's work "render" folder
    to dump the files in and keeping the original filenames.

    Args:
        comp (object): current comp instance
        session (dict): the current Avalon session

    Returns:
         None
    """

    new_work = get_workdir_from_session(session)
    renders = os.path.join(new_work, "renders")
    version_folder = _format_version_folder(renders)
    renders_version = os.path.join(renders, version_folder)

    comp.Print("New renders to: %s\n" % renders)

    with api.comp_lock_and_undo_chunk(comp):
        savers = comp.GetToolList(False, "Saver").values()
        for saver in savers:
            filepath = saver.GetAttrs("TOOLST_Clip_Name")[1.0]

            # Get old relative path to the "fusion" app folder so we can apply
            # the same relative path afterwards. If not found fall back to
            # using just a version folder with the filename in it.
            # todo: can we make this less magical?
            relpath = filepath.replace("\\", "/").rsplit("/fusion/", 1)[-1]

            if os.path.isabs(relpath):
                # If not relative to a "/fusion/" folder then just use filename
                filename = os.path.basename(filepath)
                log.warning("Can't parse relative path, refactoring to only"
                            "filename in a version folder: %s" % filename)
                new_path = os.path.join(renders_version, filename)

            else:
                # Else reuse the relative path
                # Reset version in folder and filename in the relative path
                # to v001. The version should be is only detected when prefixed
                # with either `_v` (underscore) or `/v` (folder)
                version_pattern = r"(/|_)v[0-9]+"
                if re.search(version_pattern, relpath):
                    new_relpath = re.sub(version_pattern,
                                         r"\1v001",
                                         relpath)
                    log.info("Resetting version folders to v001: "
                             "%s -> %s" % (relpath, new_relpath))
                    relpath = new_relpath

                new_path = os.path.join(new_work, relpath)

            saver["Clip"] = new_path


def update_frame_range(comp, representations):
    """Update the frame range of the comp and render length

    The start and end frame are based on the lowest start frame and the highest
    end frame

    Args:
        comp (object): current focused comp
        representations (list) collection of dicts

    Returns:
        None

    """

    version_ids = [r["parent"] for r in representations]
    versions = legacy_io.find({"type": "version", "_id": {"$in": version_ids}})
    versions = list(versions)

    versions = [v for v in versions
                if v["data"].get("frameStart", None) is not None]

    if not versions:
        log.warning("No versions loaded to match frame range to.\n")
        return

    start = min(v["data"]["frameStart"] for v in versions)
    end = max(v["data"]["frameEnd"] for v in versions)

    lib.update_frame_range(start, end, comp=comp)


def switch(asset_name, filepath=None, new=True):
    """Switch the current containers of the file to the other asset (shot)

    Args:
        filepath (str): file path of the comp file
        asset_name (str): name of the asset (shot)
        new (bool): Save updated comp under a different name

    Returns:
        comp path (str): new filepath of the updated comp

    """

    # If filepath provided, ensure it is valid absolute path
    if filepath is not None:
        if not os.path.isabs(filepath):
            filepath = os.path.abspath(filepath)

        assert os.path.exists(filepath), "%s must exist " % filepath

    # Assert asset name exists
    # It is better to do this here then to wait till switch_shot does it
    asset = legacy_io.find_one({"type": "asset", "name": asset_name})
    assert asset, "Could not find '%s' in the database" % asset_name

    # Get current project
    self._project = legacy_io.find_one({"type": "project"})

    # Go to comp
    if not filepath:
        current_comp = api.get_current_comp()
        assert current_comp is not None, "Could not find current comp"
    else:
        fusion = _get_fusion_instance()
        current_comp = fusion.LoadComp(filepath, quiet=True)
        assert current_comp is not None, (
            "Fusion could not load '{}'").format(filepath)

    host = registered_host()
    containers = list(host.ls())
    assert containers, "Nothing to update"

    representations = []
    for container in containers:
        try:
            representation = lib.switch_item(
                container,
                asset_name=asset_name)
            representations.append(representation)
        except Exception as e:
            current_comp.Print("Error in switching! %s\n" % e.message)

    message = "Switched %i Loaders of the %i\n" % (len(representations),
                                                   len(containers))
    current_comp.Print(message)

    # Build the session to switch to
    switch_to_session = legacy_io.Session.copy()
    switch_to_session["AVALON_ASSET"] = asset['name']

    if new:
        comp_path = _format_filepath(switch_to_session)

        # Update savers output based on new session
        _update_savers(current_comp, switch_to_session)
    else:
        comp_path = version_up(filepath)

    current_comp.Print(comp_path)

    current_comp.Print("\nUpdating frame range")
    update_frame_range(current_comp, representations)

    current_comp.Save(comp_path)

    return comp_path


if __name__ == '__main__':

    # QUESTION: can we convert this to gui rather then standalone script?
    # TODO: convert to gui tool
    import argparse

    parser = argparse.ArgumentParser(description="Switch to a shot within an"
                                                 "existing comp file")

    parser.add_argument("--file_path",
                        type=str,
                        default=True,
                        help="File path of the comp to use")

    parser.add_argument("--asset_name",
                        type=str,
                        default=True,
                        help="Name of the asset (shot) to switch")

    args, unknown = parser.parse_args()

    install_host(api)
    switch(args.asset_name, args.file_path)

    sys.exit(0)
