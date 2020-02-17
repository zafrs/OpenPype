import os
import json
import re
import logging

from avalon import api, io
from avalon.vendor import requests, clique

import pyblish.api


R_FRAME_NUMBER = re.compile(r'.+\.(?P<frame>[0-9]+)\..+')


def _get_script():
    """Get path to the image sequence script"""
    try:
        from pype.scripts import publish_filesequence
    except Exception:
        assert False, "Expected module 'publish_deadline'to be available"

    module_path = publish_filesequence.__file__
    if module_path.endswith(".pyc"):
        module_path = module_path[: -len(".pyc")] + ".py"

    module_path = os.path.normpath(module_path)
    mount_root = os.path.normpath(os.environ["PYPE_STUDIO_CORE_MOUNT"])
    network_root = os.path.normpath(os.environ["PYPE_STUDIO_CORE_PATH"])

    module_path = module_path.replace(mount_root, network_root)

    return module_path


# Logic to retrieve latest files concerning extendFrames
def get_latest_version(asset_name, subset_name, family):
    # Get asset
    asset_name = io.find_one(
        {"type": "asset", "name": asset_name}, projection={"name": True}
    )

    subset = io.find_one(
        {"type": "subset", "name": subset_name, "parent": asset_name["_id"]},
        projection={"_id": True, "name": True},
    )

    # Check if subsets actually exists (pre-run check)
    assert subset, "No subsets found, please publish with `extendFrames` off"

    # Get version
    version_projection = {
        "name": True,
        "data.startFrame": True,
        "data.endFrame": True,
        "parent": True,
    }

    version = io.find_one(
        {"type": "version", "parent": subset["_id"], "data.families": family},
        projection=version_projection,
        sort=[("name", -1)],
    )

    assert version, "No version found, this is a bug"

    return version


def get_resources(version, extension=None):
    """
    Get the files from the specific version
    """
    query = {"type": "representation", "parent": version["_id"]}
    if extension:
        query["name"] = extension

    representation = io.find_one(query)
    assert representation, "This is a bug"

    directory = api.get_representation_path(representation)
    print("Source: ", directory)
    resources = sorted(
        [
            os.path.normpath(os.path.join(directory, fname))
            for fname in os.listdir(directory)
        ]
    )

    return resources


def get_resource_files(resources, frame_range, override=True):

    res_collections, _ = clique.assemble(resources)
    assert len(res_collections) == 1, "Multiple collections found"
    res_collection = res_collections[0]

    # Remove any frames
    if override:
        for frame in frame_range:
            if frame not in res_collection.indexes:
                continue
            res_collection.indexes.remove(frame)

    return list(res_collection)


