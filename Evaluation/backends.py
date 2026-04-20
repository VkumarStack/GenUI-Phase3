"""
LLM backend implementations. Each backend is a thin wrapper around one model
provider, exposing a single method:

    generate(prompt: str, images: list[bytes] | None = None) -> str

Backends know nothing about evaluation logic — they just call the model.
All orchestration lives in eval_core.py.

Available backends:
  gemini    — Google Gemini via AI Studio API (requires GOOGLE_API_KEY env var)
  vertexai  — Vertex AI endpoint, including fine-tuned Gemini models
              (requires VERTEXAI_PROJECT and VERTEXAI_LOCATION env vars;
               uses Application Default Credentials — run:
               gcloud auth application-default login)
  anthropic — Anthropic Claude via API (requires ANTHROPIC_API_KEY env var)
  ollama    — Local model via Ollama daemon
  hf        — HuggingFace transformers (Kaggle / GPU environments)
"""

import base64
import os
from abc import ABC, abstractmethod

DEFAULTS = {
    "gemini":    "gemini-2.5-pro",
    "vertexai":  None,   # no sensible default — model ID must be supplied explicitly
    "anthropic": "claude-sonnet-4-6",
    "openai":    "gpt-4o",
    "ollama":    "qwen2.5vl:7b",
    "hf":        "Qwen/Qwen2.5-VL-7B-Instruct",
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


class VertexAIBackend(Backend):
    """Calls a Vertex AI endpoint — use this for fine-tuned Gemini models.

    Requires:
      - VERTEXAI_PROJECT env var (your GCP project ID)
      - VERTEXAI_LOCATION env var (region, e.g. us-central1)
      - Application Default Credentials:  gcloud auth application-default login

    The model string is the full resource name of the tuned model endpoint,
    e.g. projects/my-project/locations/us-central1/endpoints/1234567890
    """

    def __init__(self, model: str | None = None):
        import vertexai
        from vertexai.generative_models import GenerativeModel

        project   = os.environ.get("VERTEXAI_PROJECT")
        location  = os.environ.get("VERTEXAI_LOCATION", "us-central1")
        endpoint  = os.environ.get("VERTEXAI_ENDPOINT_ID")

        if not project:
            raise ValueError("VERTEXAI_PROJECT env var is required for the vertexai backend.")

        # Resolve model: explicit arg → full resource path from env vars → error.
        if model:
            self.model = model
        elif endpoint:
            self.model = f"projects/{project}/locations/{location}/endpoints/{endpoint}"
        else:
            raise ValueError(
                "No model endpoint specified. Either pass --model with the full resource path, "
                "or set VERTEXAI_ENDPOINT_ID in your .env file."
            )

        vertexai.init(project=project, location=location)
        self._genmodel = GenerativeModel(self.model)

    def generate(self, prompt: str, images: list[bytes] | None = None) -> str:
        from vertexai.generative_models import Image, Part

        parts = []
        if images:
            labels = ["Before screenshot:", "After screenshot:"] + ["Image:"] * max(0, len(images) - 2)
            for label, img_bytes in zip(labels, images):
                parts.append(Part.from_text(label))
                parts.append(Part.from_image(Image.from_bytes(img_bytes)))
        parts.append(Part.from_text(prompt))

        response = self._genmodel.generate_content(parts)
        return response.text.strip()


class AnthropicBackend(Backend):
    def __init__(self, model: str):
        import anthropic
        self.model = model
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def generate(self, prompt: str, images: list[bytes] | None = None) -> str:
        content = []
        if images:
            labels = ["Before screenshot:", "After screenshot:"] + ["Image:"] * max(0, len(images) - 2)
            for label, img_bytes in zip(labels, images):
                content.append({"type": "text", "text": label})
                content.append({
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": "image/png",
                        "data":       base64.b64encode(img_bytes).decode(),
                    },
                })
        content.append({"type": "text", "text": prompt})
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text.strip()


class OpenAIBackend(Backend):
    def __init__(self, model: str):
        import openai
        self.model = model
        self.client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def generate(self, prompt: str, images: list[bytes] | None = None) -> str:
        import base64 as _base64
        content = []
        if images:
            labels = ["Before screenshot:", "After screenshot:"] + ["Image:"] * max(0, len(images) - 2)
            for label, img_bytes in zip(labels, images):
                content.append({"type": "text", "text": label})
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{_base64.b64encode(img_bytes).decode()}"
                    },
                })
        content.append({"type": "text", "text": prompt})
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content.strip()


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
    model = model or DEFAULTS.get(name)
    if name == "gemini":
        return GeminiBackend(model)
    if name == "vertexai":
        return VertexAIBackend(model)  # model=None triggers env var resolution
    if name == "anthropic":
        return AnthropicBackend(model)
    if name == "openai":
        return OpenAIBackend(model)
    if name == "ollama":
        return OllamaBackend(model)
    if name == "hf":
        return HuggingFaceBackend(model)
    raise ValueError(f"Unknown backend '{name}'. Choose from: {', '.join(DEFAULTS)}")
