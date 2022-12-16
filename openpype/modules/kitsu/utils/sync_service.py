import os
import threading

import gazu

from openpype.client import get_project, get_assets, get_asset_by_name
from openpype.pipeline import AvalonMongoDB
from .credentials import validate_credentials
from .update_op_with_zou import (
    create_op_asset,
    set_op_project,
    get_kitsu_project_name,
    write_project_to_op,
    update_op_assets,
)


class Listener:
    """Host Kitsu listener."""

    def __init__(self, login, password):
        """Create client and add listeners to events without starting it.

            Run `listener.start()` to actually start the service.

        Args:
            login (str): Kitsu user login
            password (str): Kitsu user password

        Raises:
            AuthFailedException: Wrong user login and/or password
        """
        self.dbcon = AvalonMongoDB()
        self.dbcon.install()

        gazu.client.set_host(os.environ["KITSU_SERVER"])

        # Authenticate
        if not validate_credentials(login, password):
            raise gazu.exception.AuthFailedException(
                f"Kitsu authentication failed for login: '{login}'..."
            )

        gazu.set_event_host(
            os.environ["KITSU_SERVER"].replace("api", "socket.io")
        )
        self.event_client = gazu.events.init()

        gazu.events.add_listener(
            self.event_client, "project:new", self._new_project
        )
        gazu.events.add_listener(
            self.event_client, "project:update", self._update_project
        )
        gazu.events.add_listener(
            self.event_client, "project:delete", self._delete_project
        )

        gazu.events.add_listener(
            self.event_client, "asset:new", self._new_asset
        )
        gazu.events.add_listener(
            self.event_client, "asset:update", self._update_asset
        )
        gazu.events.add_listener(
            self.event_client, "asset:delete", self._delete_asset
        )

        gazu.events.add_listener(
            self.event_client, "episode:new", self._new_episode
        )
        gazu.events.add_listener(
            self.event_client, "episode:update", self._update_episode
        )
        gazu.events.add_listener(
            self.event_client, "episode:delete", self._delete_episode
        )

        gazu.events.add_listener(
            self.event_client, "sequence:new", self._new_sequence
        )
        gazu.events.add_listener(
            self.event_client, "sequence:update", self._update_sequence
        )
        gazu.events.add_listener(
            self.event_client, "sequence:delete", self._delete_sequence
        )

        gazu.events.add_listener(self.event_client, "shot:new", self._new_shot)
        gazu.events.add_listener(
            self.event_client, "shot:update", self._update_shot
        )
        gazu.events.add_listener(
            self.event_client, "shot:delete", self._delete_shot
        )

        gazu.events.add_listener(self.event_client, "task:new", self._new_task)
        gazu.events.add_listener(
            self.event_client, "task:update", self._update_task
        )
        gazu.events.add_listener(
            self.event_client, "task:delete", self._delete_task
        )

    def start(self):
        gazu.events.run_client(self.event_client)

    # == Project ==
    def _new_project(self, data):
        """Create new project into OP DB."""

        # Use update process to avoid duplicating code
        self._update_project(data)

    def _update_project(self, data):
        """Update project into OP DB."""
        # Get project entity
        project = gazu.project.get_project(data["project_id"])
        project_name = project["name"]

        update_project = write_project_to_op(project, self.dbcon)

        # Write into DB
        if update_project:
            self.dbcon.Session["AVALON_PROJECT"] = project_name
            self.dbcon.bulk_write([update_project])

    def _delete_project(self, data):
        """Delete project."""

        project_name = get_kitsu_project_name(data["project_id"])

        # Delete project collection
        self.dbcon.database[project_name].drop()

    # == Asset ==

    def _new_asset(self, data):
        """Create new asset into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get gazu entity
        asset = gazu.asset.get_asset(data["asset_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(asset))

        # Update
        self._update_asset(data)

    def _update_asset(self, data):
        """Update asset into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        asset = gazu.asset.get_asset(data["asset_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[asset["project_id"]] = project_doc

        # Update
        update_op_result = update_op_assets(
            self.dbcon, project_doc, [asset], zou_ids_and_asset_docs
        )
        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_asset(self, data):
        """Delete asset of OP DB."""
        set_op_project(self.dbcon, data["project_id"])

        # Delete
        self.dbcon.delete_one(
            {"type": "asset", "data.zou.id": data["asset_id"]}
        )

    # == Episode ==
    def _new_episode(self, data):
        """Create new episode into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get gazu entity
        episode = gazu.shot.get_episode(data["episode_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(episode))

        # Update
        self._update_episode(data)

    def _update_episode(self, data):
        """Update episode into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        episode = gazu.shot.get_episode(data["episode_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[episode["project_id"]] = project_doc

        # Update
        update_op_result = update_op_assets(
            self.dbcon, project_doc, [episode], zou_ids_and_asset_docs
        )
        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_episode(self, data):
        """Delete shot of OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        print("delete episode")  # TODO check bugfix

        # Delete
        self.dbcon.delete_one(
            {"type": "asset", "data.zou.id": data["episode_id"]}
        )

    # == Sequence ==
    def _new_sequence(self, data):
        """Create new sequnce into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get gazu entity
        sequence = gazu.shot.get_sequence(data["sequence_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(sequence))

        # Update
        self._update_sequence(data)

    def _update_sequence(self, data):
        """Update sequence into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        sequence = gazu.shot.get_sequence(data["sequence_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[sequence["project_id"]] = project_doc

        # Update
        update_op_result = update_op_assets(
            self.dbcon, project_doc, [sequence], zou_ids_and_asset_docs
        )
        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_sequence(self, data):
        """Delete sequence of OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        print("delete sequence")  # TODO check bugfix

        # Delete
        self.dbcon.delete_one(
            {"type": "asset", "data.zou.id": data["sequence_id"]}
        )

    # == Shot ==
    def _new_shot(self, data):
        """Create new shot into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get gazu entity
        shot = gazu.shot.get_shot(data["shot_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(shot))

        # Update
        self._update_shot(data)

    def _update_shot(self, data):
        """Update shot into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        shot = gazu.shot.get_shot(data["shot_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[shot["project_id"]] = project_doc

        # Update
        update_op_result = update_op_assets(
            self.dbcon, project_doc, [shot], zou_ids_and_asset_docs
        )
        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_shot(self, data):
        """Delete shot of OP DB."""
        set_op_project(self.dbcon, data["project_id"])

        # Delete
        self.dbcon.delete_one(
            {"type": "asset", "data.zou.id": data["shot_id"]}
        )

    # == Task ==
    def _new_task(self, data):
        """Create new task into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()

        # Get gazu entity
        task = gazu.task.get_task(data["task_id"])

        # Find asset doc
        parent_name = task["entity"]["name"]

        asset_doc = get_asset_by_name(project_name, parent_name)

        # Update asset tasks with new one
        asset_tasks = asset_doc["data"].get("tasks")
        task_type_name = task["task_type"]["name"]
        asset_tasks[task_type_name] = {"type": task_type_name, "zou": task}
        self.dbcon.update_one(
            {"_id": asset_doc["_id"]}, {"$set": {"data.tasks": asset_tasks}}
        )

    def _update_task(self, data):
        """Update task into OP DB."""
        # TODO is it necessary?
        pass

    def _delete_task(self, data):
        """Delete task of OP DB."""

        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        # Find asset doc
        asset_docs = list(get_assets(project_name))
        for doc in asset_docs:
            # Match task
            for name, task in doc["data"]["tasks"].items():
                if task.get("zou") and data["task_id"] == task["zou"]["id"]:
                    # Pop task
                    asset_tasks = doc["data"].get("tasks", {})
                    asset_tasks.pop(name)

                    # Delete task in DB
                    self.dbcon.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"data.tasks": asset_tasks}},
                    )
                    return


def start_listeners(login: str, password: str):
    """Start listeners to keep OpenPype up-to-date with Kitsu.

    Args:
        login (str): Kitsu user login
        password (str): Kitsu user password
    """
    # Refresh token every week
    def refresh_token_every_week():
        print("Refreshing token...")
        gazu.refresh_token()
        threading.Timer(7 * 3600 * 24, refresh_token_every_week).start()

    refresh_token_every_week()

    # Connect to server
    listener = Listener(login, password)
    listener.start()
