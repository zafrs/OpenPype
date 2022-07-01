import pyblish.api
import nuke
import os
import openpype
import clique


class NukeRenderLocal(openpype.api.Extractor):
    # TODO: rewrite docstring to nuke
    """Render the current Nuke composition locally.

    Extract the result of savers by starting a comp render
    This will run the local render of Fusion.

    """

    order = pyblish.api.ExtractorOrder
    label = "Render Local"
    hosts = ["nuke"]
    families = ["render.local", "prerender.local", "still.local"]

    def process(self, instance):
        families = instance.data["families"]

        node = None
        for x in instance:
            if x.Class() == "Write":
                node = x

        self.log.debug("instance collected: {}".format(instance.data))

        first_frame = instance.data.get("frameStartHandle", None)

        # exception for slate workflow
        if "slate" in families:
            first_frame -= 1

        last_frame = instance.data.get("frameEndHandle", None)
        node_subset_name = instance.data.get("name", None)

        self.log.info("Starting render")
        self.log.info("Start frame: {}".format(first_frame))
        self.log.info("End frame: {}".format(last_frame))

        node_file = node["file"]
        # Collecte expected filepaths for each frame
        # - for cases that output is still image is first created set of
        #   paths which is then sorted and converted to list
        expected_paths = list(sorted({
            node_file.evaluate(frame)
            for frame in range(first_frame, last_frame + 1)
        }))
        # Extract only filenames for representation
        filenames = [
            os.path.basename(filepath)
            for filepath in expected_paths
        ]

        # Ensure output directory exists.
        out_dir = os.path.dirname(expected_paths[0])
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        # Render frames
        nuke.execute(
            node_subset_name,
            int(first_frame),
            int(last_frame)
        )

        # exception for slate workflow
        if "slate" in families:
            first_frame += 1

        ext = node["file_type"].value()

        if "representations" not in instance.data:
            instance.data["representations"] = []

        if len(filenames) == 1:
            repre = {
                'name': ext,
                'ext': ext,
                'files': filenames[0],
                "stagingDir": out_dir
            }
        else:
            repre = {
                'name': ext,
                'ext': ext,
                'frameStart': "%0{}d".format(
                    len(str(last_frame))) % first_frame,
                'files': filenames,
                "stagingDir": out_dir
            }
        instance.data["representations"].append(repre)

        self.log.info("Extracted instance '{0}' to: {1}".format(
            instance.name,
            out_dir
        ))

        # redefinition of families
        if "render.local" in families:
            instance.data['family'] = 'render'
            families.remove('render.local')
            families.insert(0, "render2d")
        elif "prerender.local" in families:
            instance.data['family'] = 'prerender'
            families.remove('prerender.local')
            families.insert(0, "prerender")
        elif "still.local" in families:
            instance.data['family'] = 'image'
            families.remove('still.local')
        instance.data["families"] = families

        collections, remainder = clique.assemble(filenames)
        self.log.info('collections: {}'.format(str(collections)))

        if collections:
            collection = collections[0]
            instance.data['collection'] = collection

        self.log.info('Finished render')

        self.log.debug("instance extracted: {}".format(instance.data))
