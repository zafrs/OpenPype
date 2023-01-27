import os
import re

import pyblish.api

from openpype.lib import prepare_template_data
from openpype.hosts.photoshop import api as photoshop
from openpype.settings import get_project_settings
from openpype.tests.lib import is_in_tests


class CollectColorCodedInstances(pyblish.api.ContextPlugin):
    """Creates instances for layers marked by configurable color.

    Used in remote publishing when artists marks publishable layers by color-
    coding. Top level layers (group) must be marked by specific color to be
    published as an instance of 'image' family.

    Can add group for all publishable layers to allow creation of flattened
    image. (Cannot contain special background layer as it cannot be grouped!)

    Based on value `create_flatten_image` from Settings:
    - "yes": create flattened 'image' subset of all publishable layers + create
        'image' subset per publishable layer
    - "only": create ONLY flattened 'image' subset of all publishable layers
    - "no": do not create flattened 'image' subset at all,
        only separate subsets per marked layer.

    Identifier:
        id (str): "pyblish.avalon.instance"
    """
    order = pyblish.api.CollectorOrder + 0.100

    label = "Instances"
    order = pyblish.api.CollectorOrder
    hosts = ["photoshop"]
    targets = ["remotepublish"]

    # configurable by Settings
    color_code_mapping = []
    # TODO check if could be set globally, probably doesn't make sense when
    # flattened template cannot
    subset_template_name = ""
    create_flatten_image = "no"
    flatten_subset_template = ""

    def process(self, context):
        self.log.info("CollectColorCodedInstances")
        batch_dir = os.environ.get("OPENPYPE_PUBLISH_DATA")
        if (is_in_tests() and
                (not batch_dir or not os.path.exists(batch_dir))):
            self.log.debug("Automatic testing, no batch data, skipping")
            return

        existing_subset_names = self._get_existing_subset_names(context)

        # from CollectBatchData
        asset_name = context.data["asset"]
        task_name = context.data["task"]
        variant = context.data["variant"]
        project_name = context.data["projectEntity"]["name"]

        naming_conventions = get_project_settings(project_name).get(
            "photoshop", {}).get(
            "publish", {}).get(
            "ValidateNaming", {})

        stub = photoshop.stub()
        layers = stub.get_layers()

        publishable_layers = []
        created_instances = []
        family_from_settings = None
        for layer in layers:
            self.log.debug("Layer:: {}".format(layer))
            if layer.parents:
                self.log.debug("!!! Not a top layer, skip")
                continue

            if not layer.visible:
                self.log.debug("Not visible, skip")
                continue

            resolved_family, resolved_subset_template = self._resolve_mapping(
                layer
            )

            if not resolved_subset_template or not resolved_family:
                self.log.debug("!!! Not found family or template, skip")
                continue

            if not family_from_settings:
                family_from_settings = resolved_family

            fill_pairs = {
                "variant": variant,
                "family": resolved_family,
                "task": task_name,
                "layer": layer.clean_name
            }

            subset = resolved_subset_template.format(
                **prepare_template_data(fill_pairs))

            subset = self._clean_subset_name(stub, naming_conventions,
                                             subset, layer)

            if subset in existing_subset_names:
                self.log.info(
                    "Subset {} already created, skipping.".format(subset))
                continue

            if self.create_flatten_image != "flatten_only":
                instance = self._create_instance(context, layer,
                                                 resolved_family,
                                                 asset_name, subset, task_name)
                created_instances.append(instance)

            existing_subset_names.append(subset)
            publishable_layers.append(layer)

        if self.create_flatten_image != "no" and publishable_layers:
            self.log.debug("create_flatten_image")
            if not self.flatten_subset_template:
                self.log.warning("No template for flatten image")
                return

            fill_pairs.pop("layer")
            subset = self.flatten_subset_template.format(
                **prepare_template_data(fill_pairs))

            first_layer = publishable_layers[0]  # dummy layer
            first_layer.name = subset
            family = family_from_settings  # inherit family
            instance = self._create_instance(context, first_layer,
                                             family,
                                             asset_name, subset, task_name)
            instance.data["ids"] = [layer.id for layer in publishable_layers]
            created_instances.append(instance)

        for instance in created_instances:
            # Produce diagnostic message for any graphical
            # user interface interested in visualising it.
            self.log.info("Found: \"%s\" " % instance.data["name"])
            self.log.info("instance: {} ".format(instance.data))

    def _get_existing_subset_names(self, context):
        """Collect manually created instances from workfile.

        Shouldn't be any as Webpublisher bypass publishing via Openpype, but
        might be some if workfile published through OP is reused.
        """
        existing_subset_names = []
        for instance in context:
            if instance.data.get('publish'):
                existing_subset_names.append(instance.data.get('subset'))

        return existing_subset_names

    def _create_instance(self, context, layer, family,
                         asset, subset, task_name):
        instance = context.create_instance(layer.name)
        instance.data["family"] = family
        instance.data["publish"] = True
        instance.data["asset"] = asset
        instance.data["task"] = task_name
        instance.data["subset"] = subset
        instance.data["layer"] = layer
        instance.data["families"] = []

        return instance

    def _resolve_mapping(self, layer):
        """Matches 'layer' color code and name to mapping.

            If both color code AND name regex is configured, BOTH must be valid
            If layer matches to multiple mappings, only first is used!
        """
        family_list = []
        family = None
        subset_name_list = []
        resolved_subset_template = None
        for mapping in self.color_code_mapping:
            if mapping["color_code"] and \
                    layer.color_code not in mapping["color_code"]:
                continue

            if mapping["layer_name_regex"] and \
                    not any(re.search(pattern, layer.name)
               for pattern in mapping["layer_name_regex"]):
                continue

            family_list.append(mapping["family"])
            subset_name_list.append(mapping["subset_template_name"])
        if len(subset_name_list) > 1:
            self.log.warning("Multiple mappings found for '{}'".
                             format(layer.name))
            self.log.warning("Only first subset name template used!")
            subset_name_list[:] = subset_name_list[0]

        if len(family_list) > 1:
            self.log.warning("Multiple mappings found for '{}'".
                             format(layer.name))
            self.log.warning("Only first family used!")
            family_list[:] = family_list[0]
        if subset_name_list:
            resolved_subset_template = subset_name_list.pop()
        if family_list:
            family = family_list.pop()

        self.log.debug("resolved_family {}".format(family))
        self.log.debug("resolved_subset_template {}".format(
            resolved_subset_template))
        return family, resolved_subset_template

    def _clean_subset_name(self, stub, naming_conventions, subset, layer):
        """Cleans invalid characters from subset name and layer name."""
        if re.search(naming_conventions["invalid_chars"], subset):
            subset = re.sub(
                naming_conventions["invalid_chars"],
                naming_conventions["replace_char"],
                subset
            )
            layer_name = re.sub(
                naming_conventions["invalid_chars"],
                naming_conventions["replace_char"],
                layer.clean_name
            )
            layer.name = layer_name
            stub.rename_layer(layer.id, layer_name)

        return subset
