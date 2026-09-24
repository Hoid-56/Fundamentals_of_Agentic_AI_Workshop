"""
llm.py — THE ONLY FILE THAT KNOWS WHICH MODEL IS BEING USED.

Everything else in this project (chatbot.py, the grader, the tools) speaks the
canonical shapes defined here and nothing else. Swapping Llama -> Haiku ->
Bedrock -> Azure -> OpenAI is a change to this file and to one env var.

    LLM_BACKEND=local|anthropic|bedrock|openai
    LLM_MODEL=<model id for that backend>

Public surface — the whole contract:

    call_llm(messages, system=None, tools=None, ...) -> LLMResponse
    call_llm_many([...]) -> list[LLMResponse]

Canonical shapes:

    message   {"role": "user"|"assistant"|"tool",
               "content": str,
               "tool_calls": [ToolCall],       # assistant turns only
               "tool_call_id": str}            # tool turns only

    tool      {"name": str,
               "description": str,
               "parameters": {json schema}}

    response  LLMResponse(text, tool_calls, stop_reason, usage, raw)

Why this exists: the four providers disagree on where the system prompt goes,
what a tool schema is called, how a tool call comes back, and how a tool result
goes in. All four disagreements are absorbed here.
"""

from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from agent import config

# --------------------------------------------------------------------------
# Canonical types — FROZEN. Every backend produces these.
# --------------------------------------------------------------------------


class SetupError(RuntimeError):
    """
    A configuration problem the person running this can fix, as opposed to a
    bug. Entry points print these without a traceback, because a traceback
    teaches a new joiner nothing about a missing environment variable.
    """


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "stop"          # "stop" | "tool_use" | "max_tokens"
    usage: dict = field(default_factory=dict)
    raw: Any = None                    # provider payload, for debugging only

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def call_llm(
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
    reasoning: bool | None = None,
) -> LLMResponse:
    """
    Single completion. temperature=0.0 by default so grading is reproducible.

    `reasoning` defaults to config.ENABLE_REASONING. It is a no-op on backends
    that have no thinking mode (local Llama), and maps to extended thinking on
    Anthropic and Bedrock.
    """
    if reasoning is None:
        reasoning = config.ENABLE_REASONING
    return _backend().generate(messages, system, tools, max_tokens, temperature, reasoning)


def call_llm_many(
    requests: list[dict],
    max_workers: int = 8,
) -> list[LLMResponse]:
    """
    Many completions, order preserved.

    Each request is a kwargs dict for call_llm. The local backend batches on the
    GPU; API backends use a thread pool. The grader depends on this — 400
    sequential calls is ~8 minutes, batched it is under one.
    """
    return _backend().generate_many(requests, max_workers)


# --------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------

_BACKEND = None
_LOCK = threading.Lock()


def _backend():
    global _BACKEND
    if _BACKEND is None:
        with _LOCK:
            if _BACKEND is None:
                name = os.getenv("LLM_BACKEND", "local").lower().strip()
                choices = {
                    "local": LocalLlamaBackend,
                    "anthropic": AnthropicBackend,
                    "bedrock": BedrockBackend,
                    "openai": OpenAIBackend,
                }
                if name not in choices:
                    raise SetupError(
                        f"LLM_BACKEND={name!r} is not a backend.\n"
                        f"    Valid values: {', '.join(sorted(choices))}\n"
                        "    The workshop default is bedrock."
                    )
                _BACKEND = choices[name]()
    return _BACKEND


def reset_backend():
    """Test hook — forces re-read of env on next call."""
    global _BACKEND
    _BACKEND = None


class Backend:
    def generate(
        self, messages, system, tools, max_tokens, temperature, reasoning=False
    ) -> LLMResponse:
        raise NotImplementedError

    def generate_many(self, requests, max_workers) -> list[LLMResponse]:
        # Default: concurrency. Overridden by local for true GPU batching.
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            return list(pool.map(lambda r: self.generate(**_fill(r)), requests))


def _fill(r: dict) -> dict:
    return {
        "messages": r["messages"],
        "system": r.get("system"),
        "tools": r.get("tools"),
        "max_tokens": r.get("max_tokens", 512),
        "temperature": r.get("temperature", 0.0),
        "reasoning": r.get("reasoning", config.ENABLE_REASONING),
    }


