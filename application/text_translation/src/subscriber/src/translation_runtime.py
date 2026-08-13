"""Offline loading contract for the text-translation model and tokenizer."""

from pathlib import Path


ARTIFACT_DIR = Path("/opt/continuum/text-translation/artifacts/opus-mt-en-nl")
MODEL_FILES = ("config.json", "generation_config.json", "pytorch_model.bin")
TOKENIZER_FILES = (
    "config.json",
    "source.spm",
    "target.spm",
    "tokenizer_config.json",
    "vocab.json",
)


def _artifact_path(required_files):
    """Validate the image's fixed content-addressed artifact directory."""
    artifact_path = ARTIFACT_DIR
    missing = [filename for filename in required_files if not (artifact_path / filename).is_file()]
    if missing:
        raise RuntimeError(
            "translation artifact directory is missing required files: %s" % ", ".join(missing)
        )
    return artifact_path


def load_translation_components(model_class=None, tokenizer_class=None):
    """Load the reviewed snapshot locally and force inference onto the CPU."""
    model_path = _artifact_path(MODEL_FILES)
    tokenizer_path = _artifact_path(TOKENIZER_FILES)

    if model_class is None or tokenizer_class is None:
        # Import lazily so the path contract can be tested without ML dependencies.
        # pylint: disable-next=import-error,import-outside-toplevel
        from transformers import MarianMTModel, MarianTokenizer

        model_class = MarianMTModel
        tokenizer_class = MarianTokenizer

    try:
        model = model_class.from_pretrained(str(model_path), local_files_only=True)
        tokenizer = tokenizer_class.from_pretrained(str(tokenizer_path), local_files_only=True)
    except OSError as error:
        raise RuntimeError("unable to load the reviewed translation artifacts offline") from error

    model.eval()
    model.to("cpu")
    return model, tokenizer
