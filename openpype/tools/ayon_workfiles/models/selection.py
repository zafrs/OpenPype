class SelectionModel(object):
    """Model handling selection changes.

    Triggering events:
    - "selection.folder.changed"
    - "selection.task.changed"
    - "workarea.selection.changed"
    - "selection.representation.changed"
    """

    event_source = "selection.model"

    def __init__(self, controller):
        self._controller = controller

        self._folder_id = None
        self._task_name = None
        self._task_id = None
        self._workfile_path = None
        self._representation_id = None

    def get_selected_folder_id(self):
        return self._folder_id

    def set_selected_folder(self, folder_id):
        if folder_id == self._folder_id:
            return

        self._folder_id = folder_id
        self._controller.emit_event(
            "selection.folder.changed",
            {"folder_id": folder_id},
            self.event_source
        )

    def get_selected_task_name(self):
        return self._task_name

    def get_selected_task_id(self):
        return self._task_id

    def set_selected_task(self, folder_id, task_id, task_name):
        if folder_id != self._folder_id:
            self.set_selected_folder(folder_id)

        if task_id == self._task_id:
            return

        self._task_name = task_name
        self._task_id = task_id
        self._controller.emit_event(
            "selection.task.changed",
            {
                "folder_id": folder_id,
                "task_name": task_name,
                "task_id": task_id
            },
            self.event_source
        )

    def get_selected_workfile_path(self):
        return self._workfile_path

    def set_selected_workfile_path(self, path):
        if path == self._workfile_path:
            return

        self._workfile_path = path
        self._controller.emit_event(
            "workarea.selection.changed",
            {
                "path": path,
                "folder_id": self._folder_id,
                "task_name": self._task_name,
                "task_id": self._task_id,
            },
            self.event_source
        )

    def get_selected_representation_id(self):
        return self._representation_id

    def set_selected_representation_id(self, representation_id):
        if representation_id == self._representation_id:
            return
        self._representation_id = representation_id
        self._controller.emit_event(
            "selection.representation.changed",
            {"representation_id": representation_id},
            self.event_source
        )
