import unittest
from unittest.mock import patch, MagicMock
from actions.quick_knowledge import quick_knowledge, TOOL as QUICK_KNOWLEDGE_TOOL
from actions.web_search import _open_search_in_browser, TOOL as WEB_SEARCH_TOOL


class TestKnowledgeEngine(unittest.TestCase):
    def test_quick_knowledge_tool_structure(self):
        self.assertEqual(QUICK_KNOWLEDGE_TOOL["name"], "quick_knowledge")
        self.assertIn("parameters", QUICK_KNOWLEDGE_TOOL)
        self.assertIn("action", QUICK_KNOWLEDGE_TOOL["parameters"]["properties"])
        self.assertIn("query", QUICK_KNOWLEDGE_TOOL["parameters"]["properties"])
        self.assertIn("target_language", QUICK_KNOWLEDGE_TOOL["parameters"]["properties"])

    def test_quick_knowledge_empty_query(self):
        res = quick_knowledge({"action": "meaning", "query": ""})
        self.assertIn("Please specify", res)

    @patch("core.gemini.text")
    def test_quick_knowledge_meaning(self, mock_gemini_text):
        mock_gemini_text.return_value = "Ephemeral (adjective): Lasting for a very short time. Example: Fashions are ephemeral."
        res = quick_knowledge({"action": "meaning", "query": "ephemeral"})
        self.assertIn("Ephemeral", res)
        mock_gemini_text.assert_called_once()
        prompt_arg = mock_gemini_text.call_args[0][0]
        self.assertIn("ephemeral", prompt_arg)
        self.assertIn("definition", prompt_arg.lower())

    @patch("core.gemini.text")
    def test_quick_knowledge_translate(self, mock_gemini_text):
        mock_gemini_text.return_value = "සුබ උදෑසනක් (Suba Udesanak)"
        res = quick_knowledge({
            "action": "translate",
            "query": "Good morning",
            "target_language": "Sinhala",
        })
        self.assertIn("සුබ උදෑසනක්", res)
        mock_gemini_text.assert_called_once()
        prompt_arg = mock_gemini_text.call_args[0][0]
        self.assertIn("Good morning", prompt_arg)
        self.assertIn("Sinhala", prompt_arg)

    @patch("core.gemini.text")
    def test_quick_knowledge_explain(self, mock_gemini_text):
        mock_gemini_text.return_value = "Quantum computing harnesses superposition and entanglement to compute exponentially faster."
        res = quick_knowledge({
            "action": "explain",
            "query": "quantum computing",
            "detail": "concise",
        })
        self.assertIn("Quantum computing", res)
        mock_gemini_text.assert_called_once()
        prompt_arg = mock_gemini_text.call_args[0][0]
        self.assertIn("quantum computing", prompt_arg)

    @patch("subprocess.Popen")
    @patch("webbrowser.open")
    def test_web_search_does_not_open_browser_for_knowledge(self, mock_browser, mock_popen):
        # 1. Meaning query -> should NOT launch browser
        _open_search_in_browser("what is the meaning of ephemeral")
        mock_popen.assert_not_called()
        mock_browser.assert_not_called()

        # 2. Definition query -> should NOT launch browser
        _open_search_in_browser("define altruism")
        mock_popen.assert_not_called()
        mock_browser.assert_not_called()

        # 3. Translation query -> should NOT launch browser
        _open_search_in_browser("translate hello to French")
        mock_popen.assert_not_called()
        mock_browser.assert_not_called()

        # 4. Explanation query -> should NOT launch browser
        _open_search_in_browser("explain photosynthesis")
        mock_popen.assert_not_called()
        mock_browser.assert_not_called()

        # 5. Explicit Google/Web search -> SHOULD launch browser
        _open_search_in_browser("search google for latest nvidia stock price")
        mock_popen.assert_called_once()

    def test_web_search_tool_description(self):
        desc = WEB_SEARCH_TOOL["description"]
        self.assertIn("DO NOT call for general explanations", desc)
        self.assertIn("word meanings", desc)
        self.assertIn("language translations", desc)


if __name__ == "__main__":
    unittest.main()
