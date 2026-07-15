"""Load Whisper models from official or HuggingFace-style checkpoints."""

import os
from collections.abc import Mapping


def _convert_hf_state_dict(state_dict: Mapping[str, object]) -> dict[str, object]:
    """Convert Hugging Face Whisper parameter names to openai-whisper names."""

    exact_names = {
        "model.encoder.embed_positions.weight": "encoder.positional_embedding",
        "model.encoder.layer_norm.weight": "encoder.ln_post.weight",
        "model.encoder.layer_norm.bias": "encoder.ln_post.bias",
        "model.decoder.embed_tokens.weight": "decoder.token_embedding.weight",
        "model.decoder.embed_positions.weight": "decoder.positional_embedding",
        "model.decoder.layer_norm.weight": "decoder.ln.weight",
        "model.decoder.layer_norm.bias": "decoder.ln.bias",
    }
    replacements = (
        ("model.", ""),
        (".layers.", ".blocks."),
        (".self_attn.", ".attn."),
        (".encoder_attn.", ".cross_attn."),
        (".k_proj.", ".key."),
        (".v_proj.", ".value."),
        (".q_proj.", ".query."),
        (".out_proj.", ".out."),
        (".self_attn_layer_norm.", ".attn_ln."),
        (".encoder_attn_layer_norm.", ".cross_attn_ln."),
        (".fc1.", ".mlp.0."),
        (".fc2.", ".mlp.2."),
        (".final_layer_norm.", ".mlp_ln."),
    )

    converted = {}
    for source_name, value in state_dict.items():
        target_name = exact_names.get(source_name, source_name)
        if target_name == source_name:
            for source, target in replacements:
                target_name = target_name.replace(source, target)
        converted[target_name] = value
    return converted


def load_hf_whisper(model_name, cache_dir=None, device="cpu"):
    import torch
    import whisper

    if cache_dir is None:
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper")

    model_file = os.path.join(cache_dir, f"{model_name}.pt")
    if not os.path.exists(model_file):
        raise FileNotFoundError(f"Model not found: {model_file}")

    ckpt = torch.load(model_file, map_location="cpu")

    # Already whisper format
    if "dims" in ckpt:
        return whisper.load_model(model_name, device=device, download_root=cache_dir)

    # Infer dimensions from a Hugging Face state dict.
    conv1 = ckpt["model.encoder.conv1.weight"]
    n_mels = conv1.shape[1]
    n_audio_state = conv1.shape[0]
    n_audio_ctx = ckpt["model.encoder.embed_positions.weight"].shape[0]
    # n_audio_head: 64 dims per head for all whisper models
    n_audio_head = n_audio_state // 64

    enc_layers = {int(k.split(".")[3]) for k in ckpt if k.startswith("model.encoder.layers.")}
    dec_layers = {int(k.split(".")[3]) for k in ckpt if k.startswith("model.decoder.layers.")}
    n_audio_layer = max(enc_layers) + 1
    n_text_layer = max(dec_layers) + 1

    n_text_ctx = ckpt["model.decoder.embed_positions.weight"].shape[0]
    n_text_state = ckpt["model.decoder.layers.0.self_attn.k_proj.weight"].shape[0]
    n_text_head = n_text_state // 64

    n_vocab = ckpt["model.decoder.embed_tokens.weight"].shape[0]

    dims = whisper.model.ModelDimensions(
        n_mels=n_mels,
        n_audio_ctx=n_audio_ctx,
        n_audio_state=n_audio_state,
        n_audio_head=n_audio_head,
        n_audio_layer=n_audio_layer,
        n_text_ctx=n_text_ctx,
        n_text_state=n_text_state,
        n_text_head=n_text_head,
        n_text_layer=n_text_layer,
        n_vocab=n_vocab,
    )

    model = whisper.model.Whisper(dims)
    converted = _convert_hf_state_dict(ckpt)
    model.load_state_dict(converted, strict=True)
    return model.to(device).eval()
