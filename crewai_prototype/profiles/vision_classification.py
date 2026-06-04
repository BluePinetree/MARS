from __future__ import annotations

from profiles.base import BaseResearchProfile


class VisionClassificationProfile(BaseResearchProfile):
    name = "vision_classification"
    description = "Executable image classification profile with top-1/top-5 accuracy parsing and real training/evaluation baselines."
    primary_metric = "accuracy"
    scaffold_type = "vision_classification"

    def mutable_scaffold_files(self):
        return super().mutable_scaffold_files() + (
            "src/data.py",
            "src/models.py",
            "src/train.py",
            "src/evaluate.py",
        )

    def runtime_required_inputs(self):
        return ("data_root",)

    def runtime_contract_notes(self):
        return (
            "The scaffold expects an image dataset root or an explicit built-in dataset cache root.",
            "If the dataset path is missing, the run must fail explicitly instead of falling back to a placeholder.",
            "Training and evaluation helpers must report real accuracy metrics, not synthetic values.",
        )
