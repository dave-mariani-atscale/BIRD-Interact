import os

model_config = {
    "openrouter": {
        "api_key": "Your OpenRouter API Key",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "openai": {
        "api_key": "Your OpenAI API Key",
        "base_url": "Your Base URL",
    },
    "anthropic": {
        "api_key": os.environ.get("ANTHROPIC_API_KEY", "Your Anthropic API Key"),
    },
}