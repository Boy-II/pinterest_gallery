from pathlib import Path
import re


SCRIPT = Path(__file__).resolve().parent.parent / "web" / "civitai_gallery.js"


def test_civitai_gallery_uses_three_column_image_grid():
    source = SCRIPT.read_text()

    assert 'display: "grid"' in source
    assert 'gridTemplateColumns: "repeat(3, 1fr)"' in source
    assert "const THUMB_SIZE" not in source
    assert 'width: `${THUMB_SIZE}px`' not in source
    assert 'aspectRatio: "1 / 1"' in source


def test_civitai_detail_preview_only_renders_prompts():
    source = SCRIPT.read_text()
    render_detail = re.search(
        r"function renderDetail\(item\) \{(?P<body>.*?)\n    \}",
        source,
        re.DOTALL,
    ).group("body")

    assert 'item.baseModel || ""' in render_detail
    assert 'buildPromptBox("Positive Prompt", meta.prompt)' in render_detail
    assert 'buildPromptBox("Negative Prompt", meta.negativePrompt)' in render_detail
    assert "const otherKeys" not in render_detail
    assert "paramsBox" not in render_detail
    assert "此圖片未公開生成參數" not in render_detail


def test_civitai_filters_use_keyword_and_base_model_select():
    source = SCRIPT.read_text()

    assert "const keywordInput" in source
    assert 'placeholder: "Keyword"' in source
    assert "const baseModelSelect" in source
    assert '["", "All Base Models"]' in source
    assert '["Anima", "Anima"]' in source
    assert '["MiniMax H3", "MiniMax H3"]' in source
    assert '["Krea 2", "Krea 2"]' in source
    assert '["Flux.2 Klein 9B", "Flux.2 Klein 9B"]' in source
    assert 'p.set("query", keywordInput.value.trim())' in source
    assert 'p.set("baseModels", baseModelSelect.value)' in source
    assert "tagInput" not in source
    assert "usernameInput" not in source
    assert "baseModelInput" not in source


def test_civitai_grid_can_preview_video_items():
    source = SCRIPT.read_text()

    assert 'item.type === "video"' in source
    assert 'document.createElement("video")' in source
    assert "media.muted = true" in source
    assert "media.loop = true" in source
    assert "download_video: isVideoOutputConnected(node)" in source
