from langchain.chat_models import init_chat_model
from langchain_anthropic.chat_models import ChatAnthropic

OPENAI_RESPONSES_WS_BASE_URL = "wss://api.openai.com/v1"


class NoCacheAnthropic(ChatAnthropic):
    """ChatAnthropic wrapper that strips cache_control from API payloads.

    Vertex AI does not support Anthropic prompt caching, but the deepagents
    middleware unconditionally injects cache_control. This subclass removes
    it before the request reaches the API.
    """

    def _get_request_payload(self, *args, **kwargs):
        payload = super()._get_request_payload(*args, **kwargs)
        # Strip top-level cache_control (present when system is a plain string
        # and the middleware couldn't attach it to a message block)
        payload.pop("cache_control", None)
        # Strip cache_control from message content blocks
        for msg in payload.get("messages", []):
            if isinstance(msg, dict):
                msg.pop("cache_control", None)
                for content_block in msg.get("content", []):
                    if isinstance(content_block, dict):
                        content_block.pop("cache_control", None)
        # Strip from system (when system is a list of blocks)
        system = payload.get("system")
        if isinstance(system, list):
            for block in system:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
        return payload


def make_model(model_id: str, **kwargs: dict):
    model_kwargs = kwargs.copy()

    if model_id.startswith("openai:"):
        model_kwargs["base_url"] = OPENAI_RESPONSES_WS_BASE_URL
        model_kwargs["use_responses_api"] = True
        return init_chat_model(model=model_id, **model_kwargs)

    if model_id.startswith("anthropic:"):
        # Use NoCacheAnthropic for Vertex-routed models via LiteLLM
        model_name = model_id.split(":", 1)[1]
        return NoCacheAnthropic(model=model_name, **model_kwargs)

    return init_chat_model(model=model_id, **model_kwargs)
