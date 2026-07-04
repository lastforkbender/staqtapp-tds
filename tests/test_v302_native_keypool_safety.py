from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "staqtapp_tds" / "_native_index.c"
CSS = ROOT / "src" / "staqtapp_tds" / "admin" / "static" / "css" / "dashboard.css"


def test_tiny_key_pool_allocates_small_keys_at_full_block_size():
    text = SRC.read_text()
    assert "malloc((size_t)pool->block_size)" in text
    assert "Every pointer stored in free_list is allocated with exactly" in text
    assert "return (char*)malloc((size_t)len);" in text


def test_tiny_key_pool_no_longer_allocates_pool_eligible_keys_at_exact_len():
    text = SRC.read_text()
    alloc_start = text.index("static char *key_alloc")
    free_start = text.index("static void key_free")
    key_alloc_body = text[alloc_start:free_start]
    small_branch = key_alloc_body[key_alloc_body.index("if (len <= pool->block_size)"):]
    assert "malloc((size_t)len)" not in small_branch.split("pool->allocator_calls++;\n    return (char*)malloc((size_t)len);")[0]


def test_dashboard_hero_nodes_are_not_same_position():
    css = CSS.read_text()
    assert ".node-ai{width:70px;height:70px;left:36px;top:72px" in css
    assert ".node-tds{width:86px;height:86px;left:118px;top:52px" in css
