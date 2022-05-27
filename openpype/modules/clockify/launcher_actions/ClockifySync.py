from openpype_modules.clockify.clockify_api import ClockifyAPI
from openpype.api import Logger
from openpype.pipeline import (
    legacy_io,
    LauncherAction,
)

log = Logger.get_logger(__name__)


class ClockifySync(LauncherAction):

    name = "sync_to_clockify"
    label = "Sync to Clockify"
    icon = "clockify_white_icon"
    order = 500
    clockapi = ClockifyAPI()
    have_permissions = clockapi.validate_workspace_perm()

    def is_compatible(self, session):
        """Return whether the action is compatible with the session"""
        return self.have_permissions

    def process(self, session, **kwargs):
        project_name = session.get('AVALON_PROJECT', None)

        projects_to_sync = []
        if project_name.strip() == '' or project_name is None:
            for project in legacy_io.projects():
                projects_to_sync.append(project)
        else:
            project = legacy_io.find_one({'type': 'project'})
            projects_to_sync.append(project)

        projects_info = {}
        for project in projects_to_sync:
            task_types = project['config']['tasks'].keys()
            projects_info[project['name']] = task_types

        clockify_projects = self.clockapi.get_projects()
        for project_name, task_types in projects_info.items():
            if project_name not in clockify_projects:
                response = self.clockapi.add_project(project_name)
                if 'id' not in response:
                    self.log.error('Project {} can\'t be created'.format(
                        project_name
                    ))
                    continue
                project_id = response['id']
            else:
                project_id = clockify_projects[project_name]

            clockify_workspace_tags = self.clockapi.get_tags()
            for task_type in task_types:
                if task_type not in clockify_workspace_tags:
                    response = self.clockapi.add_tag(task_type)
                    if 'id' not in response:
                        self.log.error('Task {} can\'t be created'.format(
                            task_type
                        ))
                        continue
