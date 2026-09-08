from chimerax.core.toolshed import BundleAPI

__version__ = "0.1.3"


class _MolComposeBundleAPI(BundleAPI):
    api_version = 1

    @staticmethod
    def register_command(bundle_info, command_info, logger):
        from .commands import register_command

        register_command(command_info.name, logger)

    @staticmethod
    def start_tool(session, bundle_info, tool_info):
        if tool_info.name != "MolCompose":
            raise ValueError(f"Unknown MolCompose tool: {tool_info.name}")
        from .ui.tool import MolComposeTool

        return MolComposeTool(session, tool_info.name)


bundle_api = _MolComposeBundleAPI()