# --------------------------------------------------------------------------
# LOCAL — Llama 3.1 8B Instruct via transformers (development only)
# --------------------------------------------------------------------------


class LocalLlamaBackend(Backend):
    """
    Dev backend. Loads once, batches on the GPU.

    Two Llama-specific quirks handled here and nowhere else:
      1. Tool calls arrive as raw JSON text, sometimes behind <|python_tag|>.
      2. Decoder-only batching needs LEFT padding or padded rows generate junk.
    """

    def __init__(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        path = os.getenv("LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        self.tok.padding_side = "left"                     # quirk 2
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(
            path, dtype=torch.bfloat16, device_map="auto"
        )
        self.model.eval()
        self._lock = threading.Lock()

    # -- canonical -> llama ------------------------------------------------
    def _to_native(self, messages, system, tools):
        out = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            role = m["role"]
            if role == "tool":
                # The <|python_tag|> marker on the assistant turn below is what
                # actually makes Llama treat call and result as a pair. An extra
                # instruction used to be appended here as well; it leaked into
                # the model's sense of its own instructions and confounded
                # prompt-extraction tests, so it is off unless config says
                # otherwise.
                content = m["content"]
                if config.LOCAL_TOOL_RESULT_HINT:
                    content += (
                        "\n\nUse this result to answer the user's question "
                        "directly. Do not describe the function."
                    )
                out.append({"role": "ipython", "content": content})
            elif role == "assistant" and m.get("tool_calls"):
                # Llama marks its own tool calls with <|python_tag|>. Without it
                # the call and its result do not read as a pair.
                payload = json.dumps(
                    {
                        "name": m["tool_calls"][0].name,
                        "parameters": m["tool_calls"][0].arguments,
                    }
                )
                out.append({"role": "assistant", "content": f"<|python_tag|>{payload}"})
            else:
                out.append({"role": role, "content": m.get("content", "")})

        native_tools = None
        if tools:
            native_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    },
                }
                for t in tools
            ]
        return out, native_tools

    # -- llama -> canonical ------------------------------------------------
    _TAG = re.compile(r"<\|python_tag\|>|<\|eom_id\|>")
    _FENCE = re.compile(r"```(?:json)?|```")

    @staticmethod
    def _json_blocks(text: str):
        """
        Yield (start, end, parsed) for every balanced {...} / [...] block.

        Llama does not reliably emit a bare JSON object. It will happily produce
        'Sure! {"name": ...}' or obey a system-prompt format rule and prefix the
        call. Requiring the whole output to parse loses the call entirely, so we
        scan instead.
        """
        i = 0
        while i < len(text):
            if text[i] not in "{[":
                i += 1
                continue
            opener = text[i]
            closer = "}" if opener == "{" else "]"
            depth, in_str, esc = 0, False, False
            for j in range(i, len(text)):
                c = text[j]
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = not in_str
                elif not in_str:
                    if c == opener:
                        depth += 1
                    elif c == closer:
                        depth -= 1
                        if depth == 0:
                            try:
                                yield i, j + 1, json.loads(text[i : j + 1])
                            except json.JSONDecodeError:
                                pass
                            i = j
                            break
            i += 1

    def _parse(self, text: str) -> LLMResponse:
        cleaned = self._FENCE.sub("", self._TAG.sub("", text)).strip()

        calls, spans = [], []
        for start, end, obj in self._json_blocks(cleaned):
            items = obj if isinstance(obj, list) else [obj]
            found = False
            for o in items:
                if isinstance(o, dict) and "name" in o:
                    args = o.get("parameters") or o.get("arguments") or {}
                    if isinstance(args, str):          # some variants stringify
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    calls.append(
                        ToolCall(id=f"call_{len(calls)}", name=o["name"], arguments=args)
                    )
                    found = True
            if found:
                spans.append((start, end))

        if not calls:
            return LLMResponse(text=cleaned, stop_reason="stop", raw=text)

        # Strip the call out so leftover preamble does not leak to the user.
        prose = cleaned
        for start, end in reversed(spans):
            prose = prose[:start] + prose[end:]

        return LLMResponse(
            text=prose.strip(), tool_calls=calls, stop_reason="tool_use", raw=text
        )

    def _render(self, messages, system, tools) -> str:
        native, native_tools = self._to_native(messages, system, tools)
        return self.tok.apply_chat_template(
            native, tools=native_tools, tokenize=False, add_generation_prompt=True
        )

    def generate(self, messages, system, tools, max_tokens, temperature, reasoning=False):
        # Llama 3.1 8B has no thinking mode; `reasoning` is accepted and ignored
        # so the call signature stays identical across backends.
        return self._run([self._render(messages, system, tools)], max_tokens, temperature)[0]

    def generate_many(self, requests, max_workers):
        prompts = [
            self._render(r["messages"], r.get("system"), r.get("tools")) for r in requests
        ]
        max_tokens = max(r.get("max_tokens", 512) for r in requests)
        temperature = requests[0].get("temperature", 0.0)

        results, size = [], max(1, max_workers)
        for i in range(0, len(prompts), size):
            results.extend(self._run(prompts[i : i + size], max_tokens, temperature))
        return results

    def _run(self, prompts: list[str], max_tokens: int, temperature: float):
        enc = self.tok(prompts, return_tensors="pt", padding=True).to(self.model.device)
        n_in = enc["input_ids"].shape[-1]

        kwargs = dict(max_new_tokens=max_tokens, pad_token_id=self.tok.pad_token_id)
        if temperature and temperature > 0:
            kwargs.update(do_sample=True, temperature=temperature)
        else:
            kwargs.update(do_sample=False)      # greedy == reproducible

        with self._lock, self.torch.no_grad():
            out = self.model.generate(**enc, **kwargs)

        show_raw = config.verbosity() >= 2
        responses = []
        for row in out:
            text = self.tok.decode(row[n_in:], skip_special_tokens=True).strip()
            if show_raw:
                print(f"\n[raw] >>>\n{text}\n<<<\n")
            r = self._parse(text)
            r.usage = {"input_tokens": n_in, "output_tokens": len(row) - n_in}
            responses.append(r)
        return responses


