import os
import sys
import platform
import psutil
from avalon import lib as avalonlib
import acre
import ftrack_api
from pype import api as pype
from pype import lib as pypelib
from .avalon_sync import get_config_data
from .ftrack_base_handler import BaseHandler


class AppAction(BaseHandler):
    '''Custom Action base class

    <label> - a descriptive string identifing your action.
    <varaint>   - To group actions together, give them the same
                  label and specify a unique variant per action.
    <identifier>  - a unique identifier for app.
    <description>   - a verbose descriptive text for you action
    <icon>  - icon in ftrack

    <script path> - if is set, only one app will be allowed to run if script is
        set to script which launches app
    '''

    type = 'Application'

    def __init__(
        self, session, label, name, executable,
        variant=None, icon=None, description=None,
        preactions=None, once_run_data=None
    ):
        super().__init__(session)
        '''Expects a ftrack_api.Session instance'''

        if label is None:
            raise ValueError('Action missing label.')
        elif name is None:
            raise ValueError('Action missing identifier.')
        elif executable is None:
            raise ValueError('Action missing executable.')

        self.label = label
        self.identifier = name
        self.executable = executable
        self.variant = variant
        self.icon = icon
        self.description = description
        self.preactions = preactions
        self.once_run_data = once_run_data

    def register(self):
        '''Registers the action, subscribing the discover and launch topics.'''

        discovery_subscription = (
            'topic=ftrack.action.discover and source.user.username={0}'
        ).format(self.session.api_user)

        self.session.event_hub.subscribe(
            discovery_subscription,
            self._discover,
            priority=self.priority
        )

        launch_subscription = (
            'topic=ftrack.action.launch'
            ' and data.actionIdentifier={0}'
            ' and source.user.username={1}'
        ).format(
            self.identifier,
            self.session.api_user
        )
        self.session.event_hub.subscribe(
            launch_subscription,
            self._launch
        )

    def discover(self, session, entities, event):
        '''Return true if we can handle the selected entities.

        *session* is a `ftrack_api.Session` instance

        *entities* is a list of tuples each containing the entity type and
        the entity id. If the entity is a hierarchical you will always get
        the entity type TypedContext, once retrieved through a get operation
        you will have the "real" entity type ie. example Shot, Sequence
        or Asset Build.

        *event* the unmodified original event

        '''

        if (
            len(entities) != 1 or
            entities[0].entity_type.lower() != 'task'
        ):
            return False

        ft_project = entities[0]['project']

        database = pypelib.get_avalon_database()
        project_name = ft_project['full_name']
        avalon_project = database[project_name].find_one({
            "type": "project"
        })

        if avalon_project is None:
            return False
        else:
            apps = [app['name'] for app in avalon_project['config'].get(
                'apps', []
            )]

            if self.identifier not in apps:
                return False

        return True

    def _launch(self, event):
        args = self._translate_event(
            self.session, event
        )

        preactions_launched = self._handle_preactions(
            self.session, event
        )
        if preactions_launched is False:
            return

        if self._check_is_running():
            response = {
                'success': False,
                'message': '"{0}" is already running'.format(self.label)
            }
        else:
            response = self.launch(
                self.session, *args
            )

        return self._handle_result(
            self.session, response, *args
        )

    def _check_is_running(self):
        data = self.once_run_data
        if data is None:
            return False

        process_name = data.get('process_name', None)
        script_path = data.get('script_path', None)

        if process_name is None and script_path is None:
            return False
        elif process_name is None:
            procs = [p for p in psutil.process_iter() if (
                'python.exe' in p.name() and
                script_path in p.cmdline()
            )]
        elif script_path is None:
            procs = [p for p in psutil.process_iter() if (
                process_name in p.name()
            )]
        else:
            procs = [p for p in psutil.process_iter() if (
                process_name in p.name() and
                script_path in p.cmdline()
            )]

        if len(procs) > 0:
            return True
        return False

    def _handle_preactions(self, session, event):
        # If no selection
        selection = event.get('data', {}).get('selection', None)
        if (selection is None):
            return False
        # If preactions are not set
        if (
            not hasattr(self, 'preactions') and
            self.preactions is None and
            len(self.preactions) < 1
        ):
            return True
        # If preactions were already started
        if event['data'].get('preactions_launched', None) is True:
            return True

        # Launch preactions
        for preaction in self.preactions:
            event = ftrack_api.event.base.Event(
                topic='ftrack.action.launch',
                data=dict(
                    actionIdentifier=preaction,
                    selection=selection
                ),
                source=dict(
                    user=dict(username=session.api_user)
                )
            )
            session.event_hub.publish(event, on_error='ignore')
        # Relaunch this action
        event = ftrack_api.event.base.Event(
            topic='ftrack.action.launch',
            data=dict(
                actionIdentifier=self.identifier,
                selection=selection,
                preactions_launched=True
            ),
            source=dict(
                user=dict(username=session.api_user)
            )
        )
        session.event_hub.publish(event, on_error='ignore')

        return False

    def launch(self, session, entities, event):
        '''Callback method for the custom action.

        return either a bool ( True if successful or False if the action failed )
        or a dictionary with they keys `message` and `success`, the message should be a
        string and will be displayed as feedback to the user, success should be a bool,
        True if successful or False if the action failed.

        *session* is a `ftrack_api.Session` instance

        *entities* is a list of tuples each containing the entity type and the entity id.
        If the entity is a hierarchical you will always get the entity
        type TypedContext, once retrieved through a get operation you
        will have the "real" entity type ie. example Shot, Sequence
        or Asset Build.

        *event* the unmodified original event

        '''

        entity = entities[0]
        project_name = entity['project']['full_name']

        # Validate Clockify settings if Clockify is required
        clockify_timer = os.environ.get('CLOCKIFY_WORKSPACE', None)
        if clockify_timer is not None:
            from pype.clockify import ClockifyAPI
            clockapi = ClockifyAPI()
            if clockapi.verify_api() is False:
                title = 'Launch message'
                header = '# You Can\'t launch **any Application**'
                message = (
                    '<p>You don\'t have set Clockify API'
                    ' key in Clockify settings</p>'
                )
                items = [
                    {'type': 'label', 'value': header},
                    {'type': 'label', 'value': message}
                ]
                self.show_interface(event, items, title)
                return False

        database = pypelib.get_avalon_database()

        # Get current environments
        env_list = [
            'AVALON_PROJECT',
            'AVALON_SILO',
            'AVALON_ASSET',
            'AVALON_TASK',
            'AVALON_APP',
            'AVALON_APP_NAME'
        ]
        env_origin = {}
        for env in env_list:
            env_origin[env] = os.environ.get(env, None)

        # set environments for Avalon
        os.environ["AVALON_PROJECT"] = project_name
        os.environ["AVALON_SILO"] = entity['ancestors'][0]['name']
        os.environ["AVALON_ASSET"] = entity['parent']['name']
        os.environ["AVALON_TASK"] = entity['name']
        os.environ["AVALON_APP"] = self.identifier.split("_")[0]
        os.environ["AVALON_APP_NAME"] = self.identifier

        anatomy = pype.Anatomy
        hierarchy = ""
        parents = database[project_name].find_one({
            "type": 'asset',
            "name": entity['parent']['name']
        })['data']['parents']

        if parents:
            hierarchy = os.path.join(*parents)

        data = {"project": {"name": entity['project']['full_name'],
                            "code": entity['project']['name']},
                "task": entity['name'],
                "asset": entity['parent']['name'],
                "hierarchy": hierarchy}
        try:
            anatomy = anatomy.format(data)
        except Exception as e:
            self.log.error(
                "{0} Error in anatomy.format: {1}".format(__name__, e)
            )
        os.environ["AVALON_WORKDIR"] = os.path.join(
            anatomy.work.root, anatomy.work.folder
        )

        # collect all parents from the task
        parents = []
        for item in entity['link']:
            parents.append(session.get(item['type'], item['id']))

        # collect all the 'environment' attributes from parents
        tools_attr = [os.environ["AVALON_APP"], os.environ["AVALON_APP_NAME"]]
        for parent in reversed(parents):
            # check if the attribute is empty, if not use it
            if parent['custom_attributes']['tools_env']:
                tools_attr.extend(parent['custom_attributes']['tools_env'])
                break

        tools_env = acre.get_tools(tools_attr)
        env = acre.compute(tools_env)
        env = acre.merge(env, current_env=dict(os.environ))

        # Get path to execute
        st_temp_path = os.environ['PYPE_STUDIO_TEMPLATES']
        os_plat = platform.system().lower()

        # Path to folder with launchers
        path = os.path.join(st_temp_path, 'bin', os_plat)
        # Full path to executable launcher
        execfile = None

        if sys.platform == "win32":

            for ext in os.environ["PATHEXT"].split(os.pathsep):
                fpath = os.path.join(path.strip('"'), self.executable + ext)
                if os.path.isfile(fpath) and os.access(fpath, os.X_OK):
                    execfile = fpath
                    break
                pass

            # Run SW if was found executable
            if execfile is not None:
                avalonlib.launch(executable=execfile, args=[], environment=env)
            else:
                return {
                    'success': False,
                    'message': "We didn't found launcher for {0}"
                    .format(self.label)
                    }
                pass

        if sys.platform.startswith('linux'):
            execfile = os.path.join(path.strip('"'), self.executable)
            if os.path.isfile(execfile):
                try:
                    fp = open(execfile)
                except PermissionError as p:
                    self.log.error('Access denied on {0} - {1}'.format(
                        execfile, p))
                    return {
                        'success': False,
                        'message': "Access denied on launcher - {}".format(
                            execfile)
                    }
                fp.close()
                # check executable permission
                if not os.access(execfile, os.X_OK):
                    self.log.error('No executable permission on {}'.format(
                        execfile))
                    return {
                        'success': False,
                        'message': "No executable permission - {}".format(
                            execfile)
                        }
                    pass
            else:
                self.log.error('Launcher doesn\'t exist - {}'.format(
                    execfile))
                return {
                    'success': False,
                    'message': "Launcher doesn't exist - {}".format(execfile)
                }
                pass
            # Run SW if was found executable
            if execfile is not None:
                avalonlib.launch(
                    '/usr/bin/env', args=['bash', execfile], environment=env
                )
            else:
                return {
                    'success': False,
                    'message': "We didn't found launcher for {0}"
                    .format(self.label)
                    }
                pass

        # RUN TIMER IN FTRACK
        username = event['source']['user']['username']
        user_query = 'User where username is "{}"'.format(username)
        user = session.query(user_query).one()
        task = session.query('Task where id is {}'.format(entity['id'])).one()
        self.log.info('Starting timer for task: ' + task['name'])
        user.start_timer(task, force=True)

        # RUN TIMER IN Clockify
        if clockify_timer is not None:
            task_type = task['type']['name']
            project_name = task['project']['full_name']

            def get_parents(entity):
                output = []
                if entity.entity_type.lower() == 'project':
                    return output
                output.extend(get_parents(entity['parent']))
                output.append(entity['name'])

                return output

            desc_items = get_parents(task['parent'])
            desc_items.append(task['name'])
            description = '/'.join(desc_items)

            project_id = clockapi.get_project_id(project_name)
            tag_ids = []
            tag_ids.append(clockapi.get_tag_id(task_type))
            clockapi.start_time_entry(
                description, project_id, tag_ids=tag_ids
            )

        # Change status of task to In progress
        config = get_config_data()

        if 'status_update' in config:
            statuses = config['status_update']

            actual_status = entity['status']['name'].lower()
            next_status_name = None
            for key, value in statuses.items():
                if actual_status in value or '_any_' in value:
                    if key != '_ignore_':
                        next_status_name = key
                    break

            if next_status_name is not None:
                try:
                    query = 'Status where name is "{}"'.format(
                        next_status_name
                    )
                    status = session.query(query).one()
                    entity['status'] = status
                    session.commit()
                except Exception:
                    msg = (
                        'Status "{}" in config wasn\'t found on Ftrack'
                    ).format(next_status_name)
                    self.log.warning(msg)

        # Set origin avalon environments
        for key, value in env_origin.items():
            os.environ[key] = value

        return {
            'success': True,
            'message': "Launching {0}".format(self.label)
        }
