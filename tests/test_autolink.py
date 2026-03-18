"""Tests for auto-wikilink insertion."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.autolink import AutoLinker, AutolinkResult, VaultIndex, WikilinkSuggestion


def _mock_graph():
    """Build a small test graph: Essentialism -> Courage, Courage -> Duty."""
    import networkx as nx

    g = nx.MultiDiGraph()
    g.add_edge("Essentialism", "Courage is the first virtue")
    g.add_edge("Courage is the first virtue", "A Man's Duty")
    g.add_edge("A Man's Duty", "Essentialism")
    g.add_node("Home")
    g.add_node("MATH 1554 Linear Algebra")
    return g


@pytest.fixture
def sample_index():
    return VaultIndex(
        titles=[
            "Essentialism",
            "Courage is the first virtue",
            "A Man's Duty",
            "Home",
            "MATH 1554 Linear Algebra",
        ],
        title_to_path={
            "Essentialism": "04_Resources/00_Atoms/Essentialism.md",
            "Courage is the first virtue": "04_Resources/00_Atoms/Courage is the first virtue.md",
            "A Man's Duty": "04_Resources/00_Atoms/A Man's Duty.md",
            "Home": "04_Resources/00_Atoms/Home.md",
            "MATH 1554 Linear Algebra": "04_Resources/00_Atoms/MATH 1554 Linear Algebra.md",
        },
        existing_links={
            "Essentialism": ["Courage is the first virtue"],
            "Courage is the first virtue": ["Essentialism"],
            "A Man's Duty": [],
            "Home": ["Essentialism", "Courage is the first virtue"],
            "MATH 1554 Linear Algebra": [],
        },
        graph=_mock_graph(),
        tags_index={
            "Essentialism": ["philosophy"],
            "Courage is the first virtue": ["philosophy", "virtue"],
            "A Man's Duty": ["philosophy", "virtue"],
            "Home": [],
            "MATH 1554 Linear Algebra": ["academic"],
        },
    )


def _make_linker():
    """Create an AutoLinker without calling __init__."""
    linker = AutoLinker.__new__(AutoLinker)
    linker.vault_path = Path("/fake/vault")
    linker.api_base = "https://127.0.0.1:27124"
    linker.api_key = "fake-key"
    linker.max_suggestions = 8
    linker.min_confidence = "medium"
    linker.skip_folders = [".obsidian", ".smart-env", ".trash", "05_Utils", "06_Archive"]
    linker.client = MagicMock()
    linker.model = "claude-sonnet-4-20250514"
    return linker


def _mock_claude_response(text: str) -> MagicMock:
    """Create a mock Anthropic response."""
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


class TestFindCandidates:
    def test_title_match_surfaces_candidate(self, sample_index):
        linker = _make_linker()
        content = "This note is about essentialism and focus."
        candidates = linker.find_candidates(content, "TestNote", sample_index)
        assert "Essentialism" in candidates

    def test_graph_walk_finds_friends_of_friends(self, sample_index):
        """Note links to Essentialism -> walk finds Courage (1 hop)."""
        linker = _make_linker()
        # Pretend this note already links to Essentialism
        sample_index.existing_links["MyNote"] = ["Essentialism"]
        content = "Some unrelated content with no title matches."
        candidates = linker.find_candidates(content, "MyNote", sample_index)
        # Courage is 1 hop from Essentialism
        assert "Courage is the first virtue" in candidates

    def test_tag_overlap_surfaces_candidate(self, sample_index):
        linker = _make_linker()
        sample_index.tags_index["MyNote"] = ["philosophy"]
        content = "Some content."
        candidates = linker.find_candidates(content, "MyNote", sample_index)
        # Essentialism, Courage, Duty all share "philosophy" tag
        assert any(
            t in candidates
            for t in ["Essentialism", "Courage is the first virtue", "A Man's Duty"]
        )

    def test_skips_self(self, sample_index):
        linker = _make_linker()
        content = "This is about Essentialism."
        candidates = linker.find_candidates(content, "Essentialism", sample_index)
        assert "Essentialism" not in candidates

    def test_skips_tiny_titles(self, sample_index):
        """Titles shorter than 3 chars are noise, should be skipped in title scan."""
        linker = _make_linker()
        sample_index.titles.append("AI")
        sample_index.title_to_path["AI"] = "04_Resources/00_Atoms/AI.md"
        content = "This note mentions AI everywhere."
        candidates = linker.find_candidates(content, "TestNote", sample_index)
        # AI should not surface from title scan (too short)
        assert "AI" not in candidates or candidates.index("AI") > 5


class TestInsertWikilinks:
    def setup_method(self):
        self.linker = _make_linker()

    def test_basic_insertion(self):
        content = "This note discusses essentialism as a core philosophy."
        suggestions = [
            WikilinkSuggestion("Essentialism", "essentialism", "high", "direct ref")
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        assert "[[essentialism]]" in result

    def test_already_linked_skipped(self):
        content = "This discusses [[essentialism]] in depth."
        suggestions = [
            WikilinkSuggestion("Essentialism", "essentialism", "high", "direct ref")
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        assert result == content

    def test_case_insensitive_match(self):
        content = "The idea of Essentialism changed everything."
        suggestions = [
            WikilinkSuggestion("Essentialism", "essentialism", "high", "ref")
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        assert "[[Essentialism]]" in result

    def test_no_double_wrap(self):
        content = "Discusses [[Essentialism]] as a philosophy."
        suggestions = [
            WikilinkSuggestion("Essentialism", "Essentialism", "high", "ref")
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        assert result.count("[[") == 1

    def test_title_differs_from_phrase(self):
        content = "Having courage means acting despite fear."
        suggestions = [
            WikilinkSuggestion(
                "Courage is the first virtue", "courage", "high", "ref"
            )
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        assert "[[Courage is the first virtue|courage]]" in result


class TestInsertWikilinksEdgeCases:
    def setup_method(self):
        self.linker = _make_linker()

    def test_frontmatter_not_modified(self):
        """YAML frontmatter containing matching terms is not touched."""
        content = "---\ntitle: Notes on Essentialism\ntags: [essentialism]\n---\n\nThis is about essentialism."
        suggestions = [
            WikilinkSuggestion("Essentialism", "essentialism", "high", "ref")
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        # Frontmatter should be untouched
        assert result.startswith("---\ntitle: Notes on Essentialism\ntags: [essentialism]\n---")
        # Body should have the link
        assert "[[essentialism]]" in result.split("---", 2)[2]

    def test_multiple_insertions(self):
        """Two suggestions both insert correctly without interfering."""
        content = "This covers essentialism and courage in depth."
        suggestions = [
            WikilinkSuggestion("Essentialism", "essentialism", "high", "ref"),
            WikilinkSuggestion("Courage is the first virtue", "courage", "high", "ref"),
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        assert "[[essentialism]]" in result
        assert "[[Courage is the first virtue|courage]]" in result

    def test_existing_link_with_alias_not_double_wrapped(self):
        """Content with [[Title|phrase]] is not re-linked."""
        content = "This discusses [[Essentialism|the essentialist approach]] thoroughly."
        suggestions = [
            WikilinkSuggestion("Essentialism", "the essentialist approach", "high", "ref")
        ]
        result = self.linker.insert_wikilinks(content, suggestions)
        assert result == content  # Unchanged


class TestSuggestWikilinks:
    def test_mock_claude_response(self, sample_index):
        linker = _make_linker()
        linker.client.messages.create.return_value = _mock_claude_response(
            json.dumps([
                {
                    "target_title": "Essentialism",
                    "anchor_phrase": "essentialism",
                    "confidence": "high",
                    "reason": "direct reference",
                },
                {
                    "target_title": "A Man's Duty",
                    "anchor_phrase": "duty",
                    "confidence": "medium",
                    "reason": "thematic connection",
                },
            ])
        )

        suggestions = linker.suggest_wikilinks(
            "A note about essentialism and duty.", sample_index, note_stem="TestNote"
        )
        assert len(suggestions) == 2
        assert suggestions[0].target_title == "Essentialism"
        assert suggestions[1].target_title == "A Man's Duty"

    def test_filters_low_confidence(self, sample_index):
        linker = _make_linker()
        linker.client.messages.create.return_value = _mock_claude_response(
            json.dumps([
                {
                    "target_title": "Essentialism",
                    "anchor_phrase": "essentialism",
                    "confidence": "high",
                    "reason": "direct",
                },
                {
                    "target_title": "MATH 1554 Linear Algebra",
                    "anchor_phrase": "math",
                    "confidence": "low",
                    "reason": "tangential",
                },
            ])
        )

        suggestions = linker.suggest_wikilinks(
            "About essentialism and math.", sample_index, note_stem="TestNote"
        )
        assert len(suggestions) == 1
        assert suggestions[0].target_title == "Essentialism"


class TestAutolinkNote:
    @patch("src.autolink.httpx")
    def test_dry_run(self, mock_httpx, sample_index):
        linker = _make_linker()

        mock_httpx.get.return_value = MagicMock(status_code=200)
        mock_httpx.ConnectError = ConnectionError

        linker.client.messages.create.return_value = _mock_claude_response(
            json.dumps([
                {
                    "target_title": "Essentialism",
                    "anchor_phrase": "essentialism",
                    "confidence": "high",
                    "reason": "direct",
                }
            ])
        )

        with patch.object(
            linker, "build_vault_index", return_value=sample_index
        ), patch.object(
            linker,
            "get_note_content",
            return_value="Some note content about essentialism.",
        ):
            result = linker.autolink_note("01_Capture/test.md", dry_run=True)

        assert result.success is True
        assert result.links_added == 0
        assert len(result.suggestions) == 1
        mock_httpx.put.assert_not_called()


class TestSuggestWikilinksEdgeCases:
    def test_malformed_claude_response_returns_empty(self, sample_index):
        linker = _make_linker()
        linker.client.messages.create.return_value = _mock_claude_response(
            "not valid json at all"
        )
        suggestions = linker.suggest_wikilinks(
            "About essentialism.", sample_index, note_stem="TestNote"
        )
        assert suggestions == []

    def test_empty_candidates_skips_claude(self, sample_index):
        linker = _make_linker()
        # Content with no title matches, no tags, no graph links
        suggestions = linker.suggest_wikilinks(
            "Completely unrelated content xyz.", sample_index, note_stem="Unrelated"
        )
        assert suggestions == []
        linker.client.messages.create.assert_not_called()


class TestAutolinkNoteErrors:
    @patch("src.autolink.httpx")
    def test_api_unreachable_returns_error(self, mock_httpx):
        linker = _make_linker()
        mock_httpx.ConnectError = ConnectionError
        mock_httpx.get.side_effect = ConnectionError("refused")

        result = linker.autolink_note("01_Capture/test.md")
        assert result.success is False
        assert "not reachable" in result.error

    @patch("src.autolink.httpx")
    def test_live_write_calls_update(self, mock_httpx, sample_index):
        linker = _make_linker()
        mock_httpx.get.return_value = MagicMock(status_code=200)
        mock_httpx.ConnectError = ConnectionError

        linker.client.messages.create.return_value = _mock_claude_response(
            json.dumps([
                {
                    "target_title": "Essentialism",
                    "anchor_phrase": "essentialism",
                    "confidence": "high",
                    "reason": "direct",
                }
            ])
        )

        with patch.object(
            linker, "build_vault_index", return_value=sample_index
        ), patch.object(
            linker,
            "get_note_content",
            return_value="Some content about essentialism.",
        ), patch.object(
            linker, "update_note", return_value=True
        ) as mock_update:
            result = linker.autolink_note("01_Capture/test.md", dry_run=False)

        assert result.success is True
        assert result.links_added > 0
        mock_update.assert_called_once()


class TestVaultIndex:
    def test_excludes_skip_folders(self):
        linker = _make_linker()

        mock_vault = MagicMock()
        mock_vault.md_file_index = {
            "Good Note": Path("04_Resources/00_Atoms/Good Note.md"),
            "Template": Path("05_Utils/Templates/Template.md"),
            "Trash Note": Path(".trash/Old.md"),
        }
        mock_vault.get_wikilinks.return_value = []
        mock_vault.tags_index = {}

        with patch("obsidiantools.api.Vault") as MockVault:
            mock_chain = MockVault.return_value.connect.return_value.gather
            mock_chain.return_value = mock_vault
            index = linker.build_vault_index()

        assert "Good Note" in index.titles
        assert "Template" not in index.titles
        assert "Trash Note" not in index.titles
