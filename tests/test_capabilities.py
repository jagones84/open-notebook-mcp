"""Tests for the Open Notebook MCP server."""

from open_notebook_mcp.server import CAPABILITIES, search_capabilities


def test_capabilities_defined():
    """Test that all capabilities are properly defined."""
    assert len(CAPABILITIES) > 0, "No capabilities defined"

    # Check that all capabilities have required fields
    for cap in CAPABILITIES:
        assert cap.name, "Missing name for capability"
        assert cap.summary, f"Missing summary for {cap.name}"
        assert cap.tags, f"Missing tags for {cap.name}"
        assert cap.args is not None, f"Missing args for {cap.name}"
        assert cap.returns, f"Missing returns for {cap.name}"
        assert cap.example is not None, f"Missing example for {cap.name}"
        assert cap.typical_bytes > 0, f"Missing typical_bytes for {cap.name}"


def test_search_capabilities_basic():
    """Test basic search_capabilities functionality."""
    result = search_capabilities(query="", detail="name", limit=50)

    assert "request_id" in result
    assert "count" in result
    assert "matches" in result
    assert result["count"] > 0
    assert len(result["matches"]) == result["count"]


def test_search_capabilities_query():
    """Test search_capabilities with query."""
    # Search for notebook-related tools
    result = search_capabilities(query="notebook", detail="summary", limit=10)
    assert result["count"] > 0

    # All matches should have notebook-related content
    for match in result["matches"]:
        assert "name" in match
        assert "summary" in match
        assert "tags" in match


def test_search_capabilities_detail_levels():
    """Test different detail levels."""
    # Name only
    result = search_capabilities(query="", detail="name", limit=1)
    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert "name" in match
    assert "summary" not in match

    # Summary
    result = search_capabilities(query="", detail="summary", limit=1)
    match = result["matches"][0]
    assert "name" in match
    assert "summary" in match
    assert "tags" in match
    assert "args" not in match

    # Full
    result = search_capabilities(query="", detail="full", limit=1)
    match = result["matches"][0]
    assert "name" in match
    assert "summary" in match
    assert "tags" in match
    assert "args" in match
    assert "returns" in match
    assert "example" in match


def test_search_capabilities_limit():
    """Test that limit parameter is respected."""
    result = search_capabilities(query="", detail="name", limit=5)
    assert result["count"] <= 5
    assert len(result["matches"]) <= 5

    result = search_capabilities(query="", detail="name", limit=100)
    # Should be capped at 50
    assert result["count"] <= 50


def test_generate_artifact_asks_for_a_handful_of_sections():
    """A document is a book: few broad chapters, so the default must match the API."""
    import inspect

    from open_notebook_mcp.server import generate_artifact

    default = inspect.signature(generate_artifact).parameters["sections"].default
    assert default == 5


def test_generate_artifact_accepts_a_variant():
    """The kind sub-variant is part of the contract and must reach the API."""
    import inspect

    from open_notebook_mcp.server import generate_artifact

    parameters = inspect.signature(generate_artifact).parameters
    assert "variant" in parameters
    assert parameters["variant"].default is None

    capability = next(cap for cap in CAPABILITIES if cap.name == "generate_artifact")
    assert "variant" in capability.args


def test_create_source_posts_to_the_json_endpoint(monkeypatch):
    """POST /api/sources is multipart-only; the JSON contract lives at /sources/json."""
    import asyncio

    import open_notebook_mcp.server as server

    calls: dict = {}

    async def fake_request(method, path, **kwargs):
        calls["method"] = method
        calls["path"] = path
        calls["json"] = kwargs.get("json_data")
        return {"id": "source:1"}

    monkeypatch.setattr(server, "make_request", fake_request)

    result = asyncio.run(
        server.create_source(
            notebook_id="notebook:1",
            type="link",
            url="https://example.com",
            embed=False,
        )
    )

    assert calls["method"] == "POST"
    assert calls["path"] == "/api/sources/json"
    assert calls["json"]["type"] == "link"
    assert calls["json"]["embed"] is False
    assert result["source"]["id"] == "source:1"


def test_timeout_reader_accepts_a_positive_finite_value():
    """A sane OPEN_NOTEBOOK_TIMEOUT_S is read as a float."""
    from open_notebook_mcp.server import _read_timeout_s

    assert _read_timeout_s("45") == 45.0
    assert _read_timeout_s("0.5") == 0.5


def test_timeout_reader_rejects_values_httpx_would_accept():
    """Zero, negative, infinite and NaN timeouts must not reach httpx."""
    import pytest

    from open_notebook_mcp.server import _read_timeout_s

    for raw in ("0", "-1", "nan", "inf", "-inf", "abc", ""):
        with pytest.raises(ValueError):
            _read_timeout_s(raw)


