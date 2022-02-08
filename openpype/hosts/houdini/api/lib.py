import uuid
import logging
from contextlib import contextmanager

import six

from avalon import api, io
from openpype.api import get_asset


import hou

log = logging.getLogger(__name__)


def get_asset_fps():
    """Return current asset fps."""
    return get_asset()["data"].get("fps")


def set_id(node, unique_id, overwrite=False):
    exists = node.parm("id")
    if not exists:
        imprint(node, {"id": unique_id})

    if not exists and overwrite:
        node.setParm("id", unique_id)


def get_id(node):
    """
    Get the `cbId` attribute of the given node
    Args:
        node (hou.Node): the name of the node to retrieve the attribute from

    Returns:
        str

    """

    if node is None:
        return

    id = node.parm("id")
    if node is None:
        return
    return id


def generate_ids(nodes, asset_id=None):
    """Returns new unique ids for the given nodes.

    Note: This does not assign the new ids, it only generates the values.

    To assign new ids using this method:
    >>> nodes = ["a", "b", "c"]
    >>> for node, id in generate_ids(nodes):
    >>>     set_id(node, id)

    To also override any existing values (and assign regenerated ids):
    >>> nodes = ["a", "b", "c"]
    >>> for node, id in generate_ids(nodes):
    >>>     set_id(node, id, overwrite=True)

    Args:
        nodes (list): List of nodes.
        asset_id (str or bson.ObjectId): The database id for the *asset* to
            generate for. When None provided the current asset in the
            active session is used.

    Returns:
        list: A list of (node, id) tuples.

    """

    if asset_id is None:
        # Get the asset ID from the database for the asset of current context
        asset_data = io.find_one({"type": "asset",
                                  "name": api.Session["AVALON_ASSET"]},
                                 projection={"_id": True})
        assert asset_data, "No current asset found in Session"
        asset_id = asset_data['_id']

    node_ids = []
    for node in nodes:
        _, uid = str(uuid.uuid4()).rsplit("-", 1)
        unique_id = "{}:{}".format(asset_id, uid)
        node_ids.append((node, unique_id))

    return node_ids


def get_id_required_nodes():

    valid_types = ["geometry"]
    nodes = {n for n in hou.node("/out").children() if
             n.type().name() in valid_types}

    return list(nodes)


def get_additional_data(container):
    """Not implemented yet!"""
    return container


def set_parameter_callback(node, parameter, language, callback):
    """Link a callback to a parameter of a node

    Args:
        node(hou.Node): instance of the nodee
        parameter(str): name of the parameter
        language(str): name of the language, e.g.: python
        callback(str): command which needs to be triggered

    Returns:
        None

    """

    template_grp = node.parmTemplateGroup()
    template = template_grp.find(parameter)
    if not template:
        return

    script_language = (hou.scriptLanguage.Python if language == "python" else
                       hou.scriptLanguage.Hscript)

    template.setScriptCallbackLanguage(script_language)
    template.setScriptCallback(callback)

    template.setTags({"script_callback": callback,
                      "script_callback_language": language.lower()})

    # Replace the existing template with the adjusted one
    template_grp.replace(parameter, template)

    node.setParmTemplateGroup(template_grp)


def set_parameter_callbacks(node, parameter_callbacks):
    """Set callbacks for multiple parameters of a node

    Args:
        node(hou.Node): instance of a hou.Node
        parameter_callbacks(dict): collection of parameter and callback data
            example:  {"active" :
                        {"language": "python",
                         "callback": "print('hello world)'"}
                     }
    Returns:
        None
    """
    for parameter, data in parameter_callbacks.items():
        language = data["language"]
        callback = data["callback"]

        set_parameter_callback(node, parameter, language, callback)


def get_output_parameter(node):
    """Return the render output parameter name of the given node

    Example:
        root = hou.node("/obj")
        my_alembic_node = root.createNode("alembic")
        get_output_parameter(my_alembic_node)
        # Result: "output"

    Args:
        node(hou.Node): node instance

    Returns:
        hou.Parm

    """

    node_type = node.type().name()
    if node_type == "geometry":
        return node.parm("sopoutput")
    elif node_type == "alembic":
        return node.parm("filename")
    elif node_type == "comp":
        return node.parm("copoutput")
    else:
        raise TypeError("Node type '%s' not supported" % node_type)


