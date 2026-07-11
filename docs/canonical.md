# canonicalize_messages: Practical Guide

`pbom` emitter APIs (`commit()` and `record()`) take two separate strings: `system_prompt` and `user_prompt`. But most real LLM call sites store prompts as a message list like `[{role, content}, ...]`. `canonicalize_messages()` is the built-in bridge from that message-list shape to the two-string shape PBOM expects.

Why this matters: PBOM hashes prompt text. If different teams write different "message-to-strings" converters, the same conversation can produce different hashes. That makes records harder to compare across tools and organizations. `canonicalize_messages()` gives one blessed conversion path so compatible inputs map to the same canonical shape.

## Import and basic usage

```python
from pbom import canonicalize_messages

system, user = canonicalize_messages([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
])
# system == "You are a helpful assistant."
# user   == "What is the capital of France?"
```

Then feed the result into the emitter:

```python
from pbom import PBOMEmitter, canonicalize_messages

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
]
system, user = canonicalize_messages(messages)

emitter = PBOMEmitter(application_id="my-agent")
with emitter.commit(system, user) as c:
    # ... call your LLM ...
    record = c.complete(model_id="openai/gpt-4o", response_text="Paris.")
```

## Accepted shapes (v1.0.0)

`canonicalize_messages()` in v1.0.0 accepts exactly these shapes.

### 1) System + user (common case)

```python
messages = [
    {"role": "system", "content": "<str>"},
    {"role": "user", "content": "<str>"},
]
system, user = canonicalize_messages(messages)
# returns ("<system content>", "<user content>")
```

### 2) User only (no system prompt)

```python
messages = [
    {"role": "user", "content": "<str>"},
]
system, user = canonicalize_messages(messages)
# returns ("", "<user content>")
```

The `system` string comes back empty. That is valid and simply means no system prompt was set.

### 3) Empty-string system (explicit but blank)

```python
messages = [
    {"role": "system", "content": ""},
    {"role": "user", "content": "<str>"},
]
system, user = canonicalize_messages(messages)
# returns ("", "<user content>")
```

An explicit blank system message and "no system message" end up the same way here. In both cases, the system string is empty, and the resulting hash behavior is the same.

## What's not supported yet (and what to do instead)

v1.0.0 is intentionally narrow: one system turn plus one user turn.

These shapes raise `UnsupportedMessageShapeError`:

- Multi-turn conversations (more than one user turn, or any assistant turn)
- Tool calls and function-call messages
- Non-string content (for example, content as a list of parts, or image-containing content)
- Messages with roles other than `"system"` or `"user"`
- Messages with keys other than `"role"` and `"content"`
- An empty message list
- Messages in the wrong order (user before system)

Why so strict? Because collapsing a multi-turn conversation into two fields is a semantic choice. Different collapse rules change what the hash represents. Instead of guessing a rule in v1.0.0 and baking that into hashes forever, PBOM rejects unsupported shapes for now and expands later based on real adopter needs.

Practical workaround: if your input is multi-turn or otherwise unsupported, convert it to strings yourself and pass those strings directly to `commit()` or `record()`.

```python
from pbom import PBOMEmitter

# Example: explicit, app-owned collapse rule
system_prompt = "You are a helpful assistant."
user_turns = [
    "User: What's the weather?",
    "User: Also include tomorrow.",
]
user_prompt = "\n".join(user_turns)

emitter = PBOMEmitter(application_id="my-agent")
with emitter.commit(system_prompt, user_prompt) as c:
    # ... call your LLM ...
    record = c.complete(model_id="openai/gpt-4o", response_text="...")
```

That keeps the conversion decision visible in your code.

## A note on comparability

Using `canonicalize_messages()` means the same supported input shape is converted the same way everywhere, so records remain comparable. If you roll your own converter, your hashes may diverge from records produced by other teams or tools using PBOM. When your call site fits the supported shapes, use the blessed helper.