# --------------------------------------------------------------------------
# ANTHROPIC — direct API
# --------------------------------------------------------------------------


# Models on which the API removed the sampling parameters. Sending temperature
# to one of these is a 400; sending it to anything else (Haiku 4.5 and older) is
# still accepted. Matched on the model id, which on Bedrock is an inference
# profile like `global.anthropic.claude-haiku-4-5-...`.
_NO_SAMPLING = (
    "opus-4-6", "opus-4-7", "opus-4-8", "opus-5",
    "sonnet-4-6", "sonnet-5",
    "fable", "mythos",
)


def _accepts_sampling(model: str) -> bool:
    return not any(marker in model for marker in _NO_SAMPLING)


class AnthropicBackend(Backend):
    def __init__(self):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.getenv("LLM_MODEL", "claude-haiku-4-5")

    def _to_native(self, messages, tools):
        out = []
        for m in messages:
            role = m["role"]
            if role == "tool":
                # Anthropic carries tool results inside a user turn.
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m["tool_call_id"],
                                "content": m["content"],
                            }
                        ],
                    }
                )
            elif role == "assistant" and m.get("tool_calls"):
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for c in m["tool_calls"]:
                    blocks.append(
                        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                    )
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": role, "content": m.get("content", "")})

        native_tools = None
        if tools:
            native_tools = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {}),
                }
                for t in tools
            ]
        return out, native_tools

    def generate(self, messages, system, tools, max_tokens, temperature, reasoning=False):
        native, native_tools = self._to_native(messages, tools)
        kwargs = dict(
            model=self.model,
            messages=native,
            max_tokens=max_tokens,
        )
        if reasoning:
            # Extended thinking requires temperature=1 and max_tokens above the
            # budget. Both are forced here rather than left to the caller.
            budget = config.REASONING_BUDGET_TOKENS
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            temperature = 1.0
            kwargs["max_tokens"] = max(max_tokens, budget + 512)
        if _accepts_sampling(self.model):
            # `temperature` stopped being a named argument of messages.create in
            # anthropic 1.0; passing it raises TypeError. The wire field still
            # exists for the models that support it, so send it through the body.
            kwargs["extra_body"] = {"temperature": temperature}
        if system:
            # Cacheable: identical across every call in a grader run.
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        if native_tools:
            kwargs["tools"] = native_tools

        resp = self.client.messages.create(**kwargs)

        text, calls = "", []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type in {"thinking", "redacted_thinking"}:
                continue          # never surfaced to the user or the grader
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return LLMResponse(
            text=text.strip(),
            tool_calls=calls,
            stop_reason="tool_use" if calls else "stop",
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
            raw=resp,
        )