def test_default_timeout_is_positive_and_finite():
    """The timeout the client actually uses must be usable."""
    import math

    from open_notebook_mcp.server import DEFAULT_TIMEOUT_S

    assert math.isfinite(DEFAULT_TIMEOUT_S)
    assert DEFAULT_TIMEOUT_S > 0


def test_ask_tools_publish_optional_models():
    """The capability metadata has to match the Optional[str] signatures."""
    for name in ("ask_question", "ask_simple"):
        capability = next(cap for cap in CAPABILITIES if cap.name == name)
        for key in ("strategy_model", "answer_model", "final_answer_model"):
            assert capability.args[key] == "Optional[str]", f"{name}.{key}"


def test_list_artifacts_defaults_to_a_small_page(monkeypatch):
    """A list tool must not dump everything: 25 by default, with a cursor."""
    import asyncio

    import open_notebook_mcp.server as server

    rows = [{"id": f"artifact:{i}", "title": f"A{i}"} for i in range(60)]

    async def fake_request(method, path, **kwargs):
        return rows

    monkeypatch.setattr(server, "make_request", fake_request)

    page = asyncio.run(server.list_artifacts())
    assert [a["id"] for a in page["artifacts"]] == [f"artifact:{i}" for i in range(25)]
    assert page["total"] == 60
    assert page["offset"] == 0
    assert page["next_offset"] == 25


def test_list_artifacts_caps_the_limit(monkeypatch):
    """The cap has to stay under the 200 ceiling of AGENTS.md 4.1."""
    import asyncio

    import open_notebook_mcp.server as server

    rows = [{"id": f"artifact:{i}"} for i in range(300)]

    async def fake_request(method, path, **kwargs):
        return rows

    monkeypatch.setattr(server, "make_request", fake_request)

    page = asyncio.run(server.list_artifacts(limit=1000))
    assert len(page["artifacts"]) == 100
    assert page["limit"] == 100


def test_list_artifacts_closes_the_cursor(monkeypatch):
    """Paging has to end: no next_offset once the list is exhausted."""
    import asyncio

    import open_notebook_mcp.server as server

    rows = [{"id": f"artifact:{i}"} for i in range(60)]

    async def fake_request(method, path, **kwargs):
        return rows

    monkeypatch.setattr(server, "make_request", fake_request)

    page = asyncio.run(server.list_artifacts(limit=25, offset=50))
    assert [a["id"] for a in page["artifacts"]] == [f"artifact:{i}" for i in range(50, 60)]
    assert page["next_offset"] is None


def test_list_artifacts_shrinks_rows_on_request(monkeypatch):
    """detail and fields exist to keep the model's context small."""
    import asyncio

    import open_notebook_mcp.server as server

    row = {
        "id": "artifact:1",
        "notebook_id": "notebook:1",
        "title": "Report",
        "kind": "report",
        "variant": "document",
        "job_status": "done",
        "created": "2026-01-01",
        "files": ["report.md"],
    }

    async def fake_request(method, path, **kwargs):
        return [row]

    monkeypatch.setattr(server, "make_request", fake_request)

    assert asyncio.run(server.list_artifacts(detail="full"))["artifacts"][0] == row
    assert asyncio.run(server.list_artifacts(detail="name"))["artifacts"][0] == {
        "id": "artifact:1",
        "title": "Report",
    }
    summary = asyncio.run(server.list_artifacts(detail="summary"))["artifacts"][0]
    assert "id" in summary and "job_status" in summary and "files" not in summary
    assert asyncio.run(server.list_artifacts(fields=["kind", "id"]))["artifacts"][0] == {
        "kind": "report",
        "id": "artifact:1",
    }


def test_list_artifacts_publishes_its_paging_knobs():
    """The capability index has to describe the knobs the tool really has."""
    capability = next(cap for cap in CAPABILITIES if cap.name == "list_artifacts")
    for key in ("notebook_id", "limit", "offset", "fields", "detail"):
        assert key in capability.args, key


if __name__ == "__main__":
    # Run tests
    test_capabilities_defined()
    print("✓ test_capabilities_defined passed")

    test_search_capabilities_basic()
    print("✓ test_search_capabilities_basic passed")

    test_search_capabilities_query()
    print("✓ test_search_capabilities_query passed")

    test_search_capabilities_detail_levels()
    print("✓ test_search_capabilities_detail_levels passed")

    test_search_capabilities_limit()
    print("✓ test_search_capabilities_limit passed")

    print("\n✅ All tests passed!")
