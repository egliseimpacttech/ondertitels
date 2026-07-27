# tests/test_config.py
import pytest
from backend.config import validate_config, ELEVENLABS_API_KEY, DEEPL_API_KEY, OPENAI_API_KEY

#heel dit is om te voorkomen dat een lang proces gaande is, en pas op het einde te weten komen dat iets niet goed is
def test_config_validation():
    # nagaan of API sleutels in ENV zijn 
    try:
        validate_config()
    except SystemExit:
        pytest.fail("Config validation failed - check your .env file")


def test_api_keys_loaded():
    # of Elevenlabs in orde is 
    assert ELEVENLABS_API_KEY, "ELEVENLABS_API_KEY should be set"

    #minstens een van de vertaal APIS is beschikbaar 
    has_translation = bool(DEEPL_API_KEY or OPENAI_API_KEY)
    assert has_translation, "At least one translation API key should be set"


# tests/test_translation.py
import pytest
from backend.translation import translate_segments, _translate_deepl, _translate_openai
from backend.config import DEEPL_API_KEY, OPENAI_API_KEY


def test_translate_segments_empty():
    #vertaling uittettesten met lege segmenten 
    result = translate_segments([], "en", "", DEEPL_API_KEY, OPENAI_API_KEY)
    assert result == []


def test_translate_segments_no_api_keys():
    segments = [{"text": "Hello world"}]

    with pytest.raises(ValueError, match="No translation API available"):
        translate_segments(segments, "invalid_lang", "", "", "")


@pytest.mark.skipif(not DEEPL_API_KEY, reason="DeepL API key not available")
def test_deepl_translation():
    """Test DeepL translation with a simple text."""
    texts = ["Hello world"]
    result = _translate_deepl(texts, "nl", "", DEEPL_API_KEY)

    assert len(result) == 1
    assert result[0] != "Hello world"  


@pytest.mark.skipif(not OPENAI_API_KEY, reason="OpenAI API key not available")
def test_openai_translation():
    """Test OpenAI translation with a simple text."""
    texts = ["Hello world"]
    result = _translate_openai(texts, "mg", "", OPENAI_API_KEY)

    assert len(result) == 1
    assert result[0] != "Hello world"  #zou vertaald moeten zijn