# --------------------------------------------------------------------------
# BEDROCK — same wire format as Anthropic, different client + model id
# --------------------------------------------------------------------------


class BedrockBackend(AnthropicBackend):
    """
    Bedrock accepts two different kinds of credential, and the failure modes
    when you get it wrong are unhelpful enough to be worth catching here.

      A. Bedrock API key   AWS_BEARER_TOKEN_BEDROCK
                           One value. Sent as `Authorization: Bearer ...`.
                           Needs anthropic>=0.88 and does NOT need boto3.

      B. IAM credentials   AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY
                           (+ AWS_SESSION_TOKEN if temporary), or AWS_PROFILE.
                           Signed with SigV4. Needs boto3.

    The two are mutually exclusive: the SDK raises "Cannot specify both
    `api_key` and AWS credentials" if you hand it both. We pick A when a
    bearer token is present and say so, rather than letting the SDK guess.
    """

    MIN_SDK = (0, 88, 0)

    def __init__(self):
        try:
            import anthropic
            from anthropic import AnthropicBedrock
        except ImportError as exc:
            raise SetupError(
                "The `anthropic` package is not installed.\n"
                "    Fix:  pip install -r requirements.txt"
            ) from exc

        token = (os.getenv("AWS_BEARER_TOKEN_BEDROCK") or "").strip()
        access_key = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
        profile = (os.getenv("AWS_PROFILE") or "").strip()
        region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()

        if not region:
            raise SetupError(
                "No AWS region set, and the SDK will not guess one.\n"
                "    Fix:  add AWS_REGION=us-east-1 to your .env "
                "(use the region your Bedrock access is in)."
            )

        if not token and not access_key and not profile:
            raise SetupError(
                "No Bedrock credentials found.\n"
                "    Set ONE of these in your .env:\n"
                "      AWS_BEARER_TOKEN_BEDROCK=...   (a Bedrock API key)\n"
                "      AWS_ACCESS_KEY_ID=... plus AWS_SECRET_ACCESS_KEY=...\n"
                "      AWS_PROFILE=...                (a profile in ~/.aws/credentials)\n"
                "    If you did set one, your .env is probably not being read: it must\n"
                "    sit in the repository root, next to run_grader.py."
            )

        if token:
            installed = _sdk_version(anthropic)
            if installed < self.MIN_SDK:
                raise SetupError(
                    f"anthropic {_v(installed)} is installed, but Bedrock API key "
                    f"(bearer token) support arrived in {_v(self.MIN_SDK)}.\n"
                    "    On this version AWS_BEARER_TOKEN_BEDROCK is ignored and you get\n"
                    "    a credentials error that names nothing useful.\n"
                    "    Fix:  pip install -U 'anthropic>=0.88'"
                )
            # Pass it explicitly. Relying on the env var means a stray
            # AWS_ACCESS_KEY_ID in the shell can silently take precedence.
            self.client = AnthropicBedrock(api_key=token, aws_region=region)
            self.auth_mode = "bedrock api key"
        else:
            if access_key and not os.getenv("AWS_SECRET_ACCESS_KEY"):
                raise SetupError(
                    "AWS_ACCESS_KEY_ID is set but AWS_SECRET_ACCESS_KEY is not.\n"
                    "    Fix:  set both, or switch to AWS_BEARER_TOKEN_BEDROCK."
                )
            try:
                import boto3  # noqa: F401
            except ImportError as exc:
                raise SetupError(
                    "IAM credentials need boto3 to sign requests, and it is not "
                    "installed.\n"
                    "    Fix:  pip install boto3\n"
                    "    Or:   use a Bedrock API key instead, which needs no boto3."
                ) from exc
            self.client = AnthropicBedrock(aws_region=region)
            self.auth_mode = f"iam sigv4 ({'profile ' + profile if profile else 'env keys'})"

        self.region = region
        # NOTE: bare model ids fail on Bedrock with "on-demand throughput isn't
        # supported". Must be an inference profile id or full ARN.
        self.model = os.getenv(
            "LLM_MODEL", "global.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    def generate(self, *args, **kwargs):
        try:
            return super().generate(*args, **kwargs)
        except SetupError:
            raise
        except Exception as exc:  # noqa: BLE001 — translate, then re-raise
            raise _translate_bedrock_error(exc, self.model, self.region) from exc


def _sdk_version(module) -> tuple:
    raw = getattr(module, "__version__", "0.0.0")
    parts = []
    for chunk in str(raw).split(".")[:3]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _v(version: tuple) -> str:
    return ".".join(str(p) for p in version)


def _translate_bedrock_error(exc: Exception, model: str, region: str) -> Exception:
    """
    Turn the four failures every new joiner hits into instructions. The
    original exception is preserved as __cause__ for anyone who wants it.
    """
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()

    if "could not resolve credentials" in low or "nocredentials" in low:
        return SetupError(
            "Bedrock rejected the request because it found no usable credentials.\n"
            "    Most likely: your .env is not being read, or the key is empty.\n"
            "    Check:  python -m scripts.doctor\n"
            f"    Original: {text}"
        )
    if "expiredtoken" in low or "the security token included in the request is expired" in low:
        return SetupError(
            "Your credentials have expired.\n"
            "    Short-term Bedrock API keys last at most 12 hours, and SSO/temporary\n"
            "    IAM credentials are usually shorter.\n"
            "    Fix:  generate a new key and update .env.\n"
            f"    Original: {text}"
        )
    if "unrecognizedclient" in low or ("invalid" in low and "token" in low):
        return SetupError(
            "Bedrock rejected the credential itself.\n"
            "    Usually a truncated paste — a Bedrock API key is long and easy to\n"
            "    clip. Re-copy it, and check there are no quotes or spaces in .env.\n"
            f"    Original: {text}"
        )
    if "on-demand throughput" in low or "isn't supported" in low or "isnt supported" in low:
        return SetupError(
            f"Bedrock will not serve the bare model id {model!r}.\n"
            "    It needs an inference profile id or a full ARN.\n"
            "    Fix:  LLM_MODEL=global.anthropic.claude-haiku-4-5-20251001-v1:0\n"
            f"    Original: {text}"
        )
    if "accessdenied" in low or "not authorized" in low:
        return SetupError(
            f"Your credentials work, but this account may not use {model!r} in "
            f"{region}.\n"
            "    Usually model access has not been enabled, or the IAM policy is\n"
            "    missing bedrock:InvokeModel.\n"
            "    Check with whoever issued the key.\n"
            f"    Original: {text}"
        )
    if "throttl" in low or "too many requests" in low:
        return SetupError(
            "Bedrock is throttling this account.\n"
            "    Lower the concurrency:  python run_grader.py --full --workers 2\n"
            f"    Original: {text}"
        )
    if "could not connect" in low or "connection" in low or "ssl" in low:
        return SetupError(
            "Could not reach Bedrock over the network.\n"
            "    On a corporate network this is usually the proxy or TLS inspection.\n"
            f"    Original: {text}"
        )
    return exc


# --------------------------------------------------------------------------
# OPENAI / AZURE — the "last minute change" insurance
# --------------------------------------------------------------------------


class OpenAIBackend(Backend):
    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    def generate(self, messages, system, tools, max_tokens, temperature, reasoning=False):
        native = []
        if system:
            native.append({"role": "system", "content": system})
        for m in messages:
            if m["role"] == "tool":
                native.append(
                    {
                        "role": "tool",
                        "tool_call_id": m["tool_call_id"],
                        "content": m["content"],
                    }
                )
            elif m["role"] == "assistant" and m.get("tool_calls"):
                native.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {
                                    "name": c.name,
                                    "arguments": json.dumps(c.arguments),
                                },
                            }
                            for c in m["tool_calls"]
                        ],
                    }
                )
            else:
                native.append({"role": m["role"], "content": m.get("content", "")})

        kwargs = dict(
            model=self.model,
            messages=native,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    },
                }
                for t in tools
            ]

        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        calls = []
        for c in msg.tool_calls or []:
            # OpenAI hands back arguments as a JSON *string*, not a dict.
            calls.append(
                ToolCall(
                    id=c.id,
                    name=c.function.name,
                    arguments=json.loads(c.function.arguments or "{}"),
                )
            )

        return LLMResponse(
            text=(msg.content or "").strip(),
            tool_calls=calls,
            stop_reason="tool_use" if calls else "stop",
            usage={
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
            },
            raw=resp,
        )
