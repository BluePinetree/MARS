# MARS — Example Outputs

Each subdirectory contains the output artifacts from a complete MARS pipeline run:

| File | Description |
|------|-------------|
| `paper.md` | Auto-generated research paper (7 sections + coherence revision) |
| `result.json` | Experiment metrics written by generated code |
| `run_summary.md` | Human-readable summary of the pipeline run |

---

## Available Examples

### [cifar10_resnet_vs_mobilenetv2](./cifar10_resnet_vs_mobilenetv2/)

**Topic:** ResNet-18 vs MobileNetV2 accuracy and efficiency comparison on CIFAR-10  
**Domain:** Computer Vision · PyTorch  
**Pipeline:** Phase 0 → Phase 1 (approved) → Phase 2 (19 files generated) → Phase 3 → Phase 4  
**Paper quality score:** 1.00 · Coherence score: 0.74 (abstract + experiments revised)

---

## How to Run Your Own

```bash
curl -X POST http://localhost:8000/api/v1/research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "ResNet-18 vs ViT-tiny on CIFAR-10",
    "goal": "Compare top-1 accuracy for 10 epochs",
    "domain": "Computer Vision",
    "preferred_frameworks": "PyTorch",
    "max_experiments": 1,
    "time_limit_minutes": 30
  }'
```

Output lands in `crewai_prototype/outputs/<run_id>/`.
