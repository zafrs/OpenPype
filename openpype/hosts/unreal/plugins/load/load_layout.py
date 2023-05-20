# -*- coding: utf-8 -*-
"""Loader for layouts."""
import json
import collections
from pathlib import Path

import unreal
from unreal import EditorAssetLibrary
from unreal import EditorLevelLibrary
from unreal import EditorLevelUtils
from unreal import AssetToolsHelpers
from unreal import FBXImportType
from unreal import MovieSceneLevelVisibilityTrack
from unreal import MovieSceneSubTrack

from openpype.client import get_asset_by_name, get_assets, get_representations
from openpype.pipeline import (
    discover_loader_plugins,
    loaders_from_representation,
    load_container,
    get_representation_path,
    AYON_CONTAINER_ID,
    legacy_io,
)
from openpype.pipeline.context_tools import get_current_project_asset
from openpype.settings import get_current_project_settings
from openpype.hosts.unreal.api import plugin
from openpype.hosts.unreal.api import pipeline as unreal_pipeline


class LayoutLoader(plugin.Loader):
    """Load Layout from a JSON file"""

    families = ["layout"]
    representations = ["json"]

    label = "Load Layout"
    icon = "code-fork"
    color = "orange"
    ASSET_ROOT = "/Game/Ayon"

    def _get_asset_containers(self, path):
        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        asset_content = EditorAssetLibrary.list_assets(
            path, recursive=True)

        asset_containers = []

        # Get all the asset containers
        for a in asset_content:
            obj = ar.get_asset_by_object_path(a)
            if obj.get_asset().get_class().get_name() == 'AyonAssetContainer':
                asset_containers.append(obj)

        return asset_containers

    @staticmethod
    def _get_fbx_loader(loaders, family):
        name = ""
        if family == 'rig':
            name = "SkeletalMeshFBXLoader"
        elif family == 'model':
            name = "StaticMeshFBXLoader"
        elif family == 'camera':
            name = "CameraLoader"

        if name == "":
            return None

        for loader in loaders:
            if loader.__name__ == name:
                return loader

        return None

    @staticmethod
    def _get_abc_loader(loaders, family):
        name = ""
        if family == 'rig':
            name = "SkeletalMeshAlembicLoader"
        elif family == 'model':
            name = "StaticMeshAlembicLoader"

        if name == "":
            return None

        for loader in loaders:
            if loader.__name__ == name:
                return loader

        return None

    @staticmethod
    def _set_sequence_hierarchy(
        seq_i, seq_j, max_frame_i, min_frame_j, max_frame_j, map_paths
    ):
        # Get existing sequencer tracks or create them if they don't exist
        tracks = seq_i.get_master_tracks()
        subscene_track = None
        visibility_track = None
        for t in tracks:
            if t.get_class() == unreal.MovieSceneSubTrack.static_class():
                subscene_track = t
            if (t.get_class() ==
                    unreal.MovieSceneLevelVisibilityTrack.static_class()):
                visibility_track = t
        if not subscene_track:
            subscene_track = seq_i.add_master_track(unreal.MovieSceneSubTrack)
        if not visibility_track:
            visibility_track = seq_i.add_master_track(
                unreal.MovieSceneLevelVisibilityTrack)

        # Create the sub-scene section
        subscenes = subscene_track.get_sections()
        subscene = None
        for s in subscenes:
            if s.get_editor_property('sub_sequence') == seq_j:
                subscene = s
                break
        if not subscene:
            subscene = subscene_track.add_section()
            subscene.set_row_index(len(subscene_track.get_sections()))
            subscene.set_editor_property('sub_sequence', seq_j)
            subscene.set_range(
                min_frame_j,
                max_frame_j + 1)

        # Create the visibility section
        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        maps = []
        for m in map_paths:
            # Unreal requires to load the level to get the map name
            EditorLevelLibrary.save_all_dirty_levels()
            EditorLevelLibrary.load_level(m)
            maps.append(str(ar.get_asset_by_object_path(m).asset_name))

        vis_section = visibility_track.add_section()
        index = len(visibility_track.get_sections())

        vis_section.set_range(
            min_frame_j,
            max_frame_j + 1)
        vis_section.set_visibility(unreal.LevelVisibility.VISIBLE)
        vis_section.set_row_index(index)
        vis_section.set_level_names(maps)

        if min_frame_j > 1:
            hid_section = visibility_track.add_section()
            hid_section.set_range(
                1,
                min_frame_j)
            hid_section.set_visibility(unreal.LevelVisibility.HIDDEN)
            hid_section.set_row_index(index)
            hid_section.set_level_names(maps)
        if max_frame_j < max_frame_i:
            hid_section = visibility_track.add_section()
            hid_section.set_range(
                max_frame_j + 1,
                max_frame_i + 1)
            hid_section.set_visibility(unreal.LevelVisibility.HIDDEN)
            hid_section.set_row_index(index)
            hid_section.set_level_names(maps)

    def _transform_from_basis(self, transform, basis):
        """Transform a transform from a basis to a new basis."""
        # Get the basis matrix
        basis_matrix = unreal.Matrix(
            basis[0],
            basis[1],
            basis[2],
            basis[3]
        )
        transform_matrix = unreal.Matrix(
            transform[0],
            transform[1],
            transform[2],
            transform[3]
        )

        new_transform = (
            basis_matrix.get_inverse() * transform_matrix * basis_matrix)

        return new_transform.transform()

    def _process_family(
        self, assets, class_name, transform, basis, sequence, inst_name=None
    ):
        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        actors = []
        bindings = []

        for asset in assets:
            obj = ar.get_asset_by_object_path(asset).get_asset()
            if obj.get_class().get_name() == class_name:
                t = self._transform_from_basis(transform, basis)
                actor = EditorLevelLibrary.spawn_actor_from_object(
                    obj, t.translation
                )
                actor.set_actor_rotation(t.rotation.rotator(), False)
                actor.set_actor_scale3d(t.scale3d)

                if class_name == 'SkeletalMesh':
                    skm_comp = actor.get_editor_property(
                        'skeletal_mesh_component')
                    skm_comp.set_bounds_scale(10.0)

                actors.append(actor)

                if sequence:
                    binding = None
                    for p in sequence.get_possessables():
                        if p.get_name() == actor.get_name():
                            binding = p
                            break

                    if not binding:
                        binding = sequence.add_possessable(actor)

                    bindings.append(binding)

        return actors, bindings

    def _import_animation(
        self, asset_dir, path, instance_name, skeleton, actors_dict,
        animation_file, bindings_dict, sequence
    ):
        anim_file = Path(animation_file)
        anim_file_name = anim_file.with_suffix('')

        anim_path = f"{asset_dir}/animations/{anim_file_name}"

        asset_doc = get_current_project_asset()
        # Import animation
        task = unreal.AssetImportTask()
        task.options = unreal.FbxImportUI()

        task.set_editor_property(
            'filename', str(path.with_suffix(f".{animation_file}")))
        task.set_editor_property('destination_path', anim_path)
        task.set_editor_property(
            'destination_name', f"{instance_name}_animation")
        task.set_editor_property('replace_existing', False)
        task.set_editor_property('automated', True)
        task.set_editor_property('save', False)

        # set import options here
        task.options.set_editor_property(
            'automated_import_should_detect_type', False)
        task.options.set_editor_property(
            'original_import_type', FBXImportType.FBXIT_SKELETAL_MESH)
        task.options.set_editor_property(
            'mesh_type_to_import', FBXImportType.FBXIT_ANIMATION)
        task.options.set_editor_property('import_mesh', False)
        task.options.set_editor_property('import_animations', True)
        task.options.set_editor_property('override_full_name', True)
        task.options.set_editor_property('skeleton', skeleton)

        task.options.anim_sequence_import_data.set_editor_property(
            'animation_length',
            unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME
        )
        task.options.anim_sequence_import_data.set_editor_property(
            'import_meshes_in_bone_hierarchy', False)
        task.options.anim_sequence_import_data.set_editor_property(
            'use_default_sample_rate', False)
        task.options.anim_sequence_import_data.set_editor_property(
            'custom_sample_rate', asset_doc.get("data", {}).get("fps"))
        task.options.anim_sequence_import_data.set_editor_property(
            'import_custom_attribute', True)
        task.options.anim_sequence_import_data.set_editor_property(
            'import_bone_tracks', True)
        task.options.anim_sequence_import_data.set_editor_property(
            'remove_redundant_keys', False)
        task.options.anim_sequence_import_data.set_editor_property(
            'convert_scene', True)

        AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

        asset_content = unreal.EditorAssetLibrary.list_assets(
            anim_path, recursive=False, include_folder=False
        )

        animation = None

        for a in asset_content:
            unreal.EditorAssetLibrary.save_asset(a)
            imported_asset_data = unreal.EditorAssetLibrary.find_asset_data(a)
            imported_asset = unreal.AssetRegistryHelpers.get_asset(
                imported_asset_data)
            if imported_asset.__class__ == unreal.AnimSequence:
                animation = imported_asset
                break

        if animation:
            actor = None
            if actors_dict.get(instance_name):
                for a in actors_dict.get(instance_name):
                    if a.get_class().get_name() == 'SkeletalMeshActor':
                        actor = a
                        break

            animation.set_editor_property('enable_root_motion', True)
            actor.skeletal_mesh_component.set_editor_property(
                'animation_mode', unreal.AnimationMode.ANIMATION_SINGLE_NODE)
            actor.skeletal_mesh_component.animation_data.set_editor_property(
                'anim_to_play', animation)

            if sequence:
                # Add animation to the sequencer
                bindings = bindings_dict.get(instance_name)

                ar = unreal.AssetRegistryHelpers.get_asset_registry()

                for binding in bindings:
                    tracks = binding.get_tracks()
                    track = None
                    track = tracks[0] if tracks else binding.add_track(
                        unreal.MovieSceneSkeletalAnimationTrack)

                    sections = track.get_sections()
                    section = None
                    if not sections:
                        section = track.add_section()
                    else:
                        section = sections[0]

                        sec_params = section.get_editor_property('params')
                        curr_anim = sec_params.get_editor_property('animation')

                        if curr_anim:
                            # Checks if the animation path has a container.
                            # If it does, it means that the animation is
                            # already in the sequencer.
                            anim_path = str(Path(
                                curr_anim.get_path_name()).parent
                            ).replace('\\', '/')

                            _filter = unreal.ARFilter(
                                class_names=["AyonAssetContainer"],
                                package_paths=[anim_path],
                                recursive_paths=False)
                            containers = ar.get_assets(_filter)

                            if len(containers) > 0:
                                return

                    section.set_range(
                        sequence.get_playback_start(),
                        sequence.get_playback_end())
                    sec_params = section.get_editor_property('params')
                    sec_params.set_editor_property('animation', animation)

    @staticmethod
    def _generate_sequence(h, h_dir):
        tools = unreal.AssetToolsHelpers().get_asset_tools()

        sequence = tools.create_asset(
            asset_name=h,
            package_path=h_dir,
            asset_class=unreal.LevelSequence,
            factory=unreal.LevelSequenceFactoryNew()
        )

        project_name = legacy_io.active_project()
        asset_data = get_asset_by_name(
            project_name,
            h_dir.split('/')[-1],
            fields=["_id", "data.fps"]
        )

        start_frames = []
        end_frames = []

        elements = list(get_assets(
            project_name,
            parent_ids=[asset_data["_id"]],
            fields=["_id", "data.clipIn", "data.clipOut"]
        ))
        for e in elements:
            start_frames.append(e.get('data').get('clipIn'))
            end_frames.append(e.get('data').get('clipOut'))

            elements.extend(get_assets(
                project_name,
                parent_ids=[e["_id"]],
                fields=["_id", "data.clipIn", "data.clipOut"]
            ))

        min_frame = min(start_frames)
        max_frame = max(end_frames)

        sequence.set_display_rate(
            unreal.FrameRate(asset_data.get('data').get("fps"), 1.0))
        sequence.set_playback_start(min_frame)
        sequence.set_playback_end(max_frame)

        tracks = sequence.get_master_tracks()
        track = None
        for t in tracks:
            if (t.get_class() ==
                    unreal.MovieSceneCameraCutTrack.static_class()):
                track = t
                break
        if not track:
            track = sequence.add_master_track(
                unreal.MovieSceneCameraCutTrack)

        return sequence, (min_frame, max_frame)

    def _get_repre_docs_by_version_id(self, data):
        version_ids = {
            element.get("version")
            for element in data
            if element.get("representation")
        }
        version_ids.discard(None)

        output = collections.defaultdict(list)
        if not version_ids:
            return output

        project_name = legacy_io.active_project()
        repre_docs = get_representations(
            project_name,
            representation_names=["fbx", "abc"],
            version_ids=version_ids,
            fields=["_id", "parent", "name"]
        )
        for repre_doc in repre_docs:
            version_id = str(repre_doc["parent"])
            output[version_id].append(repre_doc)
        return output

    def _process(self, lib_path, asset_dir, sequence, repr_loaded=None):
        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        with open(lib_path, "r") as fp:
            data = json.load(fp)

        all_loaders = discover_loader_plugins()

        if not repr_loaded:
            repr_loaded = []

        path = Path(lib_path)

        skeleton_dict = {}
        actors_dict = {}
        bindings_dict = {}

        loaded_assets = []

        repre_docs_by_version_id = self._get_repre_docs_by_version_id(data)
        for element in data:
            representation = None
            repr_format = None
            if element.get('representation'):
                repre_docs = repre_docs_by_version_id[element.get("version")]
                if not repre_docs:
                    self.log.error(
                        f"No valid representation found for version "
                        f"{element.get('version')}")
                    continue
                repre_doc = repre_docs[0]
                representation = str(repre_doc["_id"])
                repr_format = repre_doc["name"]

            # This is to keep compatibility with old versions of the
            # json format.
            elif element.get('reference_fbx'):
                representation = element.get('reference_fbx')
                repr_format = 'fbx'
            elif element.get('reference_abc'):
                representation = element.get('reference_abc')
                repr_format = 'abc'

            # If reference is None, this element is skipped, as it cannot be
            # imported in Unreal
            if not representation:
                continue

            instance_name = element.get('instance_name')

            skeleton = None

            if representation not in repr_loaded:
                repr_loaded.append(representation)

                family = element.get('family')
                loaders = loaders_from_representation(
                    all_loaders, representation)

                loader = None

                if repr_format == 'fbx':
                    loader = self._get_fbx_loader(loaders, family)
                elif repr_format == 'abc':
                    loader = self._get_abc_loader(loaders, family)

                if not loader:
                    self.log.error(
                        f"No valid loader found for {representation}")
                    continue

                options = {
                    # "asset_dir": asset_dir
                }

                assets = load_container(
                    loader,
                    representation,
                    namespace=instance_name,
                    options=options
                )

                container = None

                for asset in assets:
                    obj = ar.get_asset_by_object_path(asset).get_asset()
                    if obj.get_class().get_name() == 'AyonAssetContainer':
                        container = obj
                    if obj.get_class().get_name() == 'Skeleton':
                        skeleton = obj

                loaded_assets.append(container.get_path_name())

                instances = [
                    item for item in data
                    if ((item.get('version') and
                        item.get('version') == element.get('version')) or
                        item.get('reference_fbx') == representation or
                        item.get('reference_abc') == representation)]

                for instance in instances:
                    # transform = instance.get('transform')
                    transform = instance.get('transform_matrix')
                    basis = instance.get('basis')
                    inst = instance.get('instance_name')

                    actors = []

                    if family == 'model':
                        actors, _ = self._process_family(
                            assets, 'StaticMesh', transform, basis,
                            sequence, inst
                        )
                    elif family == 'rig':
                        actors, bindings = self._process_family(
                            assets, 'SkeletalMesh', transform, basis,
                            sequence, inst
                        )
                        actors_dict[inst] = actors
                        bindings_dict[inst] = bindings

                if skeleton:
                    skeleton_dict[representation] = skeleton
            else:
                skeleton = skeleton_dict.get(representation)

            animation_file = element.get('animation')

            if animation_file and skeleton:
                self._import_animation(
                    asset_dir, path, instance_name, skeleton, actors_dict,
                    animation_file, bindings_dict, sequence)

        return loaded_assets

    @staticmethod
    def _remove_family(assets, components, class_name, prop_name):
        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        objects = []
        for a in assets:
            obj = ar.get_asset_by_object_path(a)
            if obj.get_asset().get_class().get_name() == class_name:
                objects.append(obj)
        for obj in objects:
            for comp in components:
                if comp.get_editor_property(prop_name) == obj.get_asset():
                    comp.get_owner().destroy_actor()

    def _remove_actors(self, path):
        asset_containers = self._get_asset_containers(path)

        # Get all the static and skeletal meshes components in the level
        components = EditorLevelLibrary.get_all_level_actors_components()
        static_meshes_comp = [
            c for c in components
            if c.get_class().get_name() == 'StaticMeshComponent']
        skel_meshes_comp = [
            c for c in components
            if c.get_class().get_name() == 'SkeletalMeshComponent']

        # For all the asset containers, get the static and skeletal meshes.
        # Then, check the components in the level and destroy the matching
        # actors.
        for asset_container in asset_containers:
            package_path = asset_container.get_editor_property('package_path')
            family = EditorAssetLibrary.get_metadata_tag(
                asset_container.get_asset(), 'family')
            assets = EditorAssetLibrary.list_assets(
                str(package_path), recursive=False)
            if family == 'model':
                self._remove_family(
                    assets, static_meshes_comp, 'StaticMesh', 'static_mesh')
            elif family == 'rig':
                self._remove_family(
                    assets, skel_meshes_comp, 'SkeletalMesh', 'skeletal_mesh')

    def load(self, context, name, namespace, options):
        """Load and containerise representation into Content Browser.

        This is two step process. First, import FBX to temporary path and
        then call `containerise()` on it - this moves all content to new
        directory and then it will create AssetContainer there and imprint it
        with metadata. This will mark this path as container.

        Args:
            context (dict): application context
            name (str): subset name
            namespace (str): in Unreal this is basically path to container.
                             This is not passed here, so namespace is set
                             by `containerise()` because only then we know
                             real path.
            options (dict): Those would be data to be imprinted. This is not
                used now, data are imprinted by `containerise()`.

        Returns:
            list(str): list of container content
        """
        data = get_current_project_settings()
        create_sequences = data["unreal"]["level_sequences_for_layouts"]

        # Create directory for asset and Ayon container
        hierarchy = context.get('asset').get('data').get('parents')
        root = self.ASSET_ROOT
        hierarchy_dir = root
        hierarchy_dir_list = []
        for h in hierarchy:
            hierarchy_dir = f"{hierarchy_dir}/{h}"
            hierarchy_dir_list.append(hierarchy_dir)
        asset = context.get('asset').get('name')
        suffix = "_CON"
        asset_name = f"{asset}_{name}" if asset else name

        tools = unreal.AssetToolsHelpers().get_asset_tools()
        asset_dir, container_name = tools.create_unique_asset_name(
            "{}/{}/{}".format(hierarchy_dir, asset, name), suffix="")

        container_name += suffix

        EditorAssetLibrary.make_directory(asset_dir)

        master_level = None
        shot = None
        sequences = []

        level = f"{asset_dir}/{asset}_map.{asset}_map"
        EditorLevelLibrary.new_level(f"{asset_dir}/{asset}_map")

        if create_sequences:
            # Create map for the shot, and create hierarchy of map. If the
            # maps already exist, we will use them.
            if hierarchy:
                h_dir = hierarchy_dir_list[0]
                h_asset = hierarchy[0]
                master_level = f"{h_dir}/{h_asset}_map.{h_asset}_map"
                if not EditorAssetLibrary.does_asset_exist(master_level):
                    EditorLevelLibrary.new_level(f"{h_dir}/{h_asset}_map")

            if master_level:
                EditorLevelLibrary.load_level(master_level)
                EditorLevelUtils.add_level_to_world(
                    EditorLevelLibrary.get_editor_world(),
                    level,
                    unreal.LevelStreamingDynamic
                )
                EditorLevelLibrary.save_all_dirty_levels()
                EditorLevelLibrary.load_level(level)

            # Get all the sequences in the hierarchy. It will create them, if
            # they don't exist.
            frame_ranges = []
            for (h_dir, h) in zip(hierarchy_dir_list, hierarchy):
                root_content = EditorAssetLibrary.list_assets(
                    h_dir, recursive=False, include_folder=False)

                existing_sequences = [
                    EditorAssetLibrary.find_asset_data(asset)
                    for asset in root_content
                    if EditorAssetLibrary.find_asset_data(
                        asset).get_class().get_name() == 'LevelSequence'
                ]

                if not existing_sequences:
                    sequence, frame_range = self._generate_sequence(h, h_dir)

                    sequences.append(sequence)
                    frame_ranges.append(frame_range)
                else:
                    for e in existing_sequences:
                        sequences.append(e.get_asset())
                        frame_ranges.append((
                            e.get_asset().get_playback_start(),
                            e.get_asset().get_playback_end()))

            shot = tools.create_asset(
                asset_name=asset,
                package_path=asset_dir,
                asset_class=unreal.LevelSequence,
                factory=unreal.LevelSequenceFactoryNew()
            )

            # sequences and frame_ranges have the same length
            for i in range(0, len(sequences) - 1):
                self._set_sequence_hierarchy(
                    sequences[i], sequences[i + 1],
                    frame_ranges[i][1],
                    frame_ranges[i + 1][0], frame_ranges[i + 1][1],
                    [level])

            project_name = legacy_io.active_project()
            data = get_asset_by_name(project_name, asset)["data"]
            shot.set_display_rate(
                unreal.FrameRate(data.get("fps"), 1.0))
            shot.set_playback_start(0)
            shot.set_playback_end(data.get('clipOut') - data.get('clipIn') + 1)
            if sequences:
                self._set_sequence_hierarchy(
                    sequences[-1], shot,
                    frame_ranges[-1][1],
                    data.get('clipIn'), data.get('clipOut'),
                    [level])

            EditorLevelLibrary.load_level(level)

        loaded_assets = self._process(self.fname, asset_dir, shot)

        for s in sequences:
            EditorAssetLibrary.save_asset(s.get_full_name())

        EditorLevelLibrary.save_current_level()

        # Create Asset Container
        unreal_pipeline.create_container(
            container=container_name, path=asset_dir)

        data = {
            "schema": "ayon:container-2.0",
            "id": AYON_CONTAINER_ID,
            "asset": asset,
            "namespace": asset_dir,
            "container_name": container_name,
            "asset_name": asset_name,
            "loader": str(self.__class__.__name__),
            "representation": context["representation"]["_id"],
            "parent": context["representation"]["parent"],
            "family": context["representation"]["context"]["family"],
            "loaded_assets": loaded_assets
        }
        unreal_pipeline.imprint(
            "{}/{}".format(asset_dir, container_name), data)

        asset_content = EditorAssetLibrary.list_assets(
            asset_dir, recursive=True, include_folder=False)

        for a in asset_content:
            EditorAssetLibrary.save_asset(a)

        if master_level:
            EditorLevelLibrary.load_level(master_level)

        return asset_content

    def update(self, container, representation):
        data = get_current_project_settings()
        create_sequences = data["unreal"]["level_sequences_for_layouts"]

        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        root = "/Game/Ayon"

        asset_dir = container.get('namespace')
        context = representation.get("context")

        sequence = None
        master_level = None

        if create_sequences:
            hierarchy = context.get('hierarchy').split("/")
            h_dir = f"{root}/{hierarchy[0]}"
            h_asset = hierarchy[0]
            master_level = f"{h_dir}/{h_asset}_map.{h_asset}_map"

            filter = unreal.ARFilter(
                class_names=["LevelSequence"],
                package_paths=[asset_dir],
                recursive_paths=False)
            sequences = ar.get_assets(filter)
            sequence = sequences[0].get_asset()

        prev_level = None

        if not master_level:
            curr_level = unreal.LevelEditorSubsystem().get_current_level()
            curr_level_path = curr_level.get_outer().get_path_name()
            # If the level path does not start with "/Game/", the current
            # level is a temporary, unsaved level.
            if curr_level_path.startswith("/Game/"):
                prev_level = curr_level_path

        # Get layout level
        filter = unreal.ARFilter(
            class_names=["World"],
            package_paths=[asset_dir],
            recursive_paths=False)
        levels = ar.get_assets(filter)

        layout_level = levels[0].get_full_name()

        EditorLevelLibrary.save_all_dirty_levels()
        EditorLevelLibrary.load_level(layout_level)

        # Delete all the actors in the level
        actors = unreal.EditorLevelLibrary.get_all_level_actors()
        for actor in actors:
            unreal.EditorLevelLibrary.destroy_actor(actor)

        if create_sequences:
            EditorLevelLibrary.save_current_level()

        EditorAssetLibrary.delete_directory(f"{asset_dir}/animations/")

        source_path = get_representation_path(representation)

        loaded_assets = self._process(source_path, asset_dir, sequence)

        data = {
            "representation": str(representation["_id"]),
            "parent": str(representation["parent"]),
            "loaded_assets": loaded_assets
        }
        unreal_pipeline.imprint(
            "{}/{}".format(asset_dir, container.get('container_name')), data)

        EditorLevelLibrary.save_current_level()

        asset_content = EditorAssetLibrary.list_assets(
            asset_dir, recursive=True, include_folder=False)

        for a in asset_content:
            EditorAssetLibrary.save_asset(a)

        if master_level:
            EditorLevelLibrary.load_level(master_level)
        elif prev_level:
            EditorLevelLibrary.load_level(prev_level)

    def remove(self, container):
        """
        Delete the layout. First, check if the assets loaded with the layout
        are used by other layouts. If not, delete the assets.
        """
        data = get_current_project_settings()
        create_sequences = data["unreal"]["level_sequences_for_layouts"]

        root = "/Game/Ayon"
        path = Path(container.get("namespace"))

        containers = unreal_pipeline.ls()
        layout_containers = [
            c for c in containers
            if (c.get('asset_name') != container.get('asset_name') and
                c.get('family') == "layout")]

        # Check if the assets have been loaded by other layouts, and deletes
        # them if they haven't.
        for asset in eval(container.get('loaded_assets')):
            layouts = [
                lc for lc in layout_containers
                if asset in lc.get('loaded_assets')]

            if not layouts:
                EditorAssetLibrary.delete_directory(str(Path(asset).parent))

                # Delete the parent folder if there aren't any more
                # layouts in it.
                asset_content = EditorAssetLibrary.list_assets(
                    str(Path(asset).parent.parent), recursive=False,
                    include_folder=True
                )

                if len(asset_content) == 0:
                    EditorAssetLibrary.delete_directory(
                        str(Path(asset).parent.parent))

        master_sequence = None
        master_level = None
        sequences = []

        if create_sequences:
            # Remove the Level Sequence from the parent.
            # We need to traverse the hierarchy from the master sequence to
            # find the level sequence.
            namespace = container.get('namespace').replace(f"{root}/", "")
            ms_asset = namespace.split('/')[0]
            ar = unreal.AssetRegistryHelpers.get_asset_registry()
            _filter = unreal.ARFilter(
                class_names=["LevelSequence"],
                package_paths=[f"{root}/{ms_asset}"],
                recursive_paths=False)
            sequences = ar.get_assets(_filter)
            master_sequence = sequences[0].get_asset()
            _filter = unreal.ARFilter(
                class_names=["World"],
                package_paths=[f"{root}/{ms_asset}"],
                recursive_paths=False)
            levels = ar.get_assets(_filter)
            master_level = levels[0].get_full_name()

            sequences = [master_sequence]

            parent = None
            for s in sequences:
                tracks = s.get_master_tracks()
                subscene_track = None
                visibility_track = None
                for t in tracks:
                    if t.get_class() == MovieSceneSubTrack.static_class():
                        subscene_track = t
                    if (t.get_class() ==
                            MovieSceneLevelVisibilityTrack.static_class()):
                        visibility_track = t
                if subscene_track:
                    sections = subscene_track.get_sections()
                    for ss in sections:
                        if (ss.get_sequence().get_name() ==
                                container.get('asset')):
                            parent = s
                            subscene_track.remove_section(ss)
                            break
                        sequences.append(ss.get_sequence())
                    # Update subscenes indexes.
                    i = 0
                    for ss in sections:
                        ss.set_row_index(i)
                        i += 1

                if visibility_track:
                    sections = visibility_track.get_sections()
                    for ss in sections:
                        if (unreal.Name(f"{container.get('asset')}_map")
                                in ss.get_level_names()):
                            visibility_track.remove_section(ss)
                    # Update visibility sections indexes.
                    i = -1
                    prev_name = []
                    for ss in sections:
                        if prev_name != ss.get_level_names():
                            i += 1
                        ss.set_row_index(i)
                        prev_name = ss.get_level_names()
                if parent:
                    break

            assert parent, "Could not find the parent sequence"

        # Create a temporary level to delete the layout level.
        EditorLevelLibrary.save_all_dirty_levels()
        EditorAssetLibrary.make_directory(f"{root}/tmp")
        tmp_level = f"{root}/tmp/temp_map"
        if not EditorAssetLibrary.does_asset_exist(f"{tmp_level}.temp_map"):
            EditorLevelLibrary.new_level(tmp_level)
        else:
            EditorLevelLibrary.load_level(tmp_level)

        # Delete the layout directory.
        EditorAssetLibrary.delete_directory(str(path))

        if create_sequences:
            EditorLevelLibrary.load_level(master_level)
            EditorAssetLibrary.delete_directory(f"{root}/tmp")

        # Delete the parent folder if there aren't any more layouts in it.
        asset_content = EditorAssetLibrary.list_assets(
            str(path.parent), recursive=False, include_folder=True
        )

        if len(asset_content) == 0:
            EditorAssetLibrary.delete_directory(str(path.parent))
