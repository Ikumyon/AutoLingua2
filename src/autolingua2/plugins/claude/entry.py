from autolingua2.plugins.api import AiSetupOption, PluginContext, PluginContribution, UIContribution
from .claude import ClaudeProvider


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="claude",
            provider=ClaudeProvider(),
            ui=UIContribution(
                ai_setup=AiSetupOption(
                    provider_id="claude",
                    title="Anthropic Claude",
                    description="Anthropic APIキーを使用してClaudeモデルを利用します。",
                    mode="common",
                ),
            ),
        )
    )

