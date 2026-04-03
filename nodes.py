import re
import base64
import requests
import numpy as np
from io import BytesIO
from PIL import Image

DEFAULT_URL = "http://localhost:8080"


def _extract_thinking(text: str) -> tuple[str, str]:
    pattern = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
    thinking_parts = pattern.findall(text)
    thinking_text = "\n\n".join(p.strip() for p in thinking_parts)
    clean_text = pattern.sub("", text).strip()
    return clean_text, thinking_text


def _tensor_to_base64(image_tensor) -> str:
    img_np = (image_tensor.numpy() * 255).clip(0, 255).astype(np.uint8)
    pil_img = Image.fromarray(img_np, mode="RGB")
    buf = BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _parse_thinking_control(thinking_control: str) -> tuple[str, bool]:
    """
    Parse thinking_control dropdown value.
    Returns: (model_series, thinking_enabled)
    """
    if "Other Models" in thinking_control:
        return "Other Models", True
    elif "Gemma 4 Series" in thinking_control:
        return "Gemma 4 Series", "Enabled" in thinking_control
    elif "Qwen 3.5 Series" in thinking_control:
        return "Qwen 3.5 Series", "Enabled" in thinking_control
    return "Other Models", True


def _apply_thinking_control(model_series: str, thinking_enabled: bool, 
                           system_prompt: str, server_url: str, payload: dict) -> tuple[str, dict]:
    """
    Apply thinking control based on model series.
    Returns: (modified_system_prompt, modified_payload)
    """
    if model_series == "Gemma 4 Series":
        if thinking_enabled:
            if system_prompt and "<|think|>" not in system_prompt:
                system_prompt = "<|think|>\n" + system_prompt
        else:
            if system_prompt:
                system_prompt = system_prompt.replace("<|think|>\n", "").replace("<|think|>", "")
    
    elif model_series == "Qwen 3.5 Series":
        if not thinking_enabled:
            if "extra_body" not in payload:
                payload["extra_body"] = {}
            payload["extra_body"]["chat_template_kwargs"] = {"enable_thinking": False}
    
    return system_prompt, payload


