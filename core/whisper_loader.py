"""Load whisper model from HF pytorch_model.bin format"""
import torch, os, re

def load_hf_whisper(model_name, cache_dir=None):
    if cache_dir is None:
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
    
    model_file = os.path.join(cache_dir, f"{model_name}.pt")
    if not os.path.exists(model_file):
        raise FileNotFoundError(f"Model not found: {model_file}")
    
    import whisper
    ckpt = torch.load(model_file, map_location="cpu")
    
    # Already whisper format
    if "dims" in ckpt:
        return whisper.load_model(model_name)
    
    # Infer dimensions from HF state dict
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
    
    n_vocab = 51865
    for k in ckpt:
        if "token_embedding" in k:
            n_vocab = ckpt[k].shape[0]; break
    
    dims = whisper.model.ModelDimensions(
        n_mels=n_mels, n_audio_ctx=n_audio_ctx, n_audio_state=n_audio_state,
        n_audio_head=n_audio_head, n_audio_layer=n_audio_layer,
        n_text_ctx=n_text_ctx, n_text_state=n_text_state,
        n_text_head=n_text_head, n_text_layer=n_text_layer, n_vocab=n_vocab)
    
    model = whisper.model.Whisper(dims)
    model.load_state_dict(ckpt, strict=False)
    return model.to("cpu")
