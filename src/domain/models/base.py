from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseModelRunner(ABC):
    @abstractmethod
    def run(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes the model logic with the given parameters.

        Args:
            parameters: A dictionary of inputs specific to the model.

        Returns:
            A dictionary containing the results of the run.

        Raises:
            Exception: If the model run fails.
        """
        pass
