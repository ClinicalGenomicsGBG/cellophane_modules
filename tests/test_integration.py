from pathlib import Path

from cellophane.src.testing import parametrize_from_yaml

INTEGRATION = Path(__file__).parent / "integration"

class Test_integration:
    @staticmethod
    @parametrize_from_yaml(INTEGRATION.glob("*.yaml"))
    def test_integration(definition: Path, run_definition):
        run_definition(definition)
