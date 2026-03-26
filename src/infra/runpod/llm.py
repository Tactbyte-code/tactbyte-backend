#!/usr/bin/env python3
"""
─────────────────────────────────────────────────────────────────────────────
Single shared LLM client — initialise once, call anywhere.

HF models are loaded into VRAM once and reused across all calls.
API providers (Anthropic, OpenAI, Gemini, Ollama, Sarvam) reuse a single config.

USAGE:
    from llm_client import get_client

    client = get_client()                          # reads env vars
    client = get_client(provider="gemini", model="gemini-2.5-flash")
    client = get_client(provider="hf", model="Qwen/Qwen3-4B")
    client = get_client(provider="sarvam", model="sarvam-105b")

    response = client.call(system_prompt, user_prompt)  # always returns str

PROVIDERS:
    anthropic  │ LLM_PROVIDER=anthropic  LLM_API_KEY=sk-ant-...
    openai     │ LLM_PROVIDER=openai     LLM_API_KEY=sk-...
    gemini     │ LLM_PROVIDER=gemini     LLM_API_KEY=AIza...
    ollama     │ LLM_PROVIDER=ollama     LLM_BASE_URL=http://localhost:11434
    sarvam     │ LLM_PROVIDER=sarvam     LLM_API_KEY=<subscription-key>
    hf         │ LLM_PROVIDER=hf         LLM_MODEL=Qwen/Qwen3-4B
               │ LLM_BASE_URL=/path/to/hf-cache  (optional)
    mock       │ LLM_PROVIDER=mock       (returns empty JSON instantly)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import os
import re
import urllib.request
import urllib.error

from src.core.settings import settings

# ── Provider defaults ─────────────────────────────────────────────────────────
_PROVIDER_DEFAULTS = {
    "anthropic": {"model": "claude-sonnet-4-20250514",  "base_url": "https://api.anthropic.com"},
    "openai":    {"model": "gpt-4o",                    "base_url": "https://api.openai.com"},
    "gemini":    {"model": "gemini-2.0-flash",          "base_url": "https://generativelanguage.googleapis.com"},
    "ollama":    {"model": "llama3",                    "base_url": "http://localhost:11434"},
    "sarvam":    {"model": "sarvam-105b",               "base_url": "https://api.sarvam.ai"},
    "hf":        {"model": "Qwen/Qwen3-14B",            "base_url": ""},
    "hf-local":  {"model": "Qwen/Qwen2.5-3B-Instruct",  "base_url": ""},
    "mock":      {"model": "mock",                      "base_url": ""},
}

# Output token limits per provider.
# Override via LLM_MAX_TOKENS env var, or pass max_tokens= to get_client().
_MAX_TOKENS = {
    "anthropic": 4000,
    "openai":    4000,
    "gemini":    8192,
    "ollama":    4000,
    "sarvam":    2000,
    "hf":        8192,   # 48GB GPU: plenty of KV cache headroom
    "hf-local":  1024,   # small local GPU: keep it fast
    "mock":      0,
}

# Model size estimates — (fp16_gb, nf4_gb)
# fp16 = full precision, nf4 = 4-bit quantised
_MODEL_SIZE_GB = {
    #  name                            fp16   nf4
    "Qwen/Qwen2.5-0.5B-Instruct":   ( 1.0,  0.4),
    "Qwen/Qwen2.5-1.5B-Instruct":   ( 3.0,  1.0),
    "Qwen/Qwen2.5-3B-Instruct":     ( 6.0,  1.8),
    "Qwen/Qwen3-4B":                ( 8.0,  2.5),
    "Qwen/Qwen3.5-2B":              ( 4.0,  1.3),
    "Qwen/Qwen3-8B":                (16.0,  5.0),
    "Qwen/Qwen2.5-7B-Instruct":     (14.0,  4.5),
    "Qwen/Qwen3-14B":               (28.0,  9.0),
    "Qwen/Qwen3-32B":               (64.0, 20.0),
    "Qwen/Qwen3-30B-A3B":           (60.0, 18.0),
    "Qwen/Qwen2.5-72B-Instruct":    (144., 42.0),
    "meta-llama/Llama-3.1-8B-Instruct":  (16.0,  5.0),
    "meta-llama/Llama-3.1-70B-Instruct": (140., 40.0),
}

_FALLBACK_LADDER = [
    "Qwen/Qwen2.5-0.5B-Instruct",
    "Qwen/Qwen2.5-1.5B-Instruct",
    "Qwen/Qwen2.5-3B-Instruct",
    "Qwen/Qwen3-4B",
    "Qwen/Qwen3-8B",
    "Qwen/Qwen3-14B",
]

_VRAM_SAFETY_MARGIN_GB = 2.0   # more headroom for KV cache on large GPUs


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP HELPER
# ═══════════════════════════════════════════════════════════════════════════════
def _post(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:600]
        hint = " (token/key expired?)" if e.code == 401 else ""
        raise RuntimeError(f"HTTP {e.code}{hint}: {body}")


# ═══════════════════════════════════════════════════════════════════════════════
# HF VRAM UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════
def _vram_info() -> tuple:
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0, 0.0
        free, total = torch.cuda.mem_get_info(0)
        return free / (1024 ** 3), total / (1024 ** 3)
    except Exception:
        return 0.0, 0.0


def _purge_vram():
    try:
        import torch, gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


def _pick_precision(model_name: str, free_gb: float) -> str:
    """
    Given available VRAM, return 'fp16', 'nf4', or 'cpu'.
      >= 6GB free  and fp16 fits  → fp16  (best quality)
      < 6GB free   or fp16 too big → nf4   (4-bit, fits most models)
      nothing fits                 → cpu   (slow but safe)
    """
    usable = max(free_gb - _VRAM_SAFETY_MARGIN_GB, 0.0)
    sizes  = _MODEL_SIZE_GB.get(model_name)
    if sizes is None:
        # Unknown model — assume fp16 if plenty of VRAM, else nf4
        return "fp16" if free_gb >= 20.0 else "nf4"
    fp16_gb, nf4_gb = sizes
    if fp16_gb <= usable:
        return "fp16"
    if nf4_gb <= usable:
        return "nf4"
    return "cpu"


def _pick_model(requested: str, free_gb: float) -> str:
    """Auto-downgrade model if it won't fit even in nf4."""
    usable = max(free_gb - _VRAM_SAFETY_MARGIN_GB, 0.0)
    sizes  = _MODEL_SIZE_GB.get(requested)
    nf4_gb = sizes[1] if sizes else 0.0

    if sizes is None or nf4_gb <= usable:
        return requested   # fits — use as requested

    for candidate in reversed(_FALLBACK_LADDER):
        c_sizes = _MODEL_SIZE_GB.get(candidate)
        if c_sizes and c_sizes[1] <= usable:
            print(
                f"[LLM client]  '{requested}' needs ~{nf4_gb:.1f}GB (nf4) "
                f"but only {usable:.1f}GB usable → downgraded to '{candidate}'",
                flush=True,
            )
            return candidate

    fallback = _FALLBACK_LADDER[0]
    print(f"[LLM client]  Not enough VRAM → CPU fallback with '{fallback}'", flush=True)
    return fallback


