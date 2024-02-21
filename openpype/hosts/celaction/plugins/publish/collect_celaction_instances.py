import os
import pyblish.api

from openpype.client import get_asset_name_identifier


class CollectCelactionInstances(pyblish.api.ContextPlugin):
    """ Adds the celaction render instances """

    label = "Collect Celaction Instances"
    order = pyblish.api.CollectorOrder + 0.1

    def process(self, context):
        task = context.data["task"]
        current_file = context.data["currentFile"]
        staging_dir = os.path.dirname(current_file)
        scene_file = os.path.basename(current_file)
        version = context.data["version"]
        asset_entity = context.data["assetEntity"]
        project_entity = context.data["projectEntity"]

        asset_name = get_asset_name_identifier(asset_entity)

        shared_instance_data = {
            "asset": asset_name,
            "frameStart": asset_entity["data"]["frameStart"],
            "frameEnd": asset_entity["data"]["frameEnd"],
            "handleStart": asset_entity["data"]["handleStart"],
            "handleEnd": asset_entity["data"]["handleEnd"],
            "fps": asset_entity["data"]["fps"],
            "resolutionWidth": asset_entity["data"].get(
                "resolutionWidth",
                project_entity["data"]["resolutionWidth"]),
            "resolutionHeight": asset_entity["data"].get(
                "resolutionHeight",
                project_entity["data"]["resolutionHeight"]),
            "pixelAspect": 1,
            "step": 1,
            "version": version
        }

        celaction_kwargs = context.data.get(
            "passingKwargs", {})

        if celaction_kwargs:
            shared_instance_data.update(celaction_kwargs)

        # workfile instance
        family = "workfile"
        subset = family + task.capitalize()
        # Create instance
        instance = context.create_instance(subset)

        # creating instance data
        instance.data.update({
            "subset": subset,
            "label": scene_file,
            "family": family,
            "families": [],
            "representations": []
        })

        # adding basic script data
        instance.data.update(shared_instance_data)

        # creating representation
        representation = {
            'name': 'scn',
            'ext': 'scn',
            'files': scene_file,
            "stagingDir": staging_dir,
        }

        instance.data["representations"].append(representation)

        self.log.info('Publishing Celaction workfile')

        # render instance
        subset = f"render{task}Main"
        instance = context.create_instance(name=subset)
        # getting instance state
        instance.data["publish"] = True

        # add assetEntity data into instance
        instance.data.update({
            "label": "{} - farm".format(subset),
            "family": "render.farm",
            "families": [],
            "subset": subset
        })

        # adding basic script data
        instance.data.update(shared_instance_data)

        self.log.info('Publishing Celaction render instance')
        self.log.debug(f"Instance data: `{instance.data}`")

        for i in context:
            self.log.debug(f"{i.data['families']}")
