import time
import random
import structlog
from typing import Dict, Any
from src.domain.models.base import BaseModelRunner

logger = structlog.get_logger()


class MockModelRunner(BaseModelRunner):
    """
    A mock model that simulates work by sleeping.

    Supported Parameters:
    - duration (float): Seconds to sleep. Default 5.
    - fail_probability (float): 0.0 to 1.0 chance of raising an error. Default 0.
    """

    def run(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        duration = float(parameters.get("duration", 5))
        fail_prob = float(parameters.get("fail_probability", 0.0))

        logger.info("mock_run_start", duration=duration, fail_prob=fail_prob)

        # Simulate processing time
        time.sleep(duration)

        # Simulate failure
        if random.random() < fail_prob:
            raise RuntimeError("Simulated random failure in MockModelRunner")

        # Simulate result generation
        accuracy = 0.8 + (random.random() * 0.2)  # 0.8 to 1.0

        result = {
            "accuracy": round(accuracy, 4),
            "processed_items": random.randint(100, 1000),
            "simulated_duration": duration
        }

        logger.info("mock_run_success", result=result)
        return result
