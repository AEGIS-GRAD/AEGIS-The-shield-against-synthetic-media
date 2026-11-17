"""
Desklib AI Text Detector Architecture definition & inference loader.
Follows the official Desklib architecture: DeBERTa-v3-large backbone + Mean Pooling + Linear(1024, 1) head.
"""
import hashlib
import os
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoConfig, AutoModel, PreTrainedModel

DESKLIB_HF_REVISION = "5fdea974cd4287c61674951ec78803aa274e2fb7"
DESKLIB_BASE_SAFETENSORS_SHA256 = "c024a1704c65f5a4bffeda58745c58fc0ed67d6ca07b158b068a257238815265"
DESKLIB_LORA_SAFETENSORS_SHA256 = "dba5608b7f771fa38dce1c8148f874d46bc5d1bde6fb2e8a780f525c5044d93b"


def _verify_sha256(file_path: str, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != expected_sha256.lower():
        raise RuntimeError(
            f"Text detector weights integrity check failed for {file_path}: "
            f"expected {expected_sha256}, got {actual}"
        )

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
        classifier_param = next(self.classifier.parameters(), None)
        if classifier_param is not None and pooled_output.dtype != classifier_param.dtype:
            pooled_output = pooled_output.to(dtype=classifier_param.dtype)

        logits = self.classifier(pooled_output)
        loss = None
        if labels is not None:
            loss_fct = nn.BCEWithLogitsLoss()
            loss = loss_fct(logits.view(-1), labels.float())

        output = {"logits": logits}
        if loss is not None:
            output["loss"] = loss
        return output

def load_desklib(model_dir=None, device=None, use_finetuned=True):
    if model_dir is None:
        model_dir = os.path.join(os.path.dirname(__file__), "models", "desklib-base")
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
    # Auto-download base weights only for local directory targets (skip for HF repo IDs)
    is_hf_repo_id = (
        isinstance(model_dir, str)
        and "/" in model_dir
        and model_dir.count("/") == 1
        and not model_dir.startswith(("/", "./", "../", ".\\", "..\\"))
        and not os.path.isabs(model_dir)
    )
    config_file = os.path.join(model_dir, "config.json")
    if not is_hf_repo_id and not os.path.exists(config_file):
        print(f"[*] Base model not found in {model_dir}. Auto-downloading from Hugging Face...")
        from download_desklib import download_desklib
        download_desklib(model_dir)

    base_safetensors = os.path.join(str(model_dir), "model.safetensors")
    if (
        not is_hf_repo_id
        and os.path.exists(base_safetensors)
        and os.getenv("AEGIS_ALLOW_UNVERIFIED_WEIGHTS", "0") != "1"
    ):
        expected_base = os.getenv("DESKLIB_BASE_SHA256", DESKLIB_BASE_SAFETENSORS_SHA256).strip()
        if expected_base:
            _verify_sha256(base_safetensors, expected_base)

    hf_kwargs = {"trust_remote_code": False}
    if is_hf_repo_id:
        hf_kwargs["revision"] = DESKLIB_HF_REVISION
    tokenizer = AutoTokenizer.from_pretrained(model_dir, **hf_kwargs)
    model = DesklibAIDetectionModel.from_pretrained(model_dir, use_safetensors=True, **hf_kwargs)

    # Automatically load fine-tuned LoRA adapter if present
    adapter_dir = os.path.join(os.path.dirname(__file__), "models", "desklib-finetuned", "lora_adapter")
    if use_finetuned and os.path.exists(os.path.join(adapter_dir, "adapter_config.json")):
        try:
            from peft import PeftModel
            adapter_safetensors = os.path.join(adapter_dir, "adapter_model.safetensors")
            if os.path.exists(adapter_safetensors) and os.getenv("AEGIS_ALLOW_UNVERIFIED_WEIGHTS", "0") != "1":
                _verify_sha256(adapter_safetensors, DESKLIB_LORA_SAFETENSORS_SHA256)
            print(f"[*] Loading fine-tuned LoRA adapter from {adapter_dir}...")
            model.model = PeftModel.from_pretrained(model.model, adapter_dir)
            print("[+] Fine-tuned LoRA adapter successfully attached.")
        except Exception as e:
            print(f"[!] Warning: Could not attach LoRA adapter ({e}). Using base model.")

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
