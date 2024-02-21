module.exports = {
    artist: [
        {
            type: "category",
            collapsed: false,
            label: "General",
            items: [
                "artist_getting_started",
                "artist_concepts",
                "artist_publish",
                {
                    type: "category",
                    collapsed: true,
                    label: "Tools",
                    link: {type: 'doc', id: 'artist_tools'},
                    items: [
                        "artist_tools_context_manager",
                        "artist_tools_creator",
                        "artist_tools_loader",
                        "artist_tools_library_loader",
                        "artist_tools_publisher",
                        "artist_tools_inventory",
                        "artist_tools_workfiles",
                        "artist_tools_look_assigner",
                        "artist_tools_subset_manager",
                        "artist_tools_sync_queue"
                    ],
                },
                "artist_install"
            ],
        },
        {
            type: "category",
            collapsed: false,
            label: "Integrations",
            items: [
                "artist_hosts_hiero",
                "artist_hosts_nuke_tut",
                {
                    type: "category",
                    label: "Maya",
                    items: [
                        "artist_hosts_maya",
                        "artist_hosts_maya_multiverse",
                        "artist_hosts_maya_yeti",
                        "artist_hosts_maya_xgen",
                        "artist_hosts_maya_arnold",
                        "artist_hosts_maya_vray",
                        "artist_hosts_maya_redshift",
                    ],
                },
                "artist_hosts_blender",
                "artist_hosts_3dsmax",
                "artist_hosts_harmony",
                "artist_hosts_houdini",
                "artist_hosts_aftereffects",
                "artist_hosts_resolve",
                "artist_hosts_photoshop",
                "artist_hosts_tvpaint",
                "artist_hosts_unreal",
                "artist_kitsu",
                {
                    type: "category",
                    label: "Ftrack",
                    items: [
                        "artist_ftrack",
                        "manager_ftrack",
                        "manager_ftrack_actions",
                    ],
                }
            ],
        },
    ],
    Admin: [
        "system_introduction",
        {
            type: "category",
            label: "Getting Started",
            items: [
                "admin_builds",
                "admin_distribute",
                "admin_use",
                "admin_openpype_commands",
            ],
        },
        {
            type: "category",
            label: "Configuration",
            items: [
                "admin_environment",
                "admin_settings",
                "admin_settings_system",
                "admin_settings_project_anatomy",
                {
                    type: "category",
                    label: "Project Settings",
                    items: [
                        "project_settings/settings_project_global",
                        "project_settings/settings_project_nuke",
                        "project_settings/settings_project_standalone"
                    ],
                },
            ],
        },
        {
            type: "category",
            label: "Modules",
            items: [
                "module_ftrack",
                "module_kitsu",
                "module_site_sync",
                "module_deadline",
                "module_royalrender",
                "module_clockify",
                "module_slack"
            ],
        },
        {
            type: "category",
            label: "Integrations",
            items: [
                "admin_hosts_blender",
                "admin_hosts_hiero",
                "admin_hosts_houdini",
                "admin_hosts_maya",
                "admin_hosts_nuke",
                "admin_hosts_resolve",
                "admin_hosts_harmony",
                "admin_hosts_photoshop",
                "admin_hosts_aftereffects",
                "admin_hosts_tvpaint"
            ],
        },
        "admin_releases",
        {
            type: "category",
            collapsed: false,
            label: "2.0 legacy docs",
            items: [
                {
                    type: "category",
                    label: "Deployment",
                    items: [
                        "pype2/admin_getting_started",
                        "pype2/admin_install",
                        "pype2/admin_config",
                        "pype2/admin_ftrack",
                        "pype2/admin_hosts",
                        "pype2/admin_pype_commands",
                        "pype2/admin_setup_troubleshooting",
                    ],
                },
                {
                    type: "category",
                    label: "Configuration",
                    items: [
                        "pype2/admin_presets_nukestudio",
                        "pype2/admin_presets_ftrack",
                        "pype2/admin_presets_maya",
                        "pype2/admin_presets_plugins",
                        "pype2/admin_presets_tools",
                    ],
                },
            ],
        },
    ],
    Dev: [
        "dev_introduction",
        "dev_requirements",
        "dev_build",
        "dev_testing",
        "dev_contribute",
        "dev_settings",
        {
            type: "category",
            label: "Hosts integrations",
            items: [
                "dev_host_implementation",
                "dev_publishing"
            ]
        },
        "dev_deadline",
        "dev_blender",
        "dev_colorspace"
    ]
};
