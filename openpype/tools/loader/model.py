import copy
import re
import math
import time
from uuid import uuid4

from qtpy import QtCore, QtGui
import qtawesome

from openpype.client import (
    get_assets,
    get_subsets,
    get_last_versions,
    get_versions,
    get_hero_versions,
    get_version_by_name,
    get_representations
)
from openpype.pipeline import (
    registered_host,
    HeroVersionType,
    schema,
)

from openpype.style import get_default_entity_icon_color
from openpype.tools.utils.models import TreeModel, Item
from openpype.tools.utils import lib
from openpype.host import ILoadHost

from openpype.modules import ModulesManager
from openpype.tools.utils.constants import (
    LOCAL_PROVIDER_ROLE,
    REMOTE_PROVIDER_ROLE,
    LOCAL_AVAILABILITY_ROLE,
    REMOTE_AVAILABILITY_ROLE
)

ITEM_ID_ROLE = QtCore.Qt.UserRole + 90


def is_filtering_recursible():
    """Does Qt binding support recursive filtering for QSortFilterProxyModel?

    (NOTE) Recursive filtering was introduced in Qt 5.10.

    """
    return hasattr(QtCore.QSortFilterProxyModel,
                   "setRecursiveFilteringEnabled")


class BaseRepresentationModel(object):
    """Methods for SyncServer useful in multiple models"""
    # Cheap & hackish way how to avoid refreshing of whole sync server module
    #   on each selection change
    _last_project = None
    _modules_manager = None
    _last_project_cache = 0
    _last_manager_cache = 0
    _max_project_cache_time = 30
    _max_manager_cache_time = 60

    def reset_sync_server(self, project_name=None):
        """Sets/Resets sync server vars after every change (refresh.)"""
        repre_icons = {}
        sync_server = None
        active_site = active_provider = None
        remote_site = remote_provider = None

        if not project_name:
            project_name = self.dbcon.active_project()
        else:
            self.dbcon.Session["AVALON_PROJECT"] = project_name

        if not project_name:
            self.repre_icons = repre_icons
            self.sync_server = sync_server
            self.active_site = active_site
            self.active_provider = active_provider
            self.remote_site = remote_site
            self.remote_provider = remote_provider
            return

        now_time = time.time()
        project_cache_diff = now_time - self._last_project_cache
        if project_cache_diff > self._max_project_cache_time:
            self._last_project = None

        if project_name == self._last_project:
            return

        self._last_project = project_name
        self._last_project_cache = now_time

        manager_cache_diff = now_time - self._last_manager_cache
        if manager_cache_diff > self._max_manager_cache_time:
            self._modules_manager = None

        if self._modules_manager is None:
            self._modules_manager = ModulesManager()
            self._last_manager_cache = now_time

        sync_server = self._modules_manager.modules_by_name["sync_server"]
        if sync_server.is_project_enabled(project_name, single=True):
            active_site = sync_server.get_active_site(project_name)
            active_provider = sync_server.get_provider_for_site(
                project_name, active_site)
            if active_site == 'studio':  # for studio use explicit icon
                active_provider = 'studio'

            remote_site = sync_server.get_remote_site(project_name)
            remote_provider = sync_server.get_provider_for_site(
                project_name, remote_site)
            if remote_site == 'studio':  # for studio use explicit icon
                remote_provider = 'studio'

            repre_icons = lib.get_repre_icons()

        self.repre_icons = repre_icons
        self.sync_server = sync_server
        self.active_site = active_site
        self.active_provider = active_provider
        self.remote_site = remote_site
        self.remote_provider = remote_provider