@contextmanager
def attribute_values(node, data):

    previous_attrs = {key: node.parm(key).eval() for key in data.keys()}
    try:
        node.setParms(data)
        yield
    except Exception as exc:
        pass
    finally:
        node.setParms(previous_attrs)


def set_scene_fps(fps):
    hou.setFps(fps)


# Valid FPS
def validate_fps():
    """Validate current scene FPS and show pop-up when it is incorrect

    Returns:
        bool

    """

    fps = get_asset_fps()
    current_fps = hou.fps()  # returns float

    if current_fps != fps:

        from openpype.widgets import popup

        # Find main window
        parent = hou.ui.mainQtWindow()
        if parent is None:
            pass
        else:
            dialog = popup.Popup(parent=parent)
            dialog.setModal(True)
            dialog.setWindowTitle("Houdini scene does not match project FPS")
            dialog.setMessage("Scene %i FPS does not match project %i FPS" %
                              (current_fps, fps))
            dialog.setButtonText("Fix")

            # on_show is the Fix button clicked callback
            dialog.on_clicked.connect(lambda: set_scene_fps(fps))

            dialog.show()

            return False

    return True


def create_remote_publish_node(force=True):
    """Function to create a remote publish node in /out

    This is a hacked "Shell" node that does *nothing* except for triggering
    `colorbleed.lib.publish_remote()` as pre-render script.

    All default attributes of the Shell node are hidden to the Artist to
    avoid confusion.

    Additionally some custom attributes are added that can be collected
    by a Collector to set specific settings for the publish, e.g. whether
    to separate the jobs per instance or process in one single job.

    """

    cmd = "import colorbleed.lib; colorbleed.lib.publish_remote()"

    existing = hou.node("/out/REMOTE_PUBLISH")
    if existing:
        if force:
            log.warning("Removing existing '/out/REMOTE_PUBLISH' node..")
            existing.destroy()
        else:
            raise RuntimeError("Node already exists /out/REMOTE_PUBLISH. "
                               "Please remove manually or set `force` to "
                               "True.")

    # Create the shell node
    out = hou.node("/out")
    node = out.createNode("shell", node_name="REMOTE_PUBLISH")
    node.moveToGoodPosition()

    # Set color make it stand out (avalon/pyblish color)
    node.setColor(hou.Color(0.439, 0.709, 0.933))

    # Set the pre-render script
    node.setParms({
        "prerender": cmd,
        "lprerender": "python"  # command language
    })

    # Lock the attributes to ensure artists won't easily mess things up.
    node.parm("prerender").lock(True)
    node.parm("lprerender").lock(True)

    # Lock up the actual shell command
    command_parm = node.parm("command")
    command_parm.set("")
    command_parm.lock(True)
    shellexec_parm = node.parm("shellexec")
    shellexec_parm.set(False)
    shellexec_parm.lock(True)

    # Get the node's parm template group so we can customize it
    template = node.parmTemplateGroup()

    # Hide default tabs
    template.hideFolder("Shell", True)
    template.hideFolder("Scripts", True)

    # Hide default settings
    template.hide("execute", True)
    template.hide("renderdialog", True)
    template.hide("trange", True)
    template.hide("f", True)
    template.hide("take", True)

    # Add custom settings to this node.
    parm_folder = hou.FolderParmTemplate("folder", "Submission Settings")

    # Separate Jobs per Instance
    parm = hou.ToggleParmTemplate(name="separateJobPerInstance",
                                  label="Separate Job per Instance",
                                  default_value=False)
    parm_folder.addParmTemplate(parm)

    # Add our custom Submission Settings folder
    template.append(parm_folder)

    # Apply template back to the node
    node.setParmTemplateGroup(template)


def render_rop(ropnode):
    """Render ROP node utility for Publishing.

    This renders a ROP node with the settings we want during Publishing.
    """
    # Print verbose when in batch mode without UI
    verbose = not hou.isUIAvailable()

    # Render
    try:
        ropnode.render(verbose=verbose,
                       # Allow Deadline to capture completion percentage
                       output_progress=verbose)
    except hou.Error as exc:
        # The hou.Error is not inherited from a Python Exception class,
        # so we explicitly capture the houdini error, otherwise pyblish
        # will remain hanging.
        import traceback
        traceback.print_exc()
        raise RuntimeError("Render failed: {0}".format(exc))


def children_as_string(node):
    return [c.name() for c in node.children()]


