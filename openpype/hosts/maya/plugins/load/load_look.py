# -*- coding: utf-8 -*-
"""Look loader."""
import json
from collections import defaultdict

from Qt import QtWidgets

from avalon import api, io
import openpype.hosts.maya.api.plugin
from openpype.hosts.maya.api import lib
from openpype.widgets.message_window import ScrollMessageBox

from openpype.hosts.maya.api.plugin import get_reference_node


class LookLoader(openpype.hosts.maya.api.plugin.ReferenceLoader):
    """Specific loader for lookdev"""

    families = ["look"]
    representations = ["ma"]

    label = "Reference look"
    order = -10
    icon = "code-fork"
    color = "orange"

    def process_reference(self, context, name, namespace, options):
        """
        Load and try to assign Lookdev to nodes based on relationship data.

        Args:
            name:
            namespace:
            context:
            options:

        Returns:

        """
        import maya.cmds as cmds

        with lib.maintained_selection():
            nodes = cmds.file(self.fname,
                              namespace=namespace,
                              reference=True,
                              returnNewNodes=True)

        self[:] = nodes

    def switch(self, container, representation):
        self.update(container, representation)

    def update(self, container, representation):
        """
            Called by Scene Inventory when look should be updated to current
            version.
            If any reference edits cannot be applied, eg. shader renamed and
            material not present, reference is unloaded and cleaned.
            All failed edits are highlighted to the user via message box.

        Args:
            container: object that has look to be updated
            representation: (dict): relationship data to get proper
                                       representation from DB and persisted
                                       data in .json
        Returns:
            None
        """
        import os
        from maya import cmds
        node = container["objectName"]
        path = api.get_representation_path(representation)

        # Get reference node from container members
        members = cmds.sets(node, query=True, nodesOnly=True)
        reference_node = get_reference_node(members, log=self.log)

        shader_nodes = cmds.ls(members, type='shadingEngine')
        orig_nodes = set(self._get_nodes_with_shader(shader_nodes))

        file_type = {
            "ma": "mayaAscii",
            "mb": "mayaBinary",
            "abc": "Alembic"
        }.get(representation["name"])

        assert file_type, "Unsupported representation: %s" % representation

        assert os.path.exists(path), "%s does not exist." % path

        self._load_reference(file_type, node, path, reference_node)

        # Remove any placeHolderList attribute entries from the set that
        # are remaining from nodes being removed from the referenced file.
        members = cmds.sets(node, query=True)
        invalid = [x for x in members if ".placeHolderList" in x]
        if invalid:
            cmds.sets(invalid, remove=node)

        # get new applied shaders and nodes from new version
        shader_nodes = cmds.ls(members, type='shadingEngine')
        nodes = set(self._get_nodes_with_shader(shader_nodes))

        json_representation = io.find_one({
            "type": "representation",
            "parent": representation['parent'],
            "name": "json"
        })

        # Load relationships
        shader_relation = api.get_representation_path(json_representation)
        with open(shader_relation, "r") as f:
            json_data = json.load(f)

        for rel, data in json_data["relationships"].items():
            # process only non-shading nodes
            current_node = "{}:{}".format(container["namespace"], rel)
            if current_node in shader_nodes:
                continue
            print("processing {}".format(rel))
            current_members = set(cmds.ls(
                cmds.sets(current_node, query=True) or [], long=True))
            new_members = {"{}".format(
                m["name"]) for m in data["members"] or []}
            dif = new_members.difference(current_members)

            # add to set
            cmds.sets(
                dif, forceElement="{}:{}".format(container["namespace"], rel))

        # update of reference could result in failed edits - material is not
        # present because of renaming etc.
        failed_edits = cmds.referenceQuery(reference_node,
                                           editStrings=True,
                                           failedEdits=True,
                                           successfulEdits=False)

        # highlight failed edits to user
        if failed_edits:
            # clean references - removes failed reference edits
            cmds.file(cr=reference_node)  # cleanReference

            # reapply shading groups from json representation on orig nodes
            lib.apply_shaders(json_data, shader_nodes, orig_nodes)

            msg = ["During reference update some edits failed.",
                   "All successful edits were kept intact.\n",
                   "Failed and removed edits:"]
            msg.extend(failed_edits)

            msg = ScrollMessageBox(QtWidgets.QMessageBox.Warning,
                                   "Some reference edit failed",
                                   msg)
            msg.exec_()

        attributes = json_data.get("attributes", [])

        # region compute lookup
        nodes_by_id = defaultdict(list)
        for n in nodes:
            nodes_by_id[lib.get_id(n)].append(n)
        lib.apply_attributes(attributes, nodes_by_id)

        # Update metadata
        cmds.setAttr("{}.representation".format(node),
                     str(representation["_id"]),
                     type="string")

    def _get_nodes_with_shader(self, shader_nodes):
        """
            Returns list of nodes belonging to specific shaders
        Args:
            shader_nodes: <list> of Shader groups
        Returns
            <list> node names
        """
        import maya.cmds as cmds
        # Get container members

        nodes_list = []
        for shader in shader_nodes:
            connections = cmds.listConnections(cmds.listHistory(shader, f=1),
                                               type='mesh')
            if connections:
                for connection in connections:
                    nodes_list.extend(cmds.listRelatives(connection,
                                                         shapes=True))
        return nodes_list

    def _load_reference(self, file_type, node, path, reference_node):
        """
            Load reference from 'path' on 'reference_node'. Used when change
            of look (version/update) is triggered.
        Args:
            file_type: extension of referenced file
            node:
            path: (string) location of referenced file
            reference_node: (string) - name of node that should be applied
                                          on
        Returns:
            None
        """
        import maya.cmds as cmds
        try:
            content = cmds.file(path,
                                loadReference=reference_node,
                                type=file_type,
                                returnNewNodes=True)
        except RuntimeError as exc:
            # When changing a reference to a file that has load errors the
            # command will raise an error even if the file is still loaded
            # correctly (e.g. when raising errors on Arnold attributes)
            # When the file is loaded and has content, we consider it's fine.
            if not cmds.referenceQuery(reference_node, isLoaded=True):
                raise

            content = cmds.referenceQuery(reference_node,
                                          nodes=True,
                                          dagPath=True)
            if not content:
                raise

            self.log.warning("Ignoring file read error:\n%s", exc)
        # Fix PLN-40 for older containers created with Avalon that had the
        # `.verticesOnlySet` set to True.
        if cmds.getAttr("{}.verticesOnlySet".format(node)):
            self.log.info("Setting %s.verticesOnlySet to False", node)
            cmds.setAttr("{}.verticesOnlySet".format(node), False)
        # Add new nodes of the reference to the container
        cmds.sets(content, forceElement=node)
