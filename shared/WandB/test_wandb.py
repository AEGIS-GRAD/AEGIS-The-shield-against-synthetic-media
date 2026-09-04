import wandb

wandb.init(
    project="multimodal-deepfake-detection",
    name="test-run",
    config={
        "model": "Test Model",
        "dataset": "Test Dataset",
        "batch_size": 32,
        "seed": 42
    }
)

wandb.log({
    "accuracy": 0.95,
    "f1_score": 0.94,
    "auc": 0.97
})

wandb.finish()