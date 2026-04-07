"""
LLM backend implementations. Each backend is a thin wrapper around one model
provider, exposing a single method:

    generate(prompt: str, images: list[bytes] | None = None) -> str

Backends know nothing about evaluation logic — they just call the model.
All orchestration lives in eval_core.py.

Available backends:
  gemini  — Google Gemini via AI Studio API (requires GOOGLE_API_KEY env var)
  ollama  — Local model via Ollama daemon
  hf      — HuggingFace transformers (Kaggle / GPU environments)
"""

import base64
import os
from abc import ABC, abstractmethod

DEFAULTS = {
    "gemini": "gemini-2.5-pro",
    "ollama": "qwen2.5vl:7b",
    "hf":     "Qwen/Qwen2.5-VL-7B-Instruct",
}


class Backend(ABC):
    """Abstract base for all model backends."""

    @abstractmethod
    def generate(self, prompt: str, images: list[bytes] | None = None) -> str:
        """Send a prompt (and optional images) to the model and return the response text."""
        ...


class GeminiBackend(Backend):
    def __init__(self, model: str):
        from google import genai
        self.model = model
        self.client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    def generate(self, prompt: str, images: list[bytes] | None = None) -> str:
        from google.genai import types
        contents = []
        if images:
            labels = ["Before screenshot:", "After screenshot:"] + ["Image:"] * max(0, len(images) - 2)
            for label, img_bytes in zip(labels, images):
                contents.append(types.Part.from_text(text=label))
                contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))
        contents.append(types.Part.from_text(text=prompt))
        response = self.client.models.generate_content(model=self.model, contents=contents)
        return response.text.strip()


class OllamaBackend(Backend):
    def __init__(self, model: str):
        import ollama as _ollama
        self.model = model
        self._ollama = _ollama

    def generate(self, prompt: str, images: list[bytes] | None = None) -> str:
        message = {"role": "user", "content": prompt}
        if images:
            message["images"] = [base64.b64encode(img).decode() for img in images]
        response = self._ollama.chat(model=self.model, messages=[message])
        return response["message"]["content"].strip()


class HuggingFaceBackend(Backend):
    def __init__(self, model: str, load_in_4bit: bool = True):
        """Load the model once at construction time.

        load_in_4bit: BitsAndBytes 4-bit quantization. Keeps VRAM ~5-6GB on a T4.
        """
        import torch
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

        self.model = model
        quant_config = BitsAndBytesConfig(load_in_4bit=True) if load_in_4bit else None
        self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model,
            quantization_config=quant_config,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        self._processor = AutoProcessor.from_pretrained(model)
        self._torch = torch

    def generate(self, prompt: str, images: list[bytes] | None = None) -> str:
        import io
        from PIL import Image
        from qwen_vl_utils import process_vision_info

        content = []
        if images:
            labels = ["Before screenshot:", "After screenshot:"] + ["Image:"] * max(0, len(images) - 2)
            for label, img_bytes in zip(labels, images):
                content.append({"type": "text", "text": label})
                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                pil_img.thumbnail((512, 512))
                content.append({"type": "image", "image": pil_img})
        content.append({"type": "text", "text": prompt})

        messages = [{"role": "user", "content": content}]
        text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._processor(
            text=[text], images=image_inputs, videos=video_inputs, return_tensors="pt"
        ).to(self._model.device)

        with self._torch.no_grad():
            output_ids = self._model.generate(**inputs, max_new_tokens=512)
        generated = output_ids[:, inputs.input_ids.shape[1]:]
        return self._processor.batch_decode(generated, skip_special_tokens=True)[0].strip()


def get_backend(name: str, model: str | None = None) -> Backend:
    """Factory: return a Backend instance for the given name."""
    model = model or DEFAULTS[name]
    if name == "gemini":
        return GeminiBackend(model)
    if name == "ollama":
        return OllamaBackend(model)
    if name == "hf":
        return HuggingFaceBackend(model)
    raise ValueError(f"Unknown backend '{name}'. Choose from: {', '.join(DEFAULTS)}")