class LlamaSwapClient:
    CATEGORY = "llama-swap"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "thinking")
    OUTPUT_TOOLTIPS = (
        "Clean response text with <think> blocks removed",
        "Extracted thinking/reasoning content (empty if model produced none)",
    )
    FUNCTION = "generate"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "server_url": ("STRING", {
                    "default": DEFAULT_URL,
                    "tooltip": "llama-swap server base URL",
                }),
                "model": ("STRING", {
                    "default": "",
                    "tooltip": "Model name — click Fetch Models button to pick from the server",
                }),
                "system_prompt": ("STRING", {
                    "default": "You are a helpful assistant.",
                    "multiline": True,
                    "tooltip": "System prompt sent before the user message",
                }),
                "prompt": ("STRING", {
                    "default": "Hello!",
                    "multiline": True,
                    "tooltip": "User message / question",
                }),
                "unload_after_generate": ("BOOLEAN", {
                    "default": False,
                    "label_on":  "Unload model after ✓",
                    "label_off": "Keep model loaded",
                    "tooltip": "Call /unload on the llama-swap server after generation",
                }),
            },
            "optional": {
                "thinking_control": ("COMBO", {
                    "default": "Other Models - Thinking Default",
                    "values": [
                        "Other Models - Thinking Default",
                        "Gemma 4 Series - Thinking Enabled",
                        "Gemma 4 Series - Thinking Disabled",
                        "Qwen 3.5 Series - Thinking Enabled",
                        "Qwen 3.5 Series - Thinking Disabled",
                    ],
                    "tooltip": "Select model series and thinking mode",
                }),
                "image_1": ("IMAGE", {
                    "tooltip": "First image for vision models (refer as 'image 1' in prompt)",
                }),
                "image_2": ("IMAGE", {
                    "tooltip": "Second image for vision models (refer as 'image 2' in prompt)",
                }),
                "image_3": ("IMAGE", {
                    "tooltip": "Third image for vision models (refer as 'image 3' in prompt)",
                }),
                "image_4": ("IMAGE", {
                    "tooltip": "Fourth image for vision models (refer as 'image 4' in prompt)",
                }),
                "use_temperature": ("BOOLEAN", {
                    "default": False,
                    "label_on": "Temp ✓",
                    "label_off": "Temp",
                    "tooltip": "Enable temperature parameter",
                }),
                "temperature": ("FLOAT", {
                    "default": 0.8,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.01,
                    "tooltip": "Controls randomness (0=deterministic, 1=creative)",
                }),
                "use_top_k": ("BOOLEAN", {
                    "default": False,
                    "label_on": "TopK ✓",
                    "label_off": "TopK",
                    "tooltip": "Enable top_k parameter",
                }),
                "top_k": ("INT", {
                    "default": 40,
                    "min": 0,
                    "max": 100,
                    "tooltip": "Sample from top K tokens (0=disabled)",
                }),
                "use_top_p": ("BOOLEAN", {
                    "default": False,
                    "label_on": "TopP ✓",
                    "label_off": "TopP",
                    "tooltip": "Enable top_p parameter",
                }),
                "top_p": ("FLOAT", {
                    "default": 0.9,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Nucleus sampling threshold (1.0=disabled)",
                }),
                "use_min_p": ("BOOLEAN", {
                    "default": False,
                    "label_on": "MinP ✓",
                    "label_off": "MinP",
                    "tooltip": "Enable min_p parameter",
                }),
                "min_p": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Minimum token probability (0.0=disabled)",
                }),
                "use_max_tokens": ("BOOLEAN", {
                    "default": False,
                    "label_on": "MaxToks ✓",
                    "label_off": "MaxToks",
                    "tooltip": "Enable max_tokens parameter",
                }),
                "max_tokens": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 100000,
                    "tooltip": "Maximum response tokens (0=unlimited)",
                }),
                "use_frequency_penalty": ("BOOLEAN", {
                    "default": False,
                    "label_on": "FreqPen ✓",
                    "label_off": "FreqPen",
                    "tooltip": "Enable frequency_penalty parameter",
                }),
                "frequency_penalty": ("FLOAT", {
                    "default": 0.0,
                    "min": -2.0,
                    "max": 2.0,
                    "step": 0.01,
                    "tooltip": "Reduce repetition (-2.0 to 2.0)",
                }),
                "use_presence_penalty": ("BOOLEAN", {
                    "default": False,
                    "label_on": "PresPen ✓",
                    "label_off": "PresPen",
                    "tooltip": "Enable presence_penalty parameter",
                }),
                "presence_penalty": ("FLOAT", {
                    "default": 0.0,
                    "min": -2.0,
                    "max": 2.0,
                    "step": 0.01,
                    "tooltip": "Encourage new topics (-2.0 to 2.0)",
                }),
                "use_seed": ("BOOLEAN", {
                    "default": False,
                    "label_on": "Seed ✓",
                    "label_off": "Seed",
                    "tooltip": "Enable seed parameter",
                }),
                "seed": ("INT", {
                    "default": -1,
                    "tooltip": "Random seed for reproducibility (-1=random)",
                }),
            },
        }

    def generate(self, 
             server_url, model, system_prompt, prompt, unload_after_generate,
             thinking_control="Other Models - Thinking Default",
             image_1=None, image_2=None, image_3=None, image_4=None,
             use_temperature=False, temperature=0.8,
             use_top_k=False, top_k=40,
             use_top_p=False, top_p=0.9,
             use_min_p=False, min_p=0.0,
             use_max_tokens=False, max_tokens=0,
             use_frequency_penalty=False, frequency_penalty=0.0,
             use_presence_penalty=False, presence_penalty=0.0,
             use_seed=False, seed=-1):
        base_url = server_url.rstrip("/")
        
        # Parse thinking control
        model_series, thinking_enabled = _parse_thinking_control(thinking_control)
        
        # Build base payload first (needed for Qwen 3.5 extra_body)
        payload = {"model": model, "messages": [], "stream": False}
        
        # Apply thinking control to system prompt
        if system_prompt.strip():
            system_prompt, payload = _apply_thinking_control(
                model_series, thinking_enabled, system_prompt.strip(), server_url, payload
            )
            if system_prompt:
                payload["messages"].append({"role": "system", "content": system_prompt})
        
        # Handle Gemma 4 with empty system prompt but thinking enabled
        if model_series == "Gemma 4 Series" and thinking_enabled and not system_prompt.strip():
            payload["messages"].append({"role": "system", "content": "<|think|>"})

        # Build content array with text and all provided images
        user_content = [{"type": "text", "text": prompt}]
        
        for img_tensor in [image_1, image_2, image_3, image_4]:
            if img_tensor is not None:
                img_b64 = _tensor_to_base64(img_tensor[0])
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })

        payload["messages"].append({"role": "user", "content": user_content})

        # Add generation parameters based on enable switches
        if use_temperature:
            payload["temperature"] = temperature
        if use_top_k:
            payload["top_k"] = top_k
        if use_top_p:
            payload["top_p"] = top_p
        if use_min_p:
            payload["min_p"] = min_p
        if use_max_tokens:
            payload["max_tokens"] = max_tokens
        if use_frequency_penalty:
            payload["frequency_penalty"] = frequency_penalty
        if use_presence_penalty:
            payload["presence_penalty"] = presence_penalty
        if use_seed:
            payload["seed"] = seed

        try:
            r = requests.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                timeout=300,
            )
            r.raise_for_status()
            full_text = r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            err = f"[LlamaSwap ERROR] {exc}"
            if unload_after_generate:
                try: requests.get(f"{base_url}/unload", timeout=5)
                except Exception: pass
            return (err, "")

        clean_text, thinking_text = _extract_thinking(full_text)

        if unload_after_generate:
            try: requests.get(f"{base_url}/unload", timeout=5)
            except Exception: pass

        return (clean_text, thinking_text)


class LlamaSwapModelSelector:
    CATEGORY = "llama-swap"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("model_name",)
    FUNCTION = "select"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "server_url": ("STRING", {"default": DEFAULT_URL}),
                "model": ("STRING", {
                    "default": "",
                    "tooltip": "Model name — click Fetch Models button to pick from the server",
                }),
            }
        }

    def select(self, server_url: str, model: str):
        return (model,)


NODE_CLASS_MAPPINGS = {
    "LlamaSwapClient":        LlamaSwapClient,
    "LlamaSwapModelSelector": LlamaSwapModelSelector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LlamaSwapClient":        "🦙 Llama-Swap Client",
    "LlamaSwapModelSelector": "🦙 Llama-Swap Model Selector",
}
