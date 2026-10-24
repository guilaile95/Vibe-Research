"""Supported provider identities shared by Settings-backed model dispatch."""
API_PROVIDERS = frozenset({"deepseek", "silicon", "openai", "minimax", "openrouter", "groq", "together", "mimo", "openai-compatible"})
CLI_PROVIDER = "cli-codex"

def provider_kind(provider):
    if provider == CLI_PROVIDER:
        return "codex"
    if provider in API_PROVIDERS:
        return "api"
    raise ValueError("UNSUPPORTED_AI_PROVIDER")

def execution_identity(cfg):
    if cfg.get("provider") == CLI_PROVIDER:
        # Legacy UI labels never selected a model. Do not silently change that
        # paid execution contract by turning a label into an SDK model option.
        return {"runtimeFamily": "codex-subscription", "requestedModel": None,
                "resolvedModel": None, "model": "unknown/default"}
    return {"runtimeFamily": "openai-compatible", "requestedModel": cfg.get("model"),
            "resolvedModel": None, "model": cfg.get("model")}


def config_cache_identity(cfg):
    """Non-secret generation/endpoint identity; never persist a key or raw URL."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps({key: cfg.get(key) for key in
        ("provider", "model", "baseURL", "revision")}, sort_keys=True).encode()).hexdigest()
