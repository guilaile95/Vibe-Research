"""Same wire golden as actual frontend transports; schemas stay extra=forbid."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from company_research_router import ModelIn as ResearchModel
from company_comparison_router import ModelIn as ComparisonModel


@pytest.mark.parametrize("model", [ResearchModel, ComparisonModel])
def test_client_generation_removed_before_strict_model_schema(model):
    golden = json.loads((Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/credential-model-wire.json").read_text())
    assert model.model_validate(golden["llm"]).model_dump() == golden["llm"]
    for extra in [{"revision": "1"}, {"unknown": "must-not-be-silently-stripped"}]:
        with pytest.raises(ValidationError):
            model.model_validate({**golden["llm"], **extra})