class SubsetsModel(BaseRepresentationModel, TreeModel):
    doc_fetched = QtCore.Signal()
    refreshed = QtCore.Signal(bool)

    Columns = [
        "subset",
        "asset",
        "family",
        "version",
        "time",
        "author",
        "frames",
        "duration",
        "handles",
        "step",
        "loaded_in_scene",
        "repre_info"
    ]

    column_labels_mapping = {
        "subset": "Subset",
        "asset": "Asset",
        "family": "Family",
        "version": "Version",
        "time": "Time",
        "author": "Author",
        "frames": "Frames",
        "duration": "Duration",
        "handles": "Handles",
        "step": "Step",
        "loaded_in_scene": "In scene",
        "repre_info": "Availability"
    }

    SortAscendingRole = QtCore.Qt.UserRole + 2
    SortDescendingRole = QtCore.Qt.UserRole + 3
    merged_subset_colors = [
        (55, 161, 222),  # Light Blue
        (231, 176, 0),  # Yellow
        (154, 13, 255),  # Purple
        (130, 184, 30),  # Light Green
        (211, 79, 63),  # Light Red
        (179, 181, 182),  # Grey
        (194, 57, 179),  # Pink
        (0, 120, 215),  # Dark Blue
        (0, 204, 106),  # Dark Green
        (247, 99, 12),  # Orange
    ]
    not_last_hero_brush = QtGui.QBrush(QtGui.QColor(254, 121, 121))

    # Should be minimum of required asset document keys
    asset_doc_projection = {
        "name": 1,
        "label": 1
    }
    # Should be minimum of required subset document keys
    subset_doc_projection = {
        "name": 1,
        "parent": 1,
        "schema": 1,
        "data.families": 1,
        "data.subsetGroup": 1
    }

    def __init__(
        self,
        dbcon,
        groups_config,
        family_config_cache,
        grouping=True,
        parent=None,
        asset_doc_projection=None,
        subset_doc_projection=None
    ):
        super(SubsetsModel, self).__init__(parent=parent)

        self.dbcon = dbcon

        # Projections for Mongo queries
        # - let ability to modify them if used in tools that require more than
        #   defaults
        if asset_doc_projection:
            self.asset_doc_projection = asset_doc_projection

        if subset_doc_projection:
            self.subset_doc_projection = subset_doc_projection

        self.repre_icons = {}
        self.sync_server = None
        self.active_site = self.active_provider = None

        self.columns_index = dict(
            (key, idx) for idx, key in enumerate(self.Columns)
        )
        self._asset_ids = None

        self.groups_config = groups_config
        self.family_config_cache = family_config_cache
        self._sorter = None
        self._grouping = grouping
        self._icons = {
            "subset": qtawesome.icon(
                "fa.file-o",
                color=get_default_entity_icon_color()
            )
        }
        self._items_by_id = {}

        self._doc_fetching_thread = None
        self._doc_fetching_stop = False
        self._doc_payload = {}

        self._host = registered_host()
        self._loaded_representation_ids = set()

        # Refresh loaded scene containers only every 3 seconds at most
        self._host_loaded_refresh_timeout = 3
        self._host_loaded_refresh_time = 0

        self.doc_fetched.connect(self._on_doc_fetched)
        self.refresh()

    def get_item_by_id(self, item_id):
        return self._items_by_id.get(item_id)

    def add_child(self, new_item, *args, **kwargs):
        item_id = str(uuid4())
        new_item["id"] = item_id
        self._items_by_id[item_id] = new_item
        super(SubsetsModel, self).add_child(new_item, *args, **kwargs)

    def set_assets(self, asset_ids):
        self._asset_ids = asset_ids
        self.refresh()

    def set_grouping(self, state):
        self._grouping = state
        self._on_doc_fetched()

    def get_subsets_families(self):
        return self._doc_payload.get("subset_families") or set()

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        # Trigger additional edit when `version` column changed
        # because it also updates the information in other columns
        if index.column() == self.columns_index["version"]:
            item = index.internalPointer()
            subset_id = item["_id"]
            if isinstance(value, HeroVersionType):
                version_doc = self._get_hero_version(subset_id)

            else:
                project_name = self.dbcon.active_project()
                version_doc = get_version_by_name(
                    project_name, value, subset_id
                )

                # update availability on active site when version changes
                if self.sync_server.enabled and version_doc:
                    repres_info = list(
                        self.sync_server.get_repre_info_for_versions(
                            project_name,
                            [version_doc["_id"]],
                            self.active_site,
                            self.remote_site
                        )
                    )
                    if repres_info:
                        version_doc["data"].update(
                            self._get_repre_dict(repres_info[0]))

            self.set_version(index, version_doc)

        return super(SubsetsModel, self).setData(index, value, role)

    def _get_hero_version(self, subset_id):
        project_name = self.dbcon.active_project()
        version_docs = get_versions(
            project_name, subset_ids=[subset_id], hero=True
        )
        standard_versions = []
        hero_version_doc = None
        for version_doc in version_docs:
            if version_doc["type"] == "hero_version":
                hero_version_doc = version_doc
                continue
            standard_versions.append(version_doc)

        src_version_id = hero_version_doc["version_id"]
        src_version = None
        is_from_latest = True
        for version_doc in reversed(sorted(
            standard_versions, key=lambda item: item["name"]
        )):
            if version_doc["_id"] == src_version_id:
                src_version = version_doc
                break
            is_from_latest = False

        hero_version_doc["data"] = src_version["data"]
        hero_version_doc["name"] = src_version["name"]
        hero_version_doc["is_from_latest"] = is_from_latest
        return hero_version_doc

    def set_version(self, index, version):
        """Update the version data of the given index.

        Arguments:
            index (QtCore.QModelIndex): The model index.
            version (dict) Version document in the database.

        """

        assert isinstance(index, QtCore.QModelIndex)
        if not index.isValid():
            return

        item = index.internalPointer()

        assert version["parent"] == item["_id"], (
            "Version does not belong to subset"
        )

        # Get the data from the version
        version_data = version.get("data", dict())

        # Compute frame ranges (if data is present)
        frame_start = version_data.get(
            "frameStart",
            # backwards compatibility
            version_data.get("startFrame", None)
        )
        frame_end = version_data.get(
            "frameEnd",
            # backwards compatibility
            version_data.get("endFrame", None)
        )

        handles_label = None
        handle_start = version_data.get("handleStart", None)
        handle_end = version_data.get("handleEnd", None)
        if handle_start is not None and handle_end is not None:
            handles_label = "{}-{}".format(str(handle_start), str(handle_end))

        if frame_start is not None and frame_end is not None:
            # Remove superfluous zeros from numbers (3.0 -> 3) to improve
            # readability for most frame ranges
            start_clean = ("%f" % frame_start).rstrip("0").rstrip(".")
            end_clean = ("%f" % frame_end).rstrip("0").rstrip(".")
            frames = "{0}-{1}".format(start_clean, end_clean)
            duration = frame_end - frame_start + 1
        else:
            frames = None
            duration = None

        schema_maj_version, _ = schema.get_schema_version(item["schema"])
        if schema_maj_version < 3:
            families = version_data.get("families", [None])
        else:
            families = item["data"]["families"]

        family = None
        if families:
            family = families[0]

        family_config = self.family_config_cache.family_config(family)

        item.update({
            "version": version["name"],
            "version_document": version,
            "author": version_data.get("author", None),
            "time": version_data.get("time", None),
            "family": family,
            "familyLabel": family_config.get("label", family),
            "familyIcon": family_config.get("icon", None),
            "families": set(families),
            "frameStart": frame_start,
            "frameEnd": frame_end,
            "duration": duration,
            "handles": handles_label,
            "frames": frames,
            "step": version_data.get("step", None),
        })

        repre_info = version_data.get("repre_info")
        if repre_info:
            item["repre_info"] = repre_info

    def _fetch(self):
        project_name = self.dbcon.active_project()
        asset_docs = get_assets(
            project_name,
            asset_ids=self._asset_ids,
            fields=self.asset_doc_projection.keys()
        )

        asset_docs_by_id = {
            asset_doc["_id"]: asset_doc
            for asset_doc in asset_docs
        }

        subset_docs_by_id = {}
        subset_docs = get_subsets(
            project_name,
            asset_ids=self._asset_ids,
            fields=self.subset_doc_projection.keys()
        )

        subset_families = set()
        for subset_doc in subset_docs:
            if self._doc_fetching_stop:
                return

            families = subset_doc.get("data", {}).get("families")
            if families:
                subset_families.add(families[0])

            subset_docs_by_id[subset_doc["_id"]] = subset_doc

        subset_ids = list(subset_docs_by_id.keys())
        last_versions_by_subset_id = get_last_versions(
            project_name,
            subset_ids,
            fields=["_id", "parent", "name", "type", "data", "schema"]
        )

        hero_versions = get_hero_versions(project_name, subset_ids=subset_ids)
        missing_versions = []
        for hero_version in hero_versions:
            version_id = hero_version["version_id"]
            if version_id not in last_versions_by_subset_id:
                missing_versions.append(version_id)

        missing_versions_by_id = {}
        if missing_versions:
            missing_version_docs = get_versions(
                project_name, version_ids=missing_versions
            )
            missing_versions_by_id = {
                missing_version_doc["_id"]: missing_version_doc
                for missing_version_doc in missing_version_docs
            }

        for hero_version in hero_versions:
            version_id = hero_version["version_id"]
            subset_id = hero_version["parent"]

            version_doc = last_versions_by_subset_id.get(subset_id)
            if version_doc is None:
                version_doc = missing_versions_by_id.get(version_id)
                if version_doc is None:
                    continue

            hero_version["data"] = version_doc["data"]
            hero_version["name"] = HeroVersionType(version_doc["name"])
            # Add information if hero version is from latest version
            hero_version["is_from_latest"] = version_id == version_doc["_id"]

            last_versions_by_subset_id[subset_id] = hero_version

        # Check loaded subsets
        loaded_subset_ids = set()
        ids = self._loaded_representation_ids
        if ids:
            if self._doc_fetching_stop:
                return

            # Get subset ids from loaded representations in workfile
            # todo: optimize with aggregation query to distinct subset id
            representations = get_representations(project_name,
                                                  representation_ids=ids,
                                                  fields=["parent"])
            version_ids = set(repre["parent"] for repre in representations)
            versions = get_versions(project_name,
                                    version_ids=version_ids,
                                    fields=["parent"])
            loaded_subset_ids = set(version["parent"] for version in versions)

        if self._doc_fetching_stop:
            return

        repre_info_by_version_id = {}
        if self.sync_server.enabled:
            versions_by_id = {}
            for _subset_id, doc in last_versions_by_subset_id.items():
                versions_by_id[doc["_id"]] = doc

            repres_info = self.sync_server.get_repre_info_for_versions(
                project_name,
                list(versions_by_id.keys()),
                self.active_site,
                self.remote_site
            )
            for repre_info in repres_info:
                if self._doc_fetching_stop:
                    return

                version_id = repre_info["_id"]
                doc = versions_by_id[version_id]
                doc["active_provider"] = self.active_provider
                doc["remote_provider"] = self.remote_provider
                repre_info_by_version_id[version_id] = repre_info

        self._doc_payload = {
            "asset_docs_by_id": asset_docs_by_id,
            "subset_docs_by_id": subset_docs_by_id,
            "subset_families": subset_families,
            "last_versions_by_subset_id": last_versions_by_subset_id,
            "repre_info_by_version_id": repre_info_by_version_id,
            "subsets_loaded_by_id": loaded_subset_ids
        }

        self.doc_fetched.emit()

    def fetch_subset_and_version(self):
        """Query all subsets and latest versions from aggregation
        (NOTE) The returned version documents are NOT the real version
            document, it's generated from the MongoDB's aggregation so
            some of the first level field may not be presented.
        """
        self._doc_payload = {}
        self._doc_fetching_stop = False
        self._doc_fetching_thread = lib.create_qthread(self._fetch)
        self._doc_fetching_thread.start()

    def stop_fetch_thread(self):
        if self._doc_fetching_thread is not None:
            self._doc_fetching_stop = True
            while self._doc_fetching_thread.isRunning():
                pass

    def refresh(self):
        self.stop_fetch_thread()
        self.clear()
        self._items_by_id = {}
        self.reset_sync_server()

        if not self._asset_ids:
            self.doc_fetched.emit()
            return

        # Collect scene container representations to compare loaded state
        # This runs in the main thread because it involves the host DCC
        if self._host:
            time_since_refresh = time.time() - self._host_loaded_refresh_time
            if time_since_refresh > self._host_loaded_refresh_timeout:
                if isinstance(self._host, ILoadHost):
                    containers = self._host.get_containers()
                else:
                    containers = self._host.ls()

                repre_ids = {con.get("representation") for con in containers}
                self._loaded_representation_ids = repre_ids
                self._host_loaded_refresh_time = time.time()

        self.fetch_subset_and_version()

    def _on_doc_fetched(self):
        self.clear()
        self._items_by_id = {}
        self.beginResetModel()

        asset_docs_by_id = self._doc_payload.get(
            "asset_docs_by_id"
        )
        subset_docs_by_id = self._doc_payload.get(
            "subset_docs_by_id"
        )
        last_versions_by_subset_id = self._doc_payload.get(
            "last_versions_by_subset_id"
        )

        repre_info_by_version_id = self._doc_payload.get(
            "repre_info_by_version_id"
        )

        subsets_loaded_by_id = self._doc_payload.get(
            "subsets_loaded_by_id"
        )

        if (
            asset_docs_by_id is None
            or subset_docs_by_id is None
            or last_versions_by_subset_id is None
            or len(self._asset_ids) == 0
        ):
            self.endResetModel()
            self.refreshed.emit(False)
            return

        self._fill_subset_items(
            asset_docs_by_id,
            subset_docs_by_id,
            last_versions_by_subset_id,
            repre_info_by_version_id,
            subsets_loaded_by_id
        )
        self.endResetModel()
        self.refreshed.emit(True)

    def create_multiasset_group(
        self, subset_name, asset_ids, subset_counter, parent_item=None
    ):
        subset_color = self.merged_subset_colors[
            subset_counter % len(self.merged_subset_colors)
        ]
        merge_group = Item()
        merge_group.update({
            "subset": "{} ({})".format(subset_name, len(asset_ids)),
            "isMerged": True,
            "subsetColor": subset_color,
            "assetIds": list(asset_ids),
            "icon": qtawesome.icon(
                "fa.circle",
                color="#{0:02x}{1:02x}{2:02x}".format(*subset_color)
            )
        })

        self.add_child(merge_group, parent_item)

        return merge_group

    def _fill_subset_items(
        self,
        asset_docs_by_id,
        subset_docs_by_id,
        last_versions_by_subset_id,
        repre_info_by_version_id,
        subsets_loaded_by_id
    ):
        _groups_tuple = self.groups_config.split_subsets_for_groups(
            subset_docs_by_id.values(), self._grouping
        )
        groups, subset_docs_without_group, subset_docs_by_group = _groups_tuple

        group_item_by_name = {}
        for group_data in groups:
            group_name = group_data["name"]
            group_item = Item()
            group_item.update({
                "subset": group_name,
                "isGroup": True
            })
            group_item.update(group_data)

            self.add_child(group_item)

            group_item_by_name[group_name] = {
                "item": group_item,
                "index": self.index(group_item.row(), 0)
            }

        def _add_subset_item(subset_doc, parent_item, parent_index):
            last_version = last_versions_by_subset_id.get(
                subset_doc["_id"]
            )
            # do not show subset without version
            if not last_version:
                return

            data = copy.deepcopy(subset_doc)
            data["subset"] = subset_doc["name"]

            asset_id = subset_doc["parent"]
            data["asset"] = asset_docs_by_id[asset_id]["name"]

            data["last_version"] = last_version
            data["loaded_in_scene"] = subset_doc["_id"] in subsets_loaded_by_id

            # Sync server data
            data.update(
                self._get_last_repre_info(repre_info_by_version_id,
                                          last_version["_id"]))

            item = Item()
            item.update(data)
            self.add_child(item, parent_item)

            index = self.index(item.row(), 0, parent_index)
            self.set_version(index, last_version)

        subset_counter = 0
        for group_name, subset_docs_by_name in subset_docs_by_group.items():
            parent_item = group_item_by_name[group_name]["item"]
            parent_index = group_item_by_name[group_name]["index"]
            for subset_name in sorted(subset_docs_by_name.keys()):
                subset_docs = subset_docs_by_name[subset_name]
                asset_ids = [
                    subset_doc["parent"] for subset_doc in subset_docs
                ]
                if len(subset_docs) > 1:
                    _parent_item = self.create_multiasset_group(
                        subset_name, asset_ids, subset_counter, parent_item
                    )
                    _parent_index = self.index(
                        _parent_item.row(), 0, parent_index
                    )
                    subset_counter += 1
                else:
                    _parent_item = parent_item
                    _parent_index = parent_index

                for subset_doc in subset_docs:
                    _add_subset_item(subset_doc,
                                     parent_item=_parent_item,
                                     parent_index=_parent_index)

        for subset_name in sorted(subset_docs_without_group.keys()):
            subset_docs = subset_docs_without_group[subset_name]
            asset_ids = [subset_doc["parent"] for subset_doc in subset_docs]
            parent_item = None
            parent_index = None
            if len(subset_docs) > 1:
                parent_item = self.create_multiasset_group(
                    subset_name, asset_ids, subset_counter
                )
                parent_index = self.index(parent_item.row(), 0)
                subset_counter += 1

            for subset_doc in subset_docs:
                _add_subset_item(subset_doc,
                                 parent_item=parent_item,
                                 parent_index=parent_index)

    def data(self, index, role):
        if not index.isValid():
            return

        item = index.internalPointer()
        if role == ITEM_ID_ROLE:
            return item["id"]

        if role == self.SortDescendingRole:
            if item.get("isGroup"):
                # Ensure groups be on top when sorting by descending order
                prefix = "2"
                order = item["order"]
            else:
                if item.get("isMerged"):
                    prefix = "1"
                else:
                    prefix = "0"
                order = str(super(SubsetsModel, self).data(
                    index, QtCore.Qt.DisplayRole
                ))
            return prefix + order

        if role == self.SortAscendingRole:
            if item.get("isGroup"):
                # Ensure groups be on top when sorting by ascending order
                prefix = "0"
                order = item["order"]
            else:
                if item.get("isMerged"):
                    prefix = "1"
                else:
                    prefix = "2"
                order = str(super(SubsetsModel, self).data(
                    index, QtCore.Qt.DisplayRole
                ))
            return prefix + order

        if role == QtCore.Qt.DisplayRole:
            if index.column() == self.columns_index["family"]:
                # Show familyLabel instead of family
                return item.get("familyLabel", None)

        elif role == QtCore.Qt.DecorationRole:

            # Add icon to subset column
            if index.column() == self.columns_index["subset"]:
                if item.get("isGroup") or item.get("isMerged"):
                    return item["icon"]
                else:
                    return self._icons["subset"]

            # Add icon to family column
            if index.column() == self.columns_index["family"]:
                return item.get("familyIcon", None)

        elif role == QtCore.Qt.ForegroundRole:
            version_doc = item.get("version_document")
            if version_doc and version_doc.get("type") == "hero_version":
                if not version_doc["is_from_latest"]:
                    return self.not_last_hero_brush

        elif role == LOCAL_AVAILABILITY_ROLE:
            if not item.get("isGroup"):
                return item.get("repre_info_local")
            else:
                return None

        elif role == REMOTE_AVAILABILITY_ROLE:
            if not item.get("isGroup"):
                return item.get("repre_info_remote")
            else:
                return None

        elif role == LOCAL_PROVIDER_ROLE:
            return self.active_provider

        elif role == REMOTE_PROVIDER_ROLE:
            return self.remote_provider

        return super(SubsetsModel, self).data(index, role)

    def flags(self, index):
        flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

        # Make the version column editable
        if index.column() == self.columns_index["version"]:
            flags |= QtCore.Qt.ItemIsEditable

        return flags

    def headerData(self, section, orientation, role):
        """Remap column names to labels"""
        if role == QtCore.Qt.DisplayRole:
            if section < len(self.Columns):
                key = self.Columns[section]
                return self.column_labels_mapping.get(key) or key

        super(TreeModel, self).headerData(section, orientation, role)

    def _get_last_repre_info(self, repre_info_by_version_id, last_version_id):
        data = {}
        if repre_info_by_version_id:
            repre_info = repre_info_by_version_id.get(last_version_id)
            return self._get_repre_dict(repre_info)

        return data

    def _get_repre_dict(self, repre_info):
        """Returns str representation of availability"""
        data = {}
        if repre_info:
            repres_str = "{}/{}".format(
                int(math.floor(float(repre_info['avail_repre_local']))),
                int(math.floor(float(repre_info['repre_count']))))

            data["repre_info_local"] = repres_str

            repres_str = "{}/{}".format(
                int(math.floor(float(repre_info['avail_repre_remote']))),
                int(math.floor(float(repre_info['repre_count']))))

            data["repre_info_remote"] = repres_str

        return data