class ProcessSubmittedJobOnFarm(pyblish.api.InstancePlugin):
    """Process Job submitted on farm.

    These jobs are dependent on a deadline or muster job
    submission prior to this plug-in.

    - In case of Deadline, it creates dependend job on farm publishing
      rendered image sequence.

    - In case of Muster, there is no need for such thing as dependend job,
      post action will be executed and rendered sequence will be published.

    Options in instance.data:
        - deadlineSubmissionJob (dict, Required): The returned .json
          data from the job submission to deadline.

        - musterSubmissionJob (dict, Required): same as deadline.

        - outputDir (str, Required): The output directory where the metadata
            file should be generated. It's assumed that this will also be
            final folder containing the output files.

        - ext (str, Optional): The extension (including `.`) that is required
            in the output filename to be picked up for image sequence
            publishing.

        - publishJobState (str, Optional): "Active" or "Suspended"
            This defaults to "Suspended"

    This requires a "frameStart" and "frameEnd" to be present in instance.data
    or in context.data.

    """

    label = "Submit image sequence jobs to Deadline or Muster"
    order = pyblish.api.IntegratorOrder + 0.2
    icon = "tractor"

    hosts = ["fusion", "maya", "nuke"]

    families = ["render.farm", "renderlayer", "imagesequence"]

    aov_filter = {"maya": ["beauty"]}

    enviro_filter = [
        "PATH",
        "PYTHONPATH",
        "FTRACK_API_USER",
        "FTRACK_API_KEY",
        "FTRACK_SERVER",
        "PYPE_ROOT",
        "PYPE_METADATA_FILE",
        "PYPE_STUDIO_PROJECTS_PATH",
        "PYPE_STUDIO_PROJECTS_MOUNT",
    ]

    # pool used to do the publishing job
    deadline_pool = ""

    def _submit_deadline_post_job(self, instance, job):
        """
        Deadline specific code separated from :meth:`process` for sake of
        more universal code. Muster post job is sent directly by Muster
        submitter, so this type of code isn't necessary for it.
        """
        data = instance.data.copy()
        subset = data["subset"]
        job_name = "{batch} - {subset} [publish image sequence]".format(
            batch=job["Props"]["Name"], subset=subset
        )

        metadata_filename = "{}_metadata.json".format(subset)
        output_dir = instance.data["outputDir"]
        metadata_path = os.path.join(output_dir, metadata_filename)

        metadata_path = os.path.normpath(metadata_path)
        mount_root = os.path.normpath(os.environ["PYPE_STUDIO_PROJECTS_MOUNT"])
        network_root = os.path.normpath(
            os.environ["PYPE_STUDIO_PROJECTS_PATH"]
        )

        metadata_path = metadata_path.replace(mount_root, network_root)

        # Generate the payload for Deadline submission
        payload = {
            "JobInfo": {
                "Plugin": "Python",
                "BatchName": job["Props"]["Batch"],
                "Name": job_name,
                "JobDependency0": job["_id"],
                "UserName": job["Props"]["User"],
                "Comment": instance.context.data.get("comment", ""),
                "Priority": job["Props"]["Pri"],
                "Pool": self.deadline_pool
            },
            "PluginInfo": {
                "Version": "3.6",
                "ScriptFile": _get_script(),
                "Arguments": "",
                "SingleFrameOnly": "True",
            },
            # Mandatory for Deadline, may be empty
            "AuxFiles": [],
        }

        # Transfer the environment from the original job to this dependent
        # job so they use the same environment

        environment = job["Props"].get("Env", {})
        environment["PYPE_METADATA_FILE"] = metadata_path
        i = 0
        for index, key in enumerate(environment):
            self.log.info("KEY: {}".format(key))
            self.log.info("FILTER: {}".format(self.enviro_filter))

            if key.upper() in self.enviro_filter:
                payload["JobInfo"].update(
                    {
                        "EnvironmentKeyValue%d"
                        % i: "{key}={value}".format(
                            key=key, value=environment[key]
                        )
                    }
                )
                i += 1

        # Avoid copied pools and remove secondary pool
        payload["JobInfo"]["Pool"] = "none"
        payload["JobInfo"].pop("SecondaryPool", None)

        self.log.info("Submitting..")
        self.log.info(json.dumps(payload, indent=4, sort_keys=True))

        url = "{}/api/jobs".format(self.DEADLINE_REST_URL)
        response = requests.post(url, json=payload)
        if not response.ok:
            raise Exception(response.text)

    def _create_instances_for_aov(self, context, instance_data, exp_files):
        task = os.environ["AVALON_TASK"]
        subset = instance_data["subset"]
        instances = []
        for aov, files in exp_files.items():
            cols, rem = clique.assemble(files)
            # we shouldn't have any reminders
            if rem:
                self.log.warning(
                    "skipping unexpected files found "
                    "in sequence: {}".format(rem))

            # but we really expect only one collection, nothing else make sense
            self.log.error("got {} sequence type".format(len(cols)))
            assert len(cols) == 1, "only one image sequence type is expected"

            # create subset name `familyTaskSubset_AOV`
            subset_name = 'render{}{}{}{}_{}'.format(
                task[0].upper(), task[1:],
                subset[0].upper(), subset[1:],
                aov)

            staging = os.path.dirname(list(cols[0])[0])
            start = int(instance_data.get("frameStart"))
            end = int(instance_data.get("frameEnd"))

            new_instance = self.context.create_instance(subset_name)
            app = os.environ.get("AVALON_APP", "")

            preview = False
            if app in self.aov_filter.keys():
                if aov in self.aov_filter[app]:
                    preview = True

            new_instance.data.update(instance_data)
            new_instance.data["subset"] = subset_name
            ext = cols[0].tail.lstrip(".")
            rep = {
                "name": ext,
                "ext": ext,
                "files": [os.path.basename(f) for f in list(cols[0])],
                "frameStart": start,
                "frameEnd": end,
                # If expectedFile are absolute, we need only filenames
                "stagingDir": staging,
                "anatomy_template": "render",
                "fps": new_instance.data.get("fps"),
                "tags": ["review", "preview"] if preview else []
            }

            # if extending frames from existing version, copy files from there
            # into our destination directory
            if instance_data.get("extendFrames", False):
                self.log.info("Preparing to copy ...")
                import speedcopy

                # get latest version of subset
                # this will stop if subset wasn't published yet
                version = get_latest_version(
                    instance_data.get("asset"),
                    subset_name, "render")
                # get its files based on extension
                subset_resources = get_resources(version, ext)
                r_col, _ = clique.assemble(subset_resources)

                # if override remove all frames we are expecting to be rendered
                # so we'll copy only those missing from current render
                if instance_data.get("overrideExistingFrame"):
                    for frame in range(start, end+1):
                        if frame not in r_col.indexes:
                            continue
                        r_col.indexes.remove(frame)

                # now we need to translate published names from represenation
                # back. This is tricky, right now we'll just use same naming
                # and only switch frame numbers
                resource_files = []
                r_filename = os.path.basename(list(cols[0])[0])  # first file
                op = re.search(R_FRAME_NUMBER, r_filename)
                pre = r_filename[:op.start("frame")]
                post = r_filename[op.end("frame"):]
                assert op is not None, "padding string wasn't found"
                for frame in list(r_col):
                    fn = re.search(R_FRAME_NUMBER, frame)
                    # silencing linter as we need to compare to True, not to
                    # type
                    assert fn is not None, "padding string wasn't found"
                    # list of tuples (source, destination)
                    resource_files.append(
                        (frame,
                         os.path.join(staging,
                                      "{}{}{}".format(pre,
                                                      fn.group("frame"),
                                                      post)))
                    )

                for source in resource_files:
                    speedcopy.copy(source[0], source[1])

                self.log.info(
                    "Finished copying %i files" % len(resource_files))

            if preview:
                if "ftrack" not in new_instance.data["families"]:
                    if os.environ.get("FTRACK_SERVER"):
                        new_instance.data["families"].append("ftrack")
                if "review" not in new_instance.data["families"]:
                    new_instance.data["families"].append("review")

            new_instance.data["representations"] = [rep]
            instances.append(new_instance)

        return instances

    def _get_representations(self, instance, exp_files):
        representations = []
        start = int(instance.data.get("frameStart"))
        end = int(instance.data.get("frameEnd"))
        cols, rem = clique.assemble(exp_files)
        # create representation for every collected sequence
        for c in cols:
            ext = c.tail.lstrip(".")
            preview = False
            # if filtered aov name is found in filename, toggle it for
            # preview video rendering
            for app in self.aov_filter:
                if os.environ.get("AVALON_APP", "") == app:
                    for aov in self.aov_filter[app]:
                        if re.match(
                            r".+(?:\.|_)({})(?:\.|_).*".format(aov),
                            list(c)[0]
                        ):
                            preview = True
                            break
                break
            rep = {
                "name": str(c),
                "ext": ext,
                "files": [os.path.basename(f) for f in list(c)],
                "frameStart": start,
                "frameEnd": end,
                # If expectedFile are absolute, we need only filenames
                "stagingDir": os.path.dirname(list(c)[0]),
                "anatomy_template": "render",
                "fps": instance.data.get("fps"),
                "tags": ["review", "preview"] if preview else [],
            }

            representations.append(rep)

            # TODO: implement extendFrame

            families = instance.data.get("families")
            # if we have one representation with preview tag
            # flag whole instance for review and for ftrack
            if preview:
                if "ftrack" not in families:
                    if os.environ.get("FTRACK_SERVER"):
                        families.append("ftrack")
                if "review" not in families:
                    families.append("review")
                instance.data["families"] = families

        for r in rem:
            ext = r.split(".")[-1]
            rep = {
                "name": r,
                "ext": ext,
                "files": os.path.basename(r),
                "stagingDir": os.path.dirname(r),
                "anatomy_template": "publish",
            }

            representations.append(rep)

        return representations

    def process(self, instance):
        """
        Detect type of renderfarm submission and create and post dependend job
        in case of Deadline. It creates json file with metadata needed for
        publishing in directory of render.

        :param instance: Instance data
        :type instance: dict
        """

        data = instance.data.copy()
        context = instance.context
        self.context = context

        if hasattr(instance, "_log"):
            data['_log'] = instance._log
        render_job = data.pop("deadlineSubmissionJob", None)
        submission_type = "deadline"
        if not render_job:
            # No deadline job. Try Muster: musterSubmissionJob
            render_job = data.pop("musterSubmissionJob", None)
            submission_type = "muster"
            assert render_job, (
                "Can't continue without valid Deadline "
                "or Muster submission prior to this "
                "plug-in."
            )

        if submission_type == "deadline":
            self.DEADLINE_REST_URL = os.environ.get(
                "DEADLINE_REST_URL", "http://localhost:8082"
            )
            assert self.DEADLINE_REST_URL, "Requires DEADLINE_REST_URL"

            self._submit_deadline_post_job(instance, render_job)

        asset = data.get("asset") or api.Session["AVALON_ASSET"]
        subset = data.get("subset")

        start = instance.data.get("frameStart")
        if start is None:
            start = context.data["frameStart"]
        end = instance.data.get("frameEnd")
        if end is None:
            end = context.data["frameEnd"]

        if data.get("extendFrames", False):
            start, end = self._extend_frames(
                asset,
                subset,
                start,
                end,
                data["overrideExistingFrame"])

        try:
            source = data["source"]
        except KeyError:
            source = context.data["currentFile"]

        source = source.replace(
            os.getenv("PYPE_STUDIO_PROJECTS_MOUNT"), api.registered_root()
        )
        relative_path = os.path.relpath(source, api.registered_root())
        source = os.path.join("{root}", relative_path).replace("\\", "/")
        regex = None

        families = ["render"]

        instance_skeleton_data = {
            "family": "render",
            "subset": subset,
            "families": families,
            "asset": asset,
            "frameStart": start,
            "frameEnd": end,
            "fps": data.get("fps", 25),
            "source": source,
            "extendFrames": data.get("extendFrames"),
            "overrideExistingFrame": data.get("overrideExistingFrame")
        }

        instances = None
        if data.get("expectedFiles"):
            """
            if content of `expectedFiles` are dictionaries, we will handle
            it as list of AOVs, creating instance from every one of them.

            Example:
            --------

            expectedFiles = [
                {
                    "beauty": [
                        "foo_v01.0001.exr",
                        "foo_v01.0002.exr"
                    ],
                    "Z": [
                        "boo_v01.0001.exr",
                        "boo_v01.0002.exr"
                    ]
                }
            ]

            This will create instances for `beauty` and `Z` subset
            adding those files to their respective representations.

            If we've got only list of files, we collect all filesequences.
            More then one doesn't probably make sense, but we'll handle it
            like creating one instance with multiple representations.

            Example:
            --------

            expectedFiles = [
                "foo_v01.0001.exr",
                "foo_v01.0002.exr",
                "xxx_v01.0001.exr",
                "xxx_v01.0002.exr"
            ]

            This will result in one instance with two representations:
            `foo` and `xxx`
            """
            if isinstance(data.get("expectedFiles")[0], dict):
                instances = self._create_instances_for_aov(
                    instance_skeleton_data,
                    data.get("expectedFiles"))
            else:
                representations = self._get_representations(
                    instance_skeleton_data,
                    data.get("expectedFiles")
                )

                if "representations" not in instance.data:
                    data["representations"] = []

                # add representation
                data["representations"] += representations

        else:
            # deprecated: passing regex is depecated. Please use
            # `expectedFiles` and collect them.
            if "ext" in instance.data:
                ext = r"\." + re.escape(instance.data["ext"])
            else:
                ext = r"\.\D+"

            regex = r"^{subset}.*\d+{ext}$".format(
                subset=re.escape(subset), ext=ext)
        # Write metadata for publish job
        # publish job file
        publish_job = {
            "asset": asset,
            "frameStart": start,
            "frameEnd": end,
            "fps": context.data.get("fps", None),
            "families": families,
            "source": source,
            "user": context.data["user"],
            "version": context.data["version"],
            "intent": context.data.get("intent"),
            "comment": context.data.get("comment"),
            "job": render_job,
            "session": api.Session.copy(),
            "instances": instances or [data]
        }

        # pass Ftrack credentials in case of Muster
        if submission_type == "muster":
            ftrack = {
                "FTRACK_API_USER": os.environ.get("FTRACK_API_USER"),
                "FTRACK_API_KEY": os.environ.get("FTRACK_API_KEY"),
                "FTRACK_SERVER": os.environ.get("FTRACK_SERVER"),
            }
            publish_job.update({"ftrack": ftrack})

        if regex:
            publish_job["regex"] = regex

        # Ensure output dir exists
        output_dir = instance.data["outputDir"]
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)

        # TODO: remove this code
        # deprecated: this is left here for backwards compatibility and is
        # not probably working at all. :hammer:
        if data.get("extendFrames", False) \
           and not data.get("expectedFiles", False):

            family = "render"
            override = data["overrideExistingFrame"]

            # override = data.get("overrideExistingFrame", False)
            out_file = render_job.get("OutFile")
            if not out_file:
                raise RuntimeError("OutFile not found in render job!")

            extension = os.path.splitext(out_file[0])[1]
            _ext = extension[1:]

            # Frame comparison
            prev_start = None
            prev_end = None
            resource_range = range(int(start), int(end)+1)

            # Gather all the subset files (one subset per render pass!)
            subset_names = [data["subset"]]
            subset_names.extend(data.get("renderPasses", []))
            resources = []
            for subset_name in subset_names:
                version = get_latest_version(asset_name=data["asset"],
                                             subset_name=subset_name,
                                             family=family)

                # Set prev start / end frames for comparison
                if not prev_start and not prev_end:
                    prev_start = version["data"]["frameStart"]
                    prev_end = version["data"]["frameEnd"]

                subset_resources = get_resources(version, _ext)
                resource_files = get_resource_files(subset_resources,
                                                    resource_range,
                                                    override)

                resources.extend(resource_files)

            updated_start = min(start, prev_start)
            updated_end = max(end, prev_end)

            # Update metadata and instance start / end frame
            self.log.info("Updating start / end frame : "
                          "{} - {}".format(updated_start, updated_end))

            # TODO : Improve logic to get new frame range for the
            # publish job (publish_filesequence.py)
            # The current approach is not following Pyblish logic
            # which is based
            # on Collect / Validate / Extract.

            # ---- Collect Plugins  ---
            # Collect Extend Frames - Only run if extendFrames is toggled
            # # # Store in instance:
            # # # Previous rendered files per subset based on frames
            # # # --> Add to instance.data[resources]
            # # # Update publish frame range

            # ---- Validate Plugins ---
            # Validate Extend Frames
            # # # Check if instance has the requirements to extend frames
            # There might have been some things which can be added to the list
            # Please do so when fixing this.

            # Start frame
            metadata["frameStart"] = updated_start
            metadata["metadata"]["instance"]["frameStart"] = updated_start

            # End frame
            metadata["frameEnd"] = updated_end
            metadata["metadata"]["instance"]["frameEnd"] = updated_end

        metadata_filename = "{}_metadata.json".format(subset)

        metadata_path = os.path.join(output_dir, metadata_filename)
        # convert log messages if they are `LogRecord` to their
        # string format to allow serializing as JSON later on.
        rendered_logs = []
        for log in metadata["metadata"]["instance"].get("_log", []):
            if isinstance(log, logging.LogRecord):
                rendered_logs.append(log.getMessage())
            else:
                rendered_logs.append(log)

        metadata["metadata"]["instance"]["_log"] = rendered_logs
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=4, sort_keys=True)

        # Copy files from previous render if extendFrame is True
        if data.get("extendFrames", False):

            self.log.info("Preparing to copy ..")
            import shutil

            dest_path = data["outputDir"]
            for source in resources:
                src_file = os.path.basename(source)
                dest = os.path.join(dest_path, src_file)
                shutil.copy(source, dest)

            self.log.info("Finished copying %i files" % len(resources))

    def _extend_frames(self, asset, subset, start, end, override):
        family = "render"
        # override = data.get("overrideExistingFrame", False)

        # Frame comparison
        prev_start = None
        prev_end = None

        version = get_latest_version(
            asset_name=asset,
            subset_name=subset,
            family=family,
        )

        # Set prev start / end frames for comparison
        if not prev_start and not prev_end:
            prev_start = version["data"]["frameStart"]
            prev_end = version["data"]["frameEnd"]

        updated_start = min(start, prev_start)
        updated_end = max(end, prev_end)

        # Update metadata and instance start / end frame
        self.log.info(
            "Updating start / end frame : "
            "{} - {}".format(updated_start, updated_end)
        )

        return updated_start, updated_end
