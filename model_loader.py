import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

from config import get_hf_token

BASE_MODEL_REPO = "meta-llama/Llama-3.2-3B-Instruct"
ADAPTER_REPO = "DilshanDev/llama-text2sql-v2-saas"

_model = None
_tokenizer = None

def load_model():
  """
    Loads the model and tokenizer once. It is better because we use module-level singleton rather than load the model for every call.
  """
  global _model, _tokenizer

  if _model is not None:
    return _model, _tokenizer

  token = get_hf_token()

  quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
  )

  _tokenizer = AutoTokenizer.from_pretrained(ADAPTER_REPO, token=token, clean_up_tokenization_spaces=False)

  base_model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL_REPO,
    quantization_config=quant_config,
    device_map="auto",
    token=token,
  )

  _model = PeftModel.from_pretrained(base_model, ADAPTER_REPO, token=token)
  _model.eval()

  return _model, _tokenizer

def get_model_and_tokenizer():
  """
    Access the already loaded model and the tokenizer.
  """
  if _model is None:
    raise RuntimeError("Model is not loaded yet... Call load_model().")
  return _model, _tokenizer