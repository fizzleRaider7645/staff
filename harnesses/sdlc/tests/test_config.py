from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdlc.config import SDLCConfig, MODEL_TIERS, PHASE_TIERS, PROVIDERS


class TestResolveModel:
    def test_cli_override_wins(self, config: SDLCConfig):
        result = config.resolve_model("plan", cli_override="custom-model")
        assert result == "custom-model"

    def test_per_phase_config_over_tier(self):
        config = SDLCConfig(provider="anthropic", models={"plan": "claude-sonnet-5"})
        result = config.resolve_model("plan")
        assert result == "claude-sonnet-5"

    def test_tier_fallback_anthropic(self):
        config = SDLCConfig(provider="anthropic")
        assert config.resolve_model("plan") == "claude-opus-5"
        assert config.resolve_model("tasks") == "claude-sonnet-5"
        assert config.resolve_model("verify") == "claude-haiku-4-5"

    def test_tier_fallback_openai(self):
        config = SDLCConfig(provider="openai")
        assert config.resolve_model("plan") == "gpt-4o"
        assert config.resolve_model("verify") == "gpt-4o-mini"

    def test_tier_fallback_google(self):
        config = SDLCConfig(provider="google")
        assert config.resolve_model("plan") == "gemini-2.5-pro"
        assert config.resolve_model("verify") == "gemini-2.5-flash"

    def test_cli_override_beats_per_phase(self):
        config = SDLCConfig(models={"plan": "configured-model"})
        result = config.resolve_model("plan", cli_override="override-model")
        assert result == "override-model"

    def test_all_phases_resolve_for_all_providers(self):
        for provider in PROVIDERS:
            config = SDLCConfig(provider=provider)
            for phase in PHASE_TIERS:
                model = config.resolve_model(phase)
                assert isinstance(model, str) and len(model) > 0

    def test_unknown_phase_raises(self, config: SDLCConfig):
        with pytest.raises(KeyError):
            config.resolve_model("nonexistent")


class TestLoadSave:
    def test_save_and_load_roundtrip(self, sdlc_dir: Path):
        original = SDLCConfig(
            provider="openai",
            models={"plan": "gpt-4o"},
            claude_code_path="/usr/local/bin/claude",
        )
        original.save(sdlc_dir)

        loaded = SDLCConfig.load(sdlc_dir)
        assert loaded.provider == "openai"
        assert loaded.models == {"plan": "gpt-4o"}
        assert loaded.claude_code_path == "/usr/local/bin/claude"

    def test_load_missing_file_returns_defaults(self, sdlc_dir: Path):
        config = SDLCConfig.load(sdlc_dir)
        assert config.provider == "anthropic"
        assert config.models == {}
        assert config.claude_code_path == "claude"

    def test_load_ignores_extra_keys(self, sdlc_dir: Path):
        data = {
            "provider": "google",
            "models": {},
            "claude_code_path": "claude",
            "project_context": {"include_file_tree": True, "max_context_files": 20},
            "unknown_key": "should be ignored",
            "another_extra": 42,
        }
        (sdlc_dir / "config.json").write_text(json.dumps(data))

        config = SDLCConfig.load(sdlc_dir)
        assert config.provider == "google"
        assert not hasattr(config, "unknown_key")

    def test_save_writes_valid_json(self, sdlc_dir: Path):
        config = SDLCConfig()
        config.save(sdlc_dir)

        raw = (sdlc_dir / "config.json").read_text()
        data = json.loads(raw)
        assert "provider" in data
        assert "models" in data

    def test_project_context_default(self):
        config = SDLCConfig()
        assert config.project_context["include_file_tree"] is True
        assert config.project_context["max_context_files"] == 20

    def test_project_context_roundtrip(self, sdlc_dir: Path):
        original = SDLCConfig(project_context={
            "include_file_tree": False,
            "max_context_files": 50,
        })
        original.save(sdlc_dir)

        loaded = SDLCConfig.load(sdlc_dir)
        assert loaded.project_context["include_file_tree"] is False
        assert loaded.project_context["max_context_files"] == 50


class TestDefaults:
    def test_default_provider(self):
        assert SDLCConfig().provider == "anthropic"

    def test_default_models_empty(self):
        assert SDLCConfig().models == {}

    def test_all_providers_in_model_tiers(self):
        for provider in PROVIDERS:
            assert provider in MODEL_TIERS

    def test_all_phases_have_tiers(self):
        from sdlc.state import PHASE_ORDER
        for phase in PHASE_ORDER:
            assert phase in PHASE_TIERS

    def test_all_tiers_exist_in_all_providers(self):
        tiers_used = set(PHASE_TIERS.values())
        for provider in PROVIDERS:
            for tier in tiers_used:
                assert tier in MODEL_TIERS[provider], f"{provider} missing tier {tier}"