class GroupMemberFilterProxyModel(QtCore.QSortFilterProxyModel):
    """Provide the feature of filtering group by the acceptance of members

    The subset group nodes will not be filtered directly, the group node's
    acceptance depends on it's child subsets' acceptance.

    """

    if is_filtering_recursible():
        def _is_group_acceptable(self, index, node):
            # (NOTE) With the help of `RecursiveFiltering` feature from
            #        Qt 5.10, group always not be accepted by default.
            return False
        filter_accepts_group = _is_group_acceptable

    else:
        # Patch future function
        setRecursiveFilteringEnabled = (lambda *args: None)

        def _is_group_acceptable(self, index, model):
            # (NOTE) This is not recursive.
            for child_row in range(model.rowCount(index)):
                if self.filterAcceptsRow(child_row, index):
                    return True
            return False
        filter_accepts_group = _is_group_acceptable

    def __init__(self, *args, **kwargs):
        super(GroupMemberFilterProxyModel, self).__init__(*args, **kwargs)
        self.setRecursiveFilteringEnabled(True)


class SubsetFilterProxyModel(GroupMemberFilterProxyModel):
    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        index = model.index(row, self.filterKeyColumn(), parent)
        item = index.internalPointer()
        if item.get("isGroup"):
            return self.filter_accepts_group(index, model)
        return super(
            SubsetFilterProxyModel, self
        ).filterAcceptsRow(row, parent)


