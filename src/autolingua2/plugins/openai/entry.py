from autolingua2.plugins.api import AiSetupOption, PluginContext, PluginContribution, UIContribution
from .openai import OpenAiProvider


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="openai",
            provider=OpenAiProvider(),
            ui=UIContribution(
                ai_setup=AiSetupOption(
                    provider_id="openai",
                    title="OpenAI",
                    description="OpenAI APIキーを使用してGPTモデルを利用します。",
                    mode="common",
                ),
            ),
        )
    )

