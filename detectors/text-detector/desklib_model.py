"""
Desklib AI Text Detector Architecture definition & inference loader.
Follows the official Desklib architecture: DeBERTa-v3-large backbone + Mean Pooling + Linear(1024, 1) head.
"""
import os
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoConfig, AutoModel, PreTrainedModel

class DesklibAIDetectionModel(PreTrainedModel):
    config_class = AutoConfig
    _tied_weights_keys = []

    def __init__(self, config):
        super().__init__(config)
        self.model = AutoModel.from_config(config)
        self.classifier = nn.Linear(config.hidden_size, 1)
        self.init_weights()

    @property
    def all_tied_weights_keys(self):
        return {}

    def forward(self, input_ids, attention_mask=None, labels=None):
        outputs = self.model(input_ids, attention_mask=attention_mask)
        last_hidden_state = outputs[0]
        # Mean pooling
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        sum_embeddings = torch.sum(last_hidden_state * input_mask_expanded, dim=1)
        sum_mask = torch.clamp(input_mask_expanded.sum(dim=1), min=1e-9)
        pooled_output = sum_embeddings / sum_mask

        logits = self.classifier(pooled_output)
        loss = None
        if labels is not None:
            loss_fct = nn.BCEWithLogitsLoss()
            loss = loss_fct(logits.view(-1), labels.float())

        output = {"logits": logits}
        if loss is not None:
            output["loss"] = loss
        return output

def load_desklib(model_dir=None, device=None):
    if model_dir is None:
        model_dir = os.path.join(os.path.dirname(__file__), "models", "desklib-base")
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = DesklibAIDetectionModel.from_pretrained(model_dir)
    model.to(device)
    model.eval()
    return model, tokenizer, device

def predict_text(text: str, model, tokenizer, device, max_len=512):
    encoded = tokenizer(
        text,
        padding='max_length',
        truncation=True,
        max_length=max_len,
        return_tensors='pt'
    )
    input_ids = encoded['input_ids'].to(device)
    attention_mask = encoded['attention_mask'].to(device)

    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        logits = outputs["logits"]
        ai_prob = torch.sigmoid(logits).item()
        
    return {
        "ai_score": round(ai_prob, 4),
        "human_score": round(1.0 - ai_prob, 4),
        "prediction": "synthetic" if ai_prob >= 0.5 else "authentic",
        "confidence": round(abs(ai_prob - 0.5) * 2, 4)
    }

if __name__ == "__main__":
    print("[*] Testing Desklib model loading and inference...")
    model, tokenizer, device = load_desklib()
    print(f"[+] Loaded on device: {device}")
    
    sample_ai = "In evaluating renewable power, it is crucial to analyze both technical limits and market costs. Furthermore, storage solutions play a key role."
    sample_human = "The Treaty of Westphalia signed in 1648 established the conceptual foundation of modern sovereign nation-states."
    
    print("\n[AI Sample Result]:", predict_text(sample_ai, model, tokenizer, device))
    print("[Human Sample Result]:", predict_text(sample_human, model, tokenizer, device))