class FamiliesFilterProxyModel(GroupMemberFilterProxyModel):
    """Filters to specified families"""

    def __init__(self, *args, **kwargs):
        super(FamiliesFilterProxyModel, self).__init__(*args, **kwargs)
        self._families = set()

    def familyFilter(self):
        return self._families

    def setFamiliesFilter(self, values):
        """Set the families to include"""
        assert isinstance(values, (tuple, list, set))
        self._families = set(values)
        self.invalidateFilter()

    def filterAcceptsRow(self, row=0, parent=None):
        if not self._families:
            return False

        model = self.sourceModel()
        index = model.index(row, 0, parent=parent or QtCore.QModelIndex())

        # Ensure index is valid
        if not index.isValid() or index is None:
            return True

        # Get the item data and validate
        item = model.data(index, TreeModel.ItemRole)

        if item.get("isGroup"):
            return self.filter_accepts_group(index, model)

        family = item.get("family")
        if not family:
            return True

        # We want to keep the families which are not in the list
        return family in self._families

    def sort(self, column, order):
        proxy = self.sourceModel()
        model = proxy.sourceModel()
        # We need to know the sorting direction for pinning groups on top
        if order == QtCore.Qt.AscendingOrder:
            self.setSortRole(model.SortAscendingRole)
        else:
            self.setSortRole(model.SortDescendingRole)

        super(FamiliesFilterProxyModel, self).sort(column, order)


