"""Input Enricher — augments research inputs with domain-specific knowledge.

Called after the Planner confirms a profile, before ContractArchitect runs.
Adds a 'domain_context' key to the inputs dict so downstream agents receive
concrete constraints (dataset stats, typical hyperparams, known pitfalls)
without having to invent them from scratch.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Domain knowledge templates
# ---------------------------------------------------------------------------

_DOMAIN_KNOWLEDGE: dict[str, dict] = {
    "vision_classification": {
        "typical_stack": "PyTorch + torchvision",
        "common_models": ["ResNet18", "ResNet50", "ViT-B/16", "EfficientNet-B0"],
        "dataset_stats": {
            "cifar10": {
                "num_classes": 10, "image_size": 32, "channels": 3,
                "mean": [0.4914, 0.4822, 0.4465], "std": [0.2470, 0.2435, 0.2616],
            },
            "cifar100": {
                "num_classes": 100, "image_size": 32, "channels": 3,
                "mean": [0.5071, 0.4867, 0.4408], "std": [0.2675, 0.2565, 0.2761],
            },
            "imagenet": {
                "num_classes": 1000, "image_size": 224, "channels": 3,
                "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
            },
        },
        "typical_hyperparams": {
            "lr": 1e-3, "weight_decay": 1e-4, "batch_size": 128,
            "epochs": 50, "optimizer": "SGD(momentum=0.9)",
            "scheduler": "CosineAnnealingLR",
        },
        "evaluation_protocol": "top-1 accuracy on test set",
        "augmentation": [
            "RandomCrop(size, padding=4)",
            "RandomHorizontalFlip()",
            "Normalize(mean, std)",
        ],
        "pitfalls": [
            "Always normalize with dataset-specific mean/std — not ImageNet defaults for CIFAR",
            "Apply augmentation only during training, not validation/test",
            "CIFAR-100 has 100 classes — ensure model final layer matches",
            "Use pin_memory=True and num_workers>0 for DataLoader performance",
        ],
    },
    "tabular_supervised": {
        "typical_stack": "PyTorch MLP or gradient boosting (use PyTorch for reproducibility)",
        "typical_hyperparams": {
            "hidden_dims": [256, 128, 64], "dropout": 0.3, "batch_size": 512,
            "lr": 1e-3, "epochs": 100, "optimizer": "Adam",
        },
        "evaluation_protocol": (
            "ROC-AUC for binary classification, "
            "macro-F1 for multiclass, RMSE for regression"
        ),
        "pitfalls": [
            "StandardScaler or MinMaxScaler numerical features before model",
            "Encode categoricals — LabelEncoder or one-hot",
            "Stratified train/val split for imbalanced targets",
            "Check for data leakage: no future information in features",
        ],
    },
    "timeseries_forecasting": {
        "typical_stack": "PyTorch LSTM / Transformer",
        "typical_hyperparams": {
            "window_size": 24, "horizon": 12, "batch_size": 64,
            "hidden_size": 128, "num_layers": 2, "lr": 1e-3,
        },
        "evaluation_protocol": "MAE and RMSE on held-out future period via rolling-origin backtest",
        "pitfalls": [
            "Never use future data as features — strict temporal ordering",
            "Align timestamps and resample to uniform frequency before splitting",
            "Use rolling-origin backtest for honest evaluation (not a single split)",
            "Normalize targets per-series or globally — document which",
        ],
    },
    "generic_script": {
        "typical_stack": "PyTorch",
        "typical_hyperparams": {"lr": 1e-3, "batch_size": 32, "epochs": 10},
        "evaluation_protocol": "Task-specific metric defined in research goal",
        "pitfalls": [
            "Implement real training logic — no synthetic / placeholder data",
            "Write all results to result.json via artifacts.save_results()",
            "Use fixed random seeds for reproducibility",
        ],
    },
}


# ---------------------------------------------------------------------------
# Dataset detection
# ---------------------------------------------------------------------------

_DATASET_ALIASES: dict[str, str] = {
    "cifar-100": "cifar100",
    "cifar 100": "cifar100",
    "cifar10": "cifar10",
    "cifar-10": "cifar10",
    "cifar 10": "cifar10",
    "imagenet": "imagenet",
    "image-net": "imagenet",
}


def _detect_dataset(topic_text: str) -> dict:
    """Return dataset stats dict if a known dataset is mentioned in the text."""
    text_lower = topic_text.lower()
    dataset_stats = _DOMAIN_KNOWLEDGE["vision_classification"]["dataset_stats"]

    for alias, canonical in _DATASET_ALIASES.items():
        if alias in text_lower:
            info = dataset_stats.get(canonical, {})
            return {"name": canonical, **info}

    for name, info in dataset_stats.items():
        if name in text_lower:
            return {"name": name, **info}

    return {}


# ---------------------------------------------------------------------------
# Enricher
# ---------------------------------------------------------------------------

class ResearchInputEnricher:
    """Adds domain_context to research inputs based on the planner's recommended profile.

    Usage:
        enricher = ResearchInputEnricher()
        enriched = enricher.enrich(base_inputs, profile="vision_classification")
        # enriched["domain_context"] is now a dict with stack, hyperparams, pitfalls, etc.
    """

    def enrich(self, research_input: dict[str, Any], profile: str) -> dict[str, Any]:
        """Return a new dict with a 'domain_context' key added.

        Never overrides existing keys — safe to call on any inputs dict.
        If profile is unknown, falls back to generic_script template.
        """
        template = _DOMAIN_KNOWLEDGE.get(profile, _DOMAIN_KNOWLEDGE["generic_script"])

        topic_text = " ".join([
            str(research_input.get("research_topic", "")),
            str(research_input.get("research_goal", "")),
            str(research_input.get("research_domain", "")),
        ])

        domain_context: dict[str, Any] = {
            "profile": profile,
            "typical_stack": template.get("typical_stack", ""),
            "evaluation_protocol": template.get("evaluation_protocol", ""),
            "typical_hyperparams": template.get("typical_hyperparams", {}),
            "pitfalls": template.get("pitfalls", []),
        }

        if profile == "vision_classification":
            detected = _detect_dataset(topic_text)
            if detected:
                domain_context["detected_dataset"] = detected

        return {**research_input, "domain_context": domain_context}

    def domain_context_summary(self, profile: str, research_input: dict[str, Any]) -> str:
        """Return a compact text summary for embedding in agent task descriptions."""
        enriched = self.enrich(research_input, profile)
        ctx = enriched.get("domain_context", {})

        lines = [
            f"Stack: {ctx.get('typical_stack', 'PyTorch')}",
            f"Evaluation: {ctx.get('evaluation_protocol', '')}",
            f"Typical hyperparams: {ctx.get('typical_hyperparams', {})}",
        ]
        if ctx.get("detected_dataset"):
            ds = ctx["detected_dataset"]
            lines.append(f"Dataset: {ds.get('name')} — classes={ds.get('num_classes')}, "
                         f"image_size={ds.get('image_size')}, "
                         f"mean={ds.get('mean')}, std={ds.get('std')}")
        pitfalls = ctx.get("pitfalls", [])
        if pitfalls:
            lines.append("Known pitfalls:")
            lines.extend(f"  - {p}" for p in pitfalls)

        return "\n".join(lines)
