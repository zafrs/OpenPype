import os
import six
import pyblish.api
import copy
from datetime import datetime

from openpype.client import OpenPypeMongoConnection
from openpype.lib.plugin_tools import prepare_template_data


class IntegrateSlackAPI(pyblish.api.InstancePlugin):
    """ Send message notification to a channel.
        Triggers on instances with "slack" family, filled by
        'collect_slack_family'.
        Expects configured profile in
        Project settings > Slack > Publish plugins > Notification to Slack.
        If instance contains 'thumbnail' it uploads it. Bot must be present
        in the target channel.
        If instance contains 'review' it could upload (if configured) or place
        link with {review_filepath} placeholder.
        Message template can contain {} placeholders from anatomyData.
    """
    order = pyblish.api.IntegratorOrder + 0.499
    label = "Integrate Slack Api"
    families = ["slack"]

    optional = True

    def process(self, instance):
        thumbnail_path = self._get_thumbnail_path(instance)
        review_path = self._get_review_path(instance)

        publish_files = set()
        for message_profile in instance.data["slack_channel_message_profiles"]:
            message = self._get_filled_message(message_profile["message"],
                                               instance,
                                               review_path)
            self.log.debug("message:: {}".format(message))
            if not message:
                return

            if message_profile["upload_thumbnail"] and thumbnail_path:
                publish_files.add(thumbnail_path)

            if message_profile["upload_review"] and review_path:
                message, publish_files = self._handle_review_upload(
                    message, message_profile, publish_files, review_path)

            project = instance.context.data["anatomyData"]["project"]["code"]
            for channel in message_profile["channels"]:
                if six.PY2:
                    msg_id, file_ids = \
                        self._python2_call(instance.data["slack_token"],
                                           channel,
                                           message,
                                           publish_files)
                else:
                    msg_id, file_ids = \
                        self._python3_call(instance.data["slack_token"],
                                           channel,
                                           message,
                                           publish_files)

                if not msg_id:
                    return

                msg = {
                    "type": "slack",
                    "msg_id": msg_id,
                    "file_ids": file_ids,
                    "project": project,
                    "created_dt": datetime.now()
                }
                mongo_client = OpenPypeMongoConnection.get_mongo_client()
                database_name = os.environ["OPENPYPE_DATABASE_NAME"]
                dbcon = mongo_client[database_name]["notification_messages"]
                dbcon.insert_one(msg)

    def _handle_review_upload(self, message, message_profile, publish_files,
                              review_path):
        """Check if uploaded file is not too large"""
        review_file_size_MB = os.path.getsize(review_path) / 1024 / 1024
        file_limit = message_profile.get("review_upload_limit", 50)
        if review_file_size_MB > file_limit:
            message += "\nReview upload omitted because of file size."
            if review_path not in message:
                message += "\nFile located at: {}".format(review_path)
        else:
            publish_files.add(review_path)
        return message, publish_files

    def _get_filled_message(self, message_templ, instance, review_path=None):
        """Use message_templ and data from instance to get message content.

        Reviews might be large, so allow only adding link to message instead of
        uploading only.
        """

        fill_data = copy.deepcopy(instance.context.data["anatomyData"])

        username = fill_data.get("user")
        fill_pairs = [
            ("asset", instance.data.get("asset", fill_data.get("asset"))),
            ("subset", instance.data.get("subset", fill_data.get("subset"))),
            ("user", username),
            ("username", username),
            ("app", instance.data.get("app", fill_data.get("app"))),
            ("family", instance.data.get("family", fill_data.get("family"))),
            ("version", str(instance.data.get("version",
                                              fill_data.get("version"))))
        ]
        if review_path:
            fill_pairs.append(("review_filepath", review_path))

        task_data = (
                copy.deepcopy(instance.data.get("anatomyData", {})).get("task")
                or fill_data.get("task")
        )
        if not isinstance(task_data, dict):
            # fallback for legacy - if task_data is only task name
            task_data["name"] = task_data
        if task_data:
            if (
                "{task}" in message_templ
                or "{Task}" in message_templ
                or "{TASK}" in message_templ
            ):
                fill_pairs.append(("task", task_data["name"]))

            else:
                for key, value in task_data.items():
                    fill_key = "task[{}]".format(key)
                    fill_pairs.append((fill_key, value))

        self.log.debug("fill_pairs ::{}".format(fill_pairs))
        multiple_case_variants = prepare_template_data(fill_pairs)
        fill_data.update(multiple_case_variants)

        message = None
        try:
            message = message_templ.format(**fill_data)
        except Exception:
            self.log.warning(
                "Some keys are missing in {}".format(message_templ),
                exc_info=True)

        return message

    def _get_thumbnail_path(self, instance):
        """Returns abs url for thumbnail if present in instance repres"""
        thumbnail_path = None
        for repre in instance.data.get("representations", []):
            if repre.get('thumbnail') or "thumbnail" in repre.get('tags', []):
                repre_thumbnail_path = (
                    repre.get("published_path") or
                    os.path.join(repre["stagingDir"], repre["files"])
                )
                if os.path.exists(repre_thumbnail_path):
                    thumbnail_path = repre_thumbnail_path
                break
        return thumbnail_path

    def _get_review_path(self, instance):
        """Returns abs url for review if present in instance repres"""
        published_path = None
        for repre in instance.data.get("representations", []):
            tags = repre.get('tags', [])
            if (repre.get("review")
                    or "review" in tags
                    or "burnin" in tags):
                if os.path.exists(repre["published_path"]):
                    published_path = repre["published_path"]
                if "burnin" in tags:  # burnin has precedence if exists
                    break
        return published_path

    def _python2_call(self, token, channel, message, publish_files):
        from slackclient import SlackClient
        try:
            client = SlackClient(token)
            attachment_str = "\n\n Attachment links: \n"
            file_ids = []
            for p_file in publish_files:
                with open(p_file, 'rb') as pf:
                    response = client.api_call(
                        "files.upload",
                        file=pf,
                        channel=channel,
                        title=os.path.basename(p_file)
                    )
                    if response.get("error"):
                        error_str = self._enrich_error(
                            str(response.get("error")),
                            channel)
                        self.log.warning(
                            "Error happened: {}".format(error_str))
                    else:
                        attachment_str += "\n<{}|{}>".format(
                            response["file"]["permalink"],
                            os.path.basename(p_file))
                        file_ids.append(response["file"]["id"])

            if publish_files:
                message += attachment_str

            response = client.api_call(
                "chat.postMessage",
                channel=channel,
                text=message
            )
            if response.get("error"):
                error_str = self._enrich_error(str(response.get("error")),
                                               channel)
                self.log.warning("Error happened: {}".format(error_str))
            else:
                return response["ts"], file_ids
        except Exception as e:
            # You will get a SlackApiError if "ok" is False
            error_str = self._enrich_error(str(e), channel)
            self.log.warning("Error happened: {}".format(error_str))

        return None, []

    def _python3_call(self, token, channel, message, publish_files):
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
        try:
            client = WebClient(token=token)
            attachment_str = "\n\n Attachment links: \n"
            file_ids = []
            for published_file in publish_files:
                response = client.files_upload(
                    file=published_file,
                    filename=os.path.basename(published_file))
                attachment_str += "\n<{}|{}>".format(
                    response["file"]["permalink"],
                    os.path.basename(published_file))
                file_ids.append(response["file"]["id"])

            if publish_files:
                message += attachment_str

            response = client.chat_postMessage(
                channel=channel,
                text=message
            )
            return response.data["ts"], file_ids
        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            error_str = self._enrich_error(str(e.response["error"]), channel)
            self.log.warning("Error happened {}".format(error_str))
        except Exception as e:
            error_str = self._enrich_error(str(e), channel)
            self.log.warning("Not SlackAPI error", exc_info=True)

        return None, []

    def _enrich_error(self, error_str, channel):
        """Enhance known errors with more helpful notations."""
        if 'not_in_channel' in error_str:
            # there is no file.write.public scope, app must be explicitly in
            # the channel
            msg = " - application must added to channel '{}'.".format(channel)
            error_str += msg + " Ask Slack admin."
        return error_str
