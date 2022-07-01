import json
import datetime

from bson.objectid import ObjectId

from aiohttp.web_response import Response

from openpype.client import (
    get_projects,
    get_project,
    get_assets,
    get_asset_by_name,
)
from openpype_modules.webserver.base_routes import RestApiEndpoint


class _RestApiEndpoint(RestApiEndpoint):
    def __init__(self, resource):
        self.resource = resource
        super(_RestApiEndpoint, self).__init__()


class AvalonProjectsEndpoint(_RestApiEndpoint):
    async def get(self) -> Response:
        output = [
            project_doc
            for project_doc in get_projects()
        ]
        return Response(
            status=200,
            body=self.resource.encode(output),
            content_type="application/json"
        )


class AvalonProjectEndpoint(_RestApiEndpoint):
    async def get(self, project_name) -> Response:
        project_doc = get_project(project_name)
        if project_doc:
            return Response(
                status=200,
                body=self.resource.encode(project_doc),
                content_type="application/json"
            )
        return Response(
            status=404,
            reason="Project name {} not found".format(project_name)
        )


class AvalonAssetsEndpoint(_RestApiEndpoint):
    async def get(self, project_name) -> Response:
        asset_docs = list(get_assets(project_name))
        return Response(
            status=200,
            body=self.resource.encode(asset_docs),
            content_type="application/json"
        )


class AvalonAssetEndpoint(_RestApiEndpoint):
    async def get(self, project_name, asset_name) -> Response:
        asset_doc = get_asset_by_name(project_name, asset_name)
        if asset_doc:
            return Response(
                status=200,
                body=self.resource.encode(asset_doc),
                content_type="application/json"
            )
        return Response(
            status=404,
            reason="Asset name {} not found in project {}".format(
                asset_name, project_name
            )
        )


class AvalonRestApiResource:
    def __init__(self, avalon_module, server_manager):
        self.module = avalon_module
        self.server_manager = server_manager

        self.prefix = "/avalon"

        self.endpoint_defs = (
            (
                "GET",
                "/projects",
                AvalonProjectsEndpoint(self)
            ),
            (
                "GET",
                "/projects/{project_name}",
                AvalonProjectEndpoint(self)
            ),
            (
                "GET",
                "/projects/{project_name}/assets",
                AvalonAssetsEndpoint(self)
            ),
            (
                "GET",
                "/projects/{project_name}/assets/{asset_name}",
                AvalonAssetEndpoint(self)
            )
        )

        self.register()

    def register(self):
        for methods, url, endpoint in self.endpoint_defs:
            final_url = self.prefix + url
            self.server_manager.add_route(
                methods, final_url, endpoint.dispatch
            )

    @staticmethod
    def json_dump_handler(value):
        if isinstance(value, datetime.datetime):
            return value.isoformat()
        if isinstance(value, ObjectId):
            return str(value)
        raise TypeError(value)

    @classmethod
    def encode(cls, data):
        return json.dumps(
            data,
            indent=4,
            default=cls.json_dump_handler
        ).encode("utf-8")
