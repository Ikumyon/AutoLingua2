from autolingua2.plugins.contracts import TextTranslator


class ExampleProvider:
    display_name = "Example"
    api_key_env = "EXAMPLE_API_KEY"

    def __init__(self, provider_id: str) -> None:
        self.id = provider_id

    def create(self, api_key: str, model: str) -> TextTranslator:
        return ExampleTranslator()


class ExampleTranslator:
    def translate(self, text: str, source_language: str, target_language: str) -> str:
        return text
