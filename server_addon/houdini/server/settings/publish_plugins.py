from pydantic import Field

from ayon_server.settings import BaseSettingsModel


# Creator Plugins
class CreatorModel(BaseSettingsModel):
    enabled: bool = Field(title="Enabled")
    default_variants: list[str] = Field(
        title="Default Products",
        default_factory=list,
    )


class CreateArnoldAssModel(BaseSettingsModel):
    enabled: bool = Field(title="Enabled")
    default_variants: list[str] = Field(
        title="Default Products",
        default_factory=list,
    )
    ext: str = Field(Title="Extension")


class CreatePluginsModel(BaseSettingsModel):
    CreateArnoldAss: CreateArnoldAssModel = Field(
        default_factory=CreateArnoldAssModel,
        title="Create Alembic Camera")
    CreateAlembicCamera: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create Alembic Camera")
    CreateCompositeSequence: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create Composite Sequence")
    CreatePointCache: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create Point Cache")
    CreateRedshiftROP: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create RedshiftROP")
    CreateRemotePublish: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create Remote Publish")
    CreateVDBCache: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create VDB Cache")
    CreateUSD: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create USD")
    CreateUSDModel: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create USD model")
    USDCreateShadingWorkspace: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create USD shading workspace")
    CreateUSDRender: CreatorModel = Field(
        default_factory=CreatorModel,
        title="Create USD render")


DEFAULT_HOUDINI_CREATE_SETTINGS = {
    "CreateArnoldAss": {
        "enabled": True,
        "default_variants": ["Main"],
        "ext": ".ass"
    },
    "CreateAlembicCamera": {
        "enabled": True,
        "default_variants": ["Main"]
    },
    "CreateCompositeSequence": {
        "enabled": True,
        "default_variants": ["Main"]
    },
    "CreatePointCache": {
        "enabled": True,
        "default_variants": ["Main"]
    },
    "CreateRedshiftROP": {
        "enabled": True,
        "default_variants": ["Main"]
    },
    "CreateRemotePublish": {
        "enabled": True,
        "default_variants": ["Main"]
    },
    "CreateVDBCache": {
        "enabled": True,
        "default_variants": ["Main"]
    },
    "CreateUSD": {
        "enabled": False,
        "default_variants": ["Main"]
    },
    "CreateUSDModel": {
        "enabled": False,
        "default_variants": ["Main"]
    },
    "USDCreateShadingWorkspace": {
        "enabled": False,
        "default_variants": ["Main"]
    },
    "CreateUSDRender": {
        "enabled": False,
        "default_variants": ["Main"]
    },
}


# Publish Plugins
class ValidateWorkfilePathsModel(BaseSettingsModel):
    enabled: bool = Field(title="Enabled")
    optional: bool = Field(title="Optional")
    node_types: list[str] = Field(
        default_factory=list,
        title="Node Types"
    )
    prohibited_vars: list[str] = Field(
        default_factory=list,
        title="Prohibited Variables"
    )


class BasicValidateModel(BaseSettingsModel):
    enabled: bool = Field(title="Enabled")
    optional: bool = Field(title="Optional")
    active: bool = Field(title="Active")


class PublishPluginsModel(BaseSettingsModel):
    ValidateWorkfilePaths: ValidateWorkfilePathsModel = Field(
        default_factory=ValidateWorkfilePathsModel,
        title="Validate workfile paths settings.")
    ValidateReviewColorspace: BasicValidateModel = Field(
        default_factory=BasicValidateModel,
        title="Validate Review Colorspace.")
    ValidateContainers: BasicValidateModel = Field(
        default_factory=BasicValidateModel,
        title="Validate Latest Containers.")


DEFAULT_HOUDINI_PUBLISH_SETTINGS = {
    "ValidateWorkfilePaths": {
        "enabled": True,
        "optional": True,
        "node_types": [
            "file",
            "alembic"
        ],
        "prohibited_vars": [
            "$HIP",
            "$JOB"
        ]
    },
    "ValidateReviewColorspace": {
        "enabled": True,
        "optional": True,
        "active": True
    },
    "ValidateContainers": {
        "enabled": True,
        "optional": True,
        "active": True
    }
}
