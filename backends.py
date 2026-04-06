"""
VLM backend implementations. Each backend exposes a single method:

    evaluate(example_dir: Path) -> dict
        Returns: { name, task, verdict ("PASS"/"FAIL"/"UNKNOWN"), response }

Use get_backend(name, model) to instantiate the right one.

Available backends:
  gemini  — Google Gemini via AI Studio API (requires GOOGLE_API_KEY env var)
  ollama  — Local model via Ollama daemon
  hf      — HuggingFace transformers (used on Kaggle / GPU environments)
"""

import base64
import os
from pathlib import Path

from eval_core import build_code_analysis_prompt, build_visual_verification_prompt, load_example, parse_verdict

# Default model names per backend
DEFAULTS = {
    "gemini": "gemini-2.5-pro",
    "ollama": "qwen2.5vl:7b",
    "hf":     "Qwen/Qwen2.5-VL-7B-Instruct",
}


class GeminiBackend:
    def __init__(self, model: str):
        from google import genai
        self.model = model
        self.client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    def evaluate(self, example_dir: Path, use_diff: bool = False) -> dict:
        from google.genai import types

        ex = load_example(example_dir)

        # --- Step 1: code-only analysis ---
        # No images. The model reasons about whether the code change is correct
        # and produces a concrete visual expectation (e.g. "footer text should be white").
        code_prompt = (
            build_code_analysis_prompt(ex["task"], diff=ex["diff"])
            if use_diff
            else build_code_analysis_prompt(ex["task"], ex["before_code"], ex["after_code"])
        )
        step1_response = self.client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_text(text=code_prompt)],
        )
        expectation = step1_response.text.strip()

        # --- Step 2: visual verification conditioned on Step 1's expectation ---
        # The expectation string directs the model's attention to the specific element
        # and property, avoiding the failure mode of open-ended image comparison.
        visual_prompt = build_visual_verification_prompt(ex["task"], expectation)
        step2_response = self.client.models.generate_content(
            model=self.model,
            contents=[
                types.Part.from_text(text="Before screenshot:"),
                types.Part.from_bytes(data=ex["before_image"].read_bytes(), mime_type="image/png"),
                types.Part.from_text(text="After screenshot:"),
                types.Part.from_bytes(data=ex["after_image"].read_bytes(), mime_type="image/png"),
                types.Part.from_text(text=visual_prompt),
            ],
        )

        response_text = step2_response.text.strip()
        return {
            "name": ex["name"],
            "task": ex["task"],
            "verdict": parse_verdict(response_text),
            # Include both steps in the response for debugging/inspection.
            "response": f"[Step 1 - Code Analysis]\n{expectation}\n\n[Step 2 - Visual Verification]\n{response_text}",
        }


class OllamaBackend:
    def __init__(self, model: str):
        import ollama as _ollama
        self.model = model
        self._ollama = _ollama

    def evaluate(self, example_dir: Path, use_diff: bool = False) -> dict:
        ex = load_example(example_dir)
        before_b64 = base64.b64encode(ex["before_image"].read_bytes()).decode()
        after_b64  = base64.b64encode(ex["after_image"].read_bytes()).decode()

        # Step 1: code-only analysis — no images.
        code_prompt = (
            build_code_analysis_prompt(ex["task"], diff=ex["diff"])
            if use_diff
            else build_code_analysis_prompt(ex["task"], ex["before_code"], ex["after_code"])
        )
        step1 = self._ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": code_prompt}],
        )
        expectation = step1["message"]["content"].strip()

        # Step 2: visual verification conditioned on the expectation.
        visual_prompt = build_visual_verification_prompt(ex["task"], expectation)
        step2 = self._ollama.chat(
            model=self.model,
            messages=[{
                "role": "user",
                "content": f"Before screenshot is image 1, after screenshot is image 2.\n\n{visual_prompt}",
                "images": [before_b64, after_b64],
            }],
        )

        response_text = step2["message"]["content"].strip()
        return {
            "name": ex["name"],
            "task": ex["task"],
            "verdict": parse_verdict(response_text),
            "response": f"[Step 1 - Code Analysis]\n{expectation}\n\n[Step 2 - Visual Verification]\n{response_text}",
        }


class HuggingFaceBackend:
    def __init__(self, model: str, load_in_4bit: bool = True):
        """Load the model once at construction time — this is the expensive step.

        load_in_4bit: use BitsAndBytes 4-bit quantization. Recommended on T4 (16GB)
        to keep VRAM usage around 5-6GB and leave headroom for inference.
        """
        import torch
        from transformers import BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration, AutoProcessor

        self.model_name = model

        quant_config = BitsAndBytesConfig(load_in_4bit=True) if load_in_4bit else None

        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model,
            quantization_config=quant_config,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        self.processor = AutoProcessor.from_pretrained(model)
        self.torch = torch

    def evaluate(self, example_dir: Path, use_diff: bool = False) -> dict:
        from PIL import Image
        from qwen_vl_utils import process_vision_info

        ex = load_example(example_dir)

        def load_image(path: Path) -> Image.Image:
            img = Image.open(path).convert("RGB")
            img.thumbnail((512, 512))
            return img

        def run_hf(messages: list) -> str:
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                return_tensors="pt",
            ).to(self.model.device)
            with self.torch.no_grad():
                output_ids = self.model.generate(**inputs, max_new_tokens=512)
            generated = output_ids[:, inputs.input_ids.shape[1]:]
            return self.processor.batch_decode(generated, skip_special_tokens=True)[0].strip()

        # Step 1: code-only analysis — no images.
        code_prompt = (
            build_code_analysis_prompt(ex["task"], diff=ex["diff"])
            if use_diff
            else build_code_analysis_prompt(ex["task"], ex["before_code"], ex["after_code"])
        )
        expectation = run_hf([{"role": "user", "content": [{"type": "text", "text": code_prompt}]}])

        # Step 2: visual verification conditioned on the expectation.
        visual_prompt = build_visual_verification_prompt(ex["task"], expectation)
        messages = [{
            "role": "user",
            "content": [
                {"type": "text",  "text": "Before screenshot:"},
                {"type": "image", "image": load_image(ex["before_image"])},
                {"type": "text",  "text": "After screenshot:"},
                {"type": "image", "image": load_image(ex["after_image"])},
                {"type": "text",  "text": visual_prompt},
            ],
        }]

        response_text = run_hf(messages)

        return {
            "name": ex["name"],
            "task": ex["task"],
            "verdict": parse_verdict(response_text),
            "response": f"[Step 1 - Code Analysis]\n{expectation}\n\n[Step 2 - Visual Verification]\n{response_text}",
        }


def get_backend(name: str, model: str | None = None):
    """Factory: returns the right backend instance for the given name."""
    model = model or DEFAULTS[name]
    if name == "gemini":
        return GeminiBackend(model)
    if name == "ollama":
        return OllamaBackend(model)
    if name == "hf":
        return HuggingFaceBackend(model)
    raise ValueError(f"Unknown backend '{name}'. Choose from: gemini, ollama, hf")