class RepresentationSortProxyModel(GroupMemberFilterProxyModel):
    """To properly sort progress string"""
    def lessThan(self, left, right):
        source_model = self.sourceModel()
        progress_indexes = [source_model.Columns.index("active_site"),
                            source_model.Columns.index("remote_site")]
        if left.column() in progress_indexes:
            left_data = self.sourceModel().data(left, QtCore.Qt.DisplayRole)
            right_data = self.sourceModel().data(right, QtCore.Qt.DisplayRole)
            left_val = re.sub("[^0-9]", '', left_data)
            right_val = re.sub("[^0-9]", '', right_data)

            return int(left_val) < int(right_val)

        return super(RepresentationSortProxyModel, self).lessThan(left, right)


class RepresentationModel(TreeModel, BaseRepresentationModel):
    doc_fetched = QtCore.Signal()
    refreshed = QtCore.Signal(bool)

    SiteNameRole = QtCore.Qt.UserRole + 2
    ProgressRole = QtCore.Qt.UserRole + 3
    SiteSideRole = QtCore.Qt.UserRole + 4
    IdRole = QtCore.Qt.UserRole + 5
    ContextRole = QtCore.Qt.UserRole + 6

    Columns = [
        "name",
        "subset",
        "asset",
        "active_site",
        "remote_site"
    ]

    column_labels_mapping = {
        "name": "Name",
        "subset": "Subset",
        "asset": "Asset",
        "active_site": "Active",
        "remote_site": "Remote"
    }

    repre_projection = {
        "_id": 1,
        "name": 1,
        "context.subset": 1,
        "context.asset": 1,
        "context.version": 1,
        "context.representation": 1,
        'files.sites': 1
    }

    def __init__(self, dbcon, header):
        super(RepresentationModel, self).__init__()
        self.dbcon = dbcon
        self._data = []
        self._header = header
        self._version_ids = []

        manager = ModulesManager()
        sync_server = active_site = remote_site = None
        active_provider = remote_provider = None

        project_name = dbcon.current_project()
        if project_name:
            sync_server = manager.modules_by_name["sync_server"]
            active_site = sync_server.get_active_site(project_name)
            remote_site = sync_server.get_remote_site(project_name)

            # TODO refactor
            active_provider = sync_server.get_provider_for_site(
                project_name, active_site
            )
            if active_site == 'studio':
                active_provider = 'studio'

            remote_provider = sync_server.get_provider_for_site(
                project_name, remote_site
            )

            if remote_site == 'studio':
                remote_provider = 'studio'

        self.sync_server = sync_server
        self.active_site = active_site
        self.active_provider = active_provider
        self.remote_site = remote_site
        self.remote_provider = remote_provider

        self.doc_fetched.connect(self._on_doc_fetched)

        self._docs = {}
        self._icons = lib.get_repre_icons()
        self._icons["repre"] = qtawesome.icon(
            "fa.file-o",
            color=get_default_entity_icon_color()
        )
        self._items_by_id = {}

    def set_version_ids(self, version_ids):
        self._version_ids = version_ids
        self.refresh()

    def data(self, index, role):
        item = index.internalPointer()

        if role == ITEM_ID_ROLE:
            return item["id"]

        if role == self.IdRole:
            return item.get("_id")

        if role == QtCore.Qt.DecorationRole:
            # Add icon to subset column
            if index.column() == self.Columns.index("name"):
                if item.get("isMerged"):
                    return item["icon"]
                return self._icons["repre"]

        active_index = self.Columns.index("active_site")
        remote_index = self.Columns.index("remote_site")
        if role == QtCore.Qt.DisplayRole:
            progress = None
            label = ''
            if index.column() == active_index:
                progress = item.get("active_site_progress", 0)
            elif index.column() == remote_index:
                progress = item.get("remote_site_progress", 0)

            if progress is not None:
                # site added, sync in progress
                progress_str = "not avail."
                if progress >= 0:
                    if progress == 0 and item.get("isMerged"):
                        progress_str = "not avail."
                    else:
                        progress_str = "{}% {}".format(
                            int(progress * 100), label
                        )

                return progress_str

        if role == QtCore.Qt.DecorationRole:
            if index.column() == active_index:
                return item.get("active_site_icon", None)
            if index.column() == remote_index:
                return item.get("remote_site_icon", None)

        if role == self.SiteNameRole:
            if index.column() == active_index:
                return item.get("active_site_name", None)
            if index.column() == remote_index:
                return item.get("remote_site_name", None)

        if role == self.SiteSideRole:
            if index.column() == active_index:
                return "active"
            if index.column() == remote_index:
                return "remote"

        if role == self.ProgressRole:
            if index.column() == active_index:
                return item.get("active_site_progress", 0)
            if index.column() == remote_index:
                return item.get("remote_site_progress", 0)

        return super(RepresentationModel, self).data(index, role)

    def _on_doc_fetched(self):
        self.clear()
        self.beginResetModel()
        subsets = set()
        assets = set()
        repre_groups = {}
        repre_groups_items = {}
        group = None
        self._items_by_id = {}
        for doc in self._docs:
            if len(self._version_ids) > 1:
                group = repre_groups.get(doc["name"])
                if not group:
                    group_item = Item()
                    item_id = str(uuid4())
                    group_item.update({
                        "id": item_id,
                        "_id": doc["_id"],
                        "name": doc["name"],
                        "isMerged": True,
                        "active_site_name": self.active_site,
                        "remote_site_name": self.remote_site,
                        "icon": qtawesome.icon(
                            "fa.folder",
                            color=get_default_entity_icon_color()
                        )
                    })
                    self._items_by_id[item_id] = group_item
                    self.add_child(group_item, None)
                    repre_groups[doc["name"]] = group_item
                    repre_groups_items[doc["name"]] = 0
                    group = group_item

            progress = lib.get_progress_for_repre(
                doc, self.active_site, self.remote_site
            )

            active_site_icon = self._icons.get(self.active_provider)
            remote_site_icon = self._icons.get(self.remote_provider)

            item_id = str(uuid4())
            data = {
                "id": item_id,
                "_id": doc["_id"],
                "name": doc["name"],
                "subset": doc["context"]["subset"],
                "asset": doc["context"]["asset"],
                "isMerged": False,

                "active_site_icon": active_site_icon,
                "remote_site_icon": remote_site_icon,
                "active_site_name": self.active_site,
                "remote_site_name": self.remote_site,
                "active_site_progress": progress[self.active_site],
                "remote_site_progress": progress[self.remote_site]
            }
            subsets.add(doc["context"]["subset"])
            assets.add(doc["context"]["subset"])

            item = Item()
            item.update(data)
            self._items_by_id[item_id] = item

            current_progress = {
                'active_site_progress': progress[self.active_site],
                'remote_site_progress': progress[self.remote_site]
            }
            if group:
                group = self._sum_group_progress(
                    doc["name"], group, current_progress, repre_groups_items
                )

            self.add_child(item, group)

        # finalize group average progress
        for group_name, group in repre_groups.items():
            items_cnt = repre_groups_items[group_name]
            active_progress = group.get("active_site_progress", 0)
            group["active_site_progress"] = active_progress / items_cnt
            remote_progress = group.get("remote_site_progress", 0)
            group["remote_site_progress"] = remote_progress / items_cnt

        self.endResetModel()
        self.refreshed.emit(False)

    def get_item_by_id(self, item_id):
        return self._items_by_id.get(item_id)

    def refresh(self):
        project_name = self.dbcon.current_project()
        if not project_name:
            return

        repre_docs = []
        if self._version_ids:
            # Simple find here for now, expected to receive lower number of
            # representations and logic could be in Python
            repre_docs = list(get_representations(
                project_name,
                version_ids=self._version_ids,
                fields=self.repre_projection.keys()
            ))

        self._docs = repre_docs

        self.doc_fetched.emit()

    def _sum_group_progress(
        self, repre_name, group, current_item_progress, repre_groups_items
    ):
        """Update final group progress

        Called after every item in group is added

        Args:
            repre_name(string)
            group(dict): info about group of selected items
            current_item_progress(dict): {'active_site_progress': XX,
                                          'remote_site_progress': YY}
            repre_groups_items(dict)
        Returns:
            (dict): updated group info
        """
        repre_groups_items[repre_name] += 1

        for key, progress in current_item_progress.items():
            group[key] = (group.get(key, 0) + max(progress, 0))

        return group
