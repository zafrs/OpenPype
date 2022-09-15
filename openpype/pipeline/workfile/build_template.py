import os
from importlib import import_module
from openpype.lib import classes_from_module
from openpype.host import HostBase
from openpype.pipeline import registered_host

from .abstract_template_loader import (
    AbstractPlaceholder,
    AbstractTemplateLoader)

from .build_template_exceptions import (
    TemplateLoadingFailed,
    TemplateAlreadyImported,
    MissingHostTemplateModule,
    MissingTemplatePlaceholderClass,
    MissingTemplateLoaderClass
)

_module_path_format = 'openpype.hosts.{host}.api.template_loader'


def build_workfile_template(*args):
    template_loader = build_template_loader()
    try:
        template_loader.import_template(template_loader.template_path)
    except TemplateAlreadyImported as err:
        template_loader.template_already_imported(err)
    except TemplateLoadingFailed as err:
        template_loader.template_loading_failed(err)
    else:
        template_loader.populate_template()


def update_workfile_template(*args):
    template_loader = build_template_loader()
    template_loader.update_missing_containers()


def build_template_loader():
    # TODO refactor to use advantage of 'HostBase' and don't import dynamically
    #   - hosts should have methods that gives option to return builders
    host = registered_host()
    if isinstance(host, HostBase):
        host_name = host.name
    else:
        host_name = os.environ.get("AVALON_APP")
        if not host_name:
            host_name = host.__name__.split(".")[-2]

    module_path = _module_path_format.format(host=host_name)
    module = import_module(module_path)
    if not module:
        raise MissingHostTemplateModule(
            "No template loader found for host {}".format(host_name))

    template_loader_class = classes_from_module(
        AbstractTemplateLoader,
        module
    )
    template_placeholder_class = classes_from_module(
        AbstractPlaceholder,
        module
    )

    if not template_loader_class:
        raise MissingTemplateLoaderClass()
    template_loader_class = template_loader_class[0]

    if not template_placeholder_class:
        raise MissingTemplatePlaceholderClass()
    template_placeholder_class = template_placeholder_class[0]
    return template_loader_class(template_placeholder_class)
