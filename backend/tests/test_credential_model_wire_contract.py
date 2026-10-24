"""Same wire golden as actual frontend transports; schemas stay extra=forbid."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from company_research_router import ModelIn as ResearchModel
from company_comparison_router import ModelIn as ComparisonModel


@pytest.mark.parametrize("model", [ResearchModel, ComparisonModel])
def test_generation_preserved_for_dispatch_schema(model):
    golden = json.loads((Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/credential-model-wire.json").read_text())
    assert model.model_validate(golden["llm"]).model_dump() == golden["llm"]
    for extra in [{"unknown": "must-not-be-silently-stripped"}]:
        with pytest.raises(ValidationError):
            model.model_validate({**golden["llm"], **extra})
