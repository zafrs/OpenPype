import re
from maya import cmds

from openpype.client import get_representations
from openpype.pipeline import legacy_io
from openpype.pipeline.workfile.abstract_template_loader import (
    AbstractPlaceholder,
    AbstractTemplateLoader
)
from openpype.pipeline.workfile.build_template_exceptions import (
    TemplateAlreadyImported
)

PLACEHOLDER_SET = 'PLACEHOLDERS_SET'


class MayaTemplateLoader(AbstractTemplateLoader):
    """Concrete implementation of AbstractTemplateLoader for maya
    """

    def import_template(self, path):
        """Import template into current scene.
        Block if a template is already loaded.
        Args:
            path (str): A path to current template (usually given by
            get_template_path implementation)
        Returns:
            bool: Wether the template was succesfully imported or not
        """
        if cmds.objExists(PLACEHOLDER_SET):
            raise TemplateAlreadyImported(
                "Build template already loaded\n"
                "Clean scene if needed (File > New Scene)")

        cmds.sets(name=PLACEHOLDER_SET, empty=True)
        self.new_nodes = cmds.file(path, i=True, returnNewNodes=True)
        cmds.setAttr(PLACEHOLDER_SET + '.hiddenInOutliner', True)

        for set in cmds.listSets(allSets=True):
            if (cmds.objExists(set) and
               cmds.attributeQuery('id', node=set, exists=True) and
               cmds.getAttr(set + '.id') == 'pyblish.avalon.instance'):
                if cmds.attributeQuery('asset', node=set, exists=True):
                    cmds.setAttr(
                        set + '.asset',
                        legacy_io.Session['AVALON_ASSET'], type='string'
                    )

        return True

    def template_already_imported(self, err_msg):
        clearButton = "Clear scene and build"
        updateButton = "Update template"
        abortButton = "Abort"

        title = "Scene already builded"
        message = (
            "It's seems a template was already build for this scene.\n"
            "Error message reveived :\n\n\"{}\"".format(err_msg))
        buttons = [clearButton, updateButton, abortButton]
        defaultButton = clearButton
        cancelButton = abortButton
        dismissString = abortButton
        answer = cmds.confirmDialog(
            t=title,
            m=message,
            b=buttons,
            db=defaultButton,
            cb=cancelButton,
            ds=dismissString)

        if answer == clearButton:
            cmds.file(newFile=True, force=True)
            self.import_template(self.template_path)
            self.populate_template()
        elif answer == updateButton:
            self.update_missing_containers()
        elif answer == abortButton:
            return

    @staticmethod
    def get_template_nodes():
        attributes = cmds.ls('*.builder_type', long=True)
        return [attribute.rpartition('.')[0] for attribute in attributes]

    def get_loaded_containers_by_id(self):
        try:
            containers = cmds.sets("AVALON_CONTAINERS", q=True)
        except ValueError:
            return None

        return [
            cmds.getAttr(container + '.representation')
            for container in containers]


class MayaPlaceholder(AbstractPlaceholder):
    """Concrete implementation of AbstractPlaceholder for maya
    """

    optional_keys = {'asset', 'subset', 'hierarchy'}

    def get_data(self, node):
        user_data = dict()
        for attr in self.required_keys.union(self.optional_keys):
            attribute_name = '{}.{}'.format(node, attr)
            if not cmds.attributeQuery(attr, node=node, exists=True):
                print("{} not found".format(attribute_name))
                continue
            user_data[attr] = cmds.getAttr(
                attribute_name,
                asString=True)
        user_data['parent'] = (
            cmds.getAttr(node + '.parent', asString=True)
            or node.rpartition('|')[0]
            or ""
        )
        user_data['node'] = node
        if user_data['parent']:
            siblings = cmds.listRelatives(user_data['parent'], children=True)
        else:
            siblings = cmds.ls(assemblies=True)
        node_shortname = user_data['node'].rpartition('|')[2]
        current_index = cmds.getAttr(node + '.index', asString=True)
        user_data['index'] = (
            current_index if current_index >= 0
            else siblings.index(node_shortname))

        self.data = user_data

    def parent_in_hierarchy(self, containers):
        """Parent loaded container to placeholder's parent
        ie : Set loaded content as placeholder's sibling
        Args:
            containers (String): Placeholder loaded containers
        """
        if not containers:
            return

        roots = cmds.sets(containers, q=True)
        nodes_to_parent = []
        for root in roots:
            if root.endswith("_RN"):
                refRoot = cmds.referenceQuery(root, n=True)[0]
                refRoot = cmds.listRelatives(refRoot, parent=True) or [refRoot]
                nodes_to_parent.extend(refRoot)
            elif root in cmds.listSets(allSets=True):
                if not cmds.sets(root, q=True):
                    return
                else:
                    continue
            else:
                nodes_to_parent.append(root)

        if self.data['parent']:
            cmds.parent(nodes_to_parent, self.data['parent'])
        # Move loaded nodes to correct index in outliner hierarchy
        placeholder_node = self.data['node']
        placeholder_form = cmds.xform(
            placeholder_node,
            q=True,
            matrix=True,
            worldSpace=True
        )
        for node in set(nodes_to_parent):
            cmds.reorder(node, front=True)
            cmds.reorder(node, relative=self.data['index'])
            cmds.xform(node, matrix=placeholder_form, ws=True)

        holding_sets = cmds.listSets(object=placeholder_node)
        if not holding_sets:
            return
        for holding_set in holding_sets:
            cmds.sets(roots, forceElement=holding_set)

    def clean(self):
        """Hide placeholder, parent them to root
        add them to placeholder set and register placeholder's parent
        to keep placeholder info available for future use
        """
        node = self.data['node']
        if self.data['parent']:
            cmds.setAttr(node + '.parent', self.data['parent'], type='string')
        if cmds.getAttr(node + '.index') < 0:
            cmds.setAttr(node + '.index', self.data['index'])

        holding_sets = cmds.listSets(object=node)
        if holding_sets:
            for set in holding_sets:
                cmds.sets(node, remove=set)

        if cmds.listRelatives(node, p=True):
            node = cmds.parent(node, world=True)[0]
        cmds.sets(node, addElement=PLACEHOLDER_SET)
        cmds.hide(node)
        cmds.setAttr(node + '.hiddenInOutliner', True)

    def get_representations(self, current_asset_doc, linked_asset_docs):
        project_name = legacy_io.active_project()

        builder_type = self.data["builder_type"]
        if builder_type == "context_asset":
            context_filters = {
                "asset": [current_asset_doc["name"]],
                "subset": [re.compile(self.data["subset"])],
                "hierarchy": [re.compile(self.data["hierarchy"])],
                "representations": [self.data["representation"]],
                "family": [self.data["family"]]
            }

        elif builder_type != "linked_asset":
            context_filters = {
                "asset": [re.compile(self.data["asset"])],
                "subset": [re.compile(self.data["subset"])],
                "hierarchy": [re.compile(self.data["hierarchy"])],
                "representation": [self.data["representation"]],
                "family": [self.data["family"]]
            }

        else:
            asset_regex = re.compile(self.data["asset"])
            linked_asset_names = []
            for asset_doc in linked_asset_docs:
                asset_name = asset_doc["name"]
                if asset_regex.match(asset_name):
                    linked_asset_names.append(asset_name)

            context_filters = {
                "asset": linked_asset_names,
                "subset": [re.compile(self.data["subset"])],
                "hierarchy": [re.compile(self.data["hierarchy"])],
                "representation": [self.data["representation"]],
                "family": [self.data["family"]],
            }

        return list(get_representations(
            project_name,
            context_filters=context_filters
        ))

    def err_message(self):
        return (
            "Error while trying to load a representation.\n"
            "Either the subset wasn't published or the template is malformed."
            "\n\n"
            "Builder was looking for :\n{attributes}".format(
                attributes="\n".join([
                    "{}: {}".format(key.title(), value)
                    for key, value in self.data.items()]
                )
            )
        )