def imprint(node, data):
    """Store attributes with value on a node

    Depending on the type of attribute it creates the correct parameter
    template. Houdini uses a template per type, see the docs for more
    information.

    http://www.sidefx.com/docs/houdini/hom/hou/ParmTemplate.html

    Args:
        node(hou.Node): node object from Houdini
        data(dict): collection of attributes and their value

    Returns:
        None

    """

    parm_group = node.parmTemplateGroup()

    parm_folder = hou.FolderParmTemplate("folder", "Extra")
    for key, value in data.items():
        if value is None:
            continue

        if isinstance(value, float):
            parm = hou.FloatParmTemplate(name=key,
                                         label=key,
                                         num_components=1,
                                         default_value=(value,))
        elif isinstance(value, bool):
            parm = hou.ToggleParmTemplate(name=key,
                                          label=key,
                                          default_value=value)
        elif isinstance(value, int):
            parm = hou.IntParmTemplate(name=key,
                                       label=key,
                                       num_components=1,
                                       default_value=(value,))
        elif isinstance(value, six.string_types):
            parm = hou.StringParmTemplate(name=key,
                                          label=key,
                                          num_components=1,
                                          default_value=(value,))
        else:
            raise TypeError("Unsupported type: %r" % type(value))

        parm_folder.addParmTemplate(parm)

    parm_group.append(parm_folder)
    node.setParmTemplateGroup(parm_group)


def lsattr(attr, value=None):
    if value is None:
        nodes = list(hou.node("/obj").allNodes())
        return [n for n in nodes if n.parm(attr)]
    return lsattrs({attr: value})


def lsattrs(attrs):
    """Return nodes matching `key` and `value`

    Arguments:
        attrs (dict): collection of attribute: value

    Example:
        >> lsattrs({"id": "myId"})
        ["myNode"]
        >> lsattr("id")
        ["myNode", "myOtherNode"]

    Returns:
        list
    """

    matches = set()
    nodes = list(hou.node("/obj").allNodes())  # returns generator object
    for node in nodes:
        for attr in attrs:
            if not node.parm(attr):
                continue
            elif node.evalParm(attr) != attrs[attr]:
                continue
            else:
                matches.add(node)

    return list(matches)


def read(node):
    """Read the container data in to a dict

    Args:
        node(hou.Node): Houdini node

    Returns:
        dict

    """
    # `spareParms` returns a tuple of hou.Parm objects
    return {parameter.name(): parameter.eval() for
            parameter in node.spareParms()}


def unique_name(name, format="%03d", namespace="", prefix="", suffix="",
                separator="_"):
    """Return unique `name`

    The function takes into consideration an optional `namespace`
    and `suffix`. The suffix is included in evaluating whether a
    name exists - such as `name` + "_GRP" - but isn't included
    in the returned value.

    If a namespace is provided, only names within that namespace
    are considered when evaluating whether the name is unique.

    Arguments:
        format (str, optional): The `name` is given a number, this determines
            how this number is formatted. Defaults to a padding of 2.
            E.g. my_name01, my_name02.
        namespace (str, optional): Only consider names within this namespace.
        suffix (str, optional): Only consider names with this suffix.

    Example:
        >>> name = hou.node("/obj").createNode("geo", name="MyName")
        >>> assert hou.node("/obj/MyName")
        True
        >>> unique = unique_name(name)
        >>> assert hou.node("/obj/{}".format(unique))
        False

    """

    iteration = 1

    parts = [prefix, name, format % iteration, suffix]
    if namespace:
        parts.insert(0, namespace)

    unique = separator.join(parts)
    children = children_as_string(hou.node("/obj"))
    while unique in children:
        iteration += 1
        unique = separator.join(parts)

    if suffix:
        return unique[:-len(suffix)]

    return unique


@contextmanager
def maintained_selection():
    """Maintain selection during context
    Example:
        >>> with maintained_selection():
        ...     # Modify selection
        ...     node.setSelected(on=False, clear_all_selected=True)
        >>> # Selection restored
    """

    previous_selection = hou.selectedNodes()
    try:
        yield
    finally:
        # Clear the selection
        # todo: does hou.clearAllSelected() do the same?
        for node in hou.selectedNodes():
            node.setSelected(on=False)

        if previous_selection:
            for node in previous_selection:
                node.setSelected(on=True)
