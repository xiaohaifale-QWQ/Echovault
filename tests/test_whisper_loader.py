from core.whisper_loader import _convert_hf_state_dict


def test_huggingface_parameter_names_map_to_openai_whisper():
    source = {
        "model.encoder.embed_positions.weight": "encoder-position",
        "model.encoder.layers.0.self_attn.q_proj.weight": "encoder-query",
        "model.encoder.layers.0.self_attn_layer_norm.bias": "encoder-attn-norm",
        "model.encoder.layers.0.fc1.weight": "encoder-mlp-in",
        "model.encoder.layers.0.final_layer_norm.weight": "encoder-mlp-norm",
        "model.encoder.layer_norm.weight": "encoder-final-norm",
        "model.decoder.embed_tokens.weight": "tokens",
        "model.decoder.embed_positions.weight": "decoder-position",
        "model.decoder.layers.0.encoder_attn.k_proj.weight": "cross-key",
        "model.decoder.layers.0.encoder_attn_layer_norm.bias": "cross-norm",
        "model.decoder.layer_norm.bias": "decoder-final-norm",
    }

    converted = _convert_hf_state_dict(source)

    assert converted == {
        "encoder.positional_embedding": "encoder-position",
        "encoder.blocks.0.attn.query.weight": "encoder-query",
        "encoder.blocks.0.attn_ln.bias": "encoder-attn-norm",
        "encoder.blocks.0.mlp.0.weight": "encoder-mlp-in",
        "encoder.blocks.0.mlp_ln.weight": "encoder-mlp-norm",
        "encoder.ln_post.weight": "encoder-final-norm",
        "decoder.token_embedding.weight": "tokens",
        "decoder.positional_embedding": "decoder-position",
        "decoder.blocks.0.cross_attn.key.weight": "cross-key",
        "decoder.blocks.0.cross_attn_ln.bias": "cross-norm",
        "decoder.ln.bias": "decoder-final-norm",
    }