# ═══════════════════════════════════════════════════════════════════════════════
# LLM CLIENT CLASS
# ═══════════════════════════════════════════════════════════════════════════════
class LLMClient:
    """
    Unified LLM client. Load once, call as many times as needed.

    HF models stay resident in VRAM between calls — no reload overhead.
    API providers are stateless (just HTTP) so no special handling needed.
    """

    def __init__(self, provider: str, model: str, api_key: str, base_url: str):
        self.provider = provider
        self.model    = model
        self.api_key  = api_key
        self.base_url = base_url.rstrip("/")

        # HF state — populated on first call, reused on all subsequent calls
        self._hf_model     = None
        self._hf_tokenizer = None

        print(f"[LLM client] LLMClient ready → provider={provider} | model={model}", flush=True)

    # ── Public interface ──────────────────────────────────────────────────────
    def call(self, system: str, prompt: str) -> str:
        """
        Send a single system+user turn to the configured LLM.
        Always returns a plain string (JSON or otherwise).
        """
        p = self.provider
        if   p == "anthropic": return self._anthropic(system, prompt)
        elif p == "openai":    return self._openai(system, prompt)
        elif p == "gemini":    return self._gemini(system, prompt)
        elif p == "ollama":    return self._ollama(system, prompt)
        elif p == "sarvam":    return self._sarvam(system, prompt)
        elif p in ("hf", "hf-local"): return self._hf(system, prompt)
        elif p == "mock":      return "{}"
        else: raise ValueError(f"Unknown provider: {p}")

    # ── API callers ───────────────────────────────────────────────────────────
    def _anthropic(self, system: str, prompt: str) -> str:
        resp = _post(
            f"{self.base_url}/v1/messages",
            {
                "model": self.model,
                "max_tokens": _MAX_TOKENS["anthropic"],
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            {"anthropic-version": "2023-06-01", "x-api-key": self.api_key},
        )
        return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")

    def _openai(self, system: str, prompt: str) -> str:
        resp = _post(
            f"{self.base_url}/v1/chat/completions",
            {
                "model": self.model,
                "max_tokens": _MAX_TOKENS["openai"],
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
            },
            {"Authorization": f"Bearer {self.api_key}"},
        )
        return resp["choices"][0]["message"]["content"]

    def _gemini(self, system: str, prompt: str) -> str:
        resp = _post(
            f"{self.base_url}/v1beta/models/{self.model}:generateContent?key={self.api_key}",
            {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens":  _MAX_TOKENS["gemini"],
                    "responseMimeType": "application/json",
                },
            },
            {},
        )
        return resp["candidates"][0]["content"]["parts"][0]["text"]

    def _ollama(self, system: str, prompt: str) -> str:
        resp = _post(
            f"{self.base_url}/api/chat",
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
            },
            {},
        )
        return resp["message"]["content"]

    def _sarvam(self, system: str, prompt: str) -> str:
        """
        Sarvam AI chat completions.
        Docs: https://docs.sarvam.ai
        Auth: api-subscription-key header (your LLM_API_KEY value).
        The system prompt is prepended as a system-role message.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = _post(
            f"{self.base_url}/v1/chat/completions",
            {
                "model":      self.model,
                "messages":   messages,
                "max_tokens": _MAX_TOKENS["sarvam"],
                "temperature": 0.3,
                "top_p":      1,
            },
            {"api-subscription-key": self.api_key},
        )
        return resp["choices"][0]["message"]["content"]

    # ── HF local inference — model loaded once, reused forever ───────────────
    def _hf_ensure_loaded(self):
        """Load model + tokenizer into VRAM if not already loaded."""
        if self._hf_model is not None:
            return  # already loaded — skip entirely

        # Reserve NVIDIA GPU for AI, push display to iGPU
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
        os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
        os.environ.setdefault("DRI_PRIME", "0")
        os.environ.setdefault("__NV_PRIME_RENDER_OFFLOAD", "0")
        os.environ.setdefault("__GLX_VENDOR_LIBRARY_NAME", "mesa")

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            raise RuntimeError("Run: pip install transformers torch accelerate")

        _purge_vram()
        free_gb, total_gb = _vram_info()
        print(f"[LLM client] VRAM: {free_gb:.1f}GB free / {total_gb:.1f}GB total", flush=True)

        model_name = _pick_model(self.model, free_gb)
        cache_dir  = self.base_url or os.environ.get("HF_CACHE_DIR", "") or None

        # Resolve / download model
        try:
            from huggingface_hub import snapshot_download
            print(f"Resolving: {model_name}", flush=True)
            model_path = snapshot_download(
                repo_id=model_name, cache_dir=cache_dir,
                local_files_only=False, resume_download=True,
            )
            print(f"[LLM client]  Model path: {model_path}", flush=True)
        except ImportError:
            model_path = model_name  # fall back to HF hub auto-download

        print(f"[LLM client] Loading tokenizer...", flush=True)
        self._hf_tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        # Re-read VRAM after tokenizer (it allocates a small amount)
        free_gb, _ = _vram_info()
        usable    = max(free_gb - _VRAM_SAFETY_MARGIN_GB, 0.0)
        precision = _pick_precision(model_name, free_gb)

        if precision == "fp16":
            print(f"[LLM client] Strategy: FP16 full precision ({free_gb:.1f}GB free, {usable:.1f}GB usable)", flush=True)
            self._hf_model = AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype=torch.float16,
                device_map="auto",
                trust_remote_code=True,
            )

        elif precision == "cpu":
            print(f"[LLM client] Strategy: CPU-only float32 (< 0.5GB VRAM free)", flush=True)
            self._hf_model = AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype=torch.float32,
                device_map={"": "cpu"},
                trust_remote_code=True,
            )

        else:  # nf4
            print(f"[LLM client]  Strategy: 4-bit NF4, GPU cap={usable:.1f}GB, overflow→CPU RAM", flush=True)
            try:
                from transformers import BitsAndBytesConfig
            except ImportError:
                raise RuntimeError("Run: pip install bitsandbytes")
            bnb = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
            self._hf_model = AutoModelForCausalLM.from_pretrained(
                model_path,
                quantization_config=bnb,
                device_map="auto",
                max_memory={0: f"{usable:.1f}GiB", "cpu": "32GiB"},
                trust_remote_code=True,
            )

        try:
            device = next(self._hf_model.parameters()).device
        except Exception:
            device = "unknown"
        print(f"[LLM client]  Model loaded on {device} — will reuse for all subsequent calls", flush=True)

    def _hf(self, system: str, prompt: str) -> str:
        import torch

        self._hf_ensure_loaded()  # no-op if already loaded

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ]
        try:
            text = self._hf_tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
        except TypeError:
            text = self._hf_tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )

        inputs = self._hf_tokenizer([text], return_tensors="pt").to(self._hf_model.device)

        free_gb = _vram_info()[0]
        # Hard floor on tiny GPUs to avoid OOM during generation
        if free_gb < 2.0:
            max_new_toks = 256
        elif free_gb < 6.0:
            max_new_toks = 1024
        else:
            # Large GPU (RunPod 48GB etc.) — use full configured limit
            key = "hf-local" if self.provider == "hf-local" else "hf"
            max_new_toks = int(os.environ.get("LLM_MAX_TOKENS", _MAX_TOKENS[key]))

        with torch.no_grad():
            generated_ids = self._hf_model.generate(
                **inputs,
                max_new_tokens=max_new_toks,
                temperature=0.3,
                top_p=0.9,
                top_k=40,
                do_sample=True,
                pad_token_id=self._hf_tokenizer.eos_token_id,
            )

        output_ids = generated_ids[0][len(inputs.input_ids[0]):]
        output     = self._hf_tokenizer.decode(output_ids, skip_special_tokens=True).strip()

        del inputs, generated_ids, output_ids
        _purge_vram()

        # Strip markdown fences + Qwen3 <think> blocks
        output = re.sub(r"```json\s*|```\s*", "", output).strip()
        output = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL).strip()
        return output

    def __repr__(self):
        loaded = " [model loaded]" if self._hf_model is not None else ""
        return f"LLMClient(provider={self.provider!r}, model={self.model!r}{loaded})"


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON FACTORY
# ═══════════════════════════════════════════════════════════════════════════════
_instance: LLMClient | None = None


def get_client(
    provider:   str = None,
    model:      str = None,
    api_key:    str = None,
    base_url:   str = None,
    max_tokens: int = None,
) -> LLMClient:
    """
    Return the shared LLMClient instance. Creates it on first call, returns
    the same object on every subsequent call — model stays loaded in VRAM.

    Args are read from env vars if not provided:
        LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL, LLM_MAX_TOKENS

    RunPod 48GB example:
        client = get_client(provider="hf", model="Qwen/Qwen3-14B", max_tokens=8192)

    Sarvam AI example:
        client = get_client(provider="sarvam", model="sarvam-105b")
        # Set LLM_API_KEY to your api-subscription-key

    To force a new client (e.g. different model mid-run), call reset_client()
    first, then get_client() again.
    """
    global _instance

    provider = (provider or settings.LLM_PROVIDER).lower()
    if provider not in _PROVIDER_DEFAULTS:
        raise ValueError(f"Unknown provider '{provider}'. Choose: {list(_PROVIDER_DEFAULTS)}")

    defaults = _PROVIDER_DEFAULTS[provider]
    model    = model    or settings.LLM_MODEL      or defaults["model"]
    api_key  = api_key  or settings.LLM_API_KEY
    base_url = base_url or settings.LLM_BASE_URL   or defaults["base_url"]

    # max_tokens: explicit arg > .env > hardcoded default
    resolved_max = max_tokens or settings.LLM_MAX_TOKENS
    if resolved_max:
        key = "hf-local" if provider == "hf-local" else provider
        if key in _MAX_TOKENS:
            _MAX_TOKENS[key] = resolved_max
            os.environ["LLM_MAX_TOKENS"] = str(resolved_max)

    if provider not in ("ollama", "hf", "hf-local", "mock") and not api_key:
        raise RuntimeError(f"No API key for '{provider}'. Set LLM_API_KEY env var.")

    # Return existing instance if provider+model match
    if _instance is not None:
        if _instance.provider == provider and _instance.model == model:
            return _instance
        # Different config requested — warn and replace
        print(f"[LLM client] LLMClient config changed ({_instance.provider}/{_instance.model} → {provider}/{model}). Replacing instance.", flush=True)
        reset_client()

    _instance = LLMClient(provider, model, api_key, base_url)
    return _instance


def reset_client():
    """
    Destroy the current singleton and free VRAM.
    Call this if you need to switch providers/models mid-run.
    """
    global _instance
    if _instance is not None:
        if _instance._hf_model is not None:
            print("[LLM client]  Unloading HF model from VRAM...", flush=True)
            del _instance._hf_model
            del _instance._hf_tokenizer
            _purge_vram()
        _instance = None
        print("[LLM client]  LLMClient reset.", flush=True)