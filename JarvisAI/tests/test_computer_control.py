import json
import unittest
from unittest.mock import patch, MagicMock
from actions.computer_control import (
    computer_control,
    _generate_shape_paths,
    _safe_cursor_pos,
    TOOL,
)
from core import security


class TestComputerControl(unittest.TestCase):
    def test_tool_declaration(self):
        self.assertEqual(TOOL["name"], "computer_control")
        self.assertTrue(callable(TOOL["handler"]))
        props = TOOL["parameters"]["properties"]
        self.assertIn("action", props)
        self.assertIn("shape", props)
        self.assertIn("direction", props)
        self.assertIn("amount", props)
        self.assertIn("points", props)
        self.assertIn("size", props)

    def test_security_tiers(self):
        for act in ("scroll", "draw", "draw_shape", "draw_path", "mouse_down", "mouse_up", "click", "move"):
            self.assertEqual(
                security.tier_for("computer_control", {"action": act}),
                security.TIER_SENSITIVE,
                f"Action {act} should be TIER_SENSITIVE"
            )

    def test_shape_generators(self):
        shapes = [
            "heart", "smiley", "face", "star", "flower", "house",
            "sun", "circle", "rectangle", "triangle", "tree", "spiral", "line"
        ]
        for shape in shapes:
            paths = _generate_shape_paths(shape, 500, 500, size=150)
            self.assertGreater(len(paths), 0, f"Shape {shape} generated no paths")
            for path in paths:
                self.assertGreaterEqual(len(path), 2, f"Path in {shape} has fewer than 2 points")
                for pt in path:
                    self.assertEqual(len(pt), 2, f"Point in {shape} is not (x, y)")
                    self.assertIsInstance(pt[0], int)
                    self.assertIsInstance(pt[1], int)

    @patch("actions.computer_control._click")
    def test_click_fast_path_pronouns(self, mock_click):
        mock_click.return_value = "Clicked at current position"
        # "click this", "click that", "click here" should not trigger screen vision search
        for desc in ("this", "that", "here", "it", "current", "cursor", "this button"):
            res = computer_control({"action": "click", "description": desc})
            self.assertEqual(res, "Clicked at current position")
            mock_click.assert_called_with(None, None, "left", 1)

    @patch("actions.computer_control._click")
    def test_screen_click_fast_path_pronouns(self, mock_click):
        mock_click.return_value = "Clicked at current position"
        for desc in ("this", "that", "here", "it", "current", "cursor", ""):
            res = computer_control({"action": "screen_click", "description": desc})
            self.assertEqual(res, "Clicked at current position")

    @patch("actions.computer_control.pyautogui.scroll")
    def test_scroll_down_and_up(self, mock_scroll):
        with patch("actions.computer_control._move"):
            res_down = computer_control({"action": "scroll", "direction": "down", "amount": 3})
            self.assertIn("Scrolled down", res_down)
            mock_scroll.assert_called_with(-360)

            res_up = computer_control({"action": "scroll", "direction": "up", "amount": 2})
            self.assertIn("Scrolled up", res_up)
            mock_scroll.assert_called_with(240)

    @patch("actions.computer_control.pyautogui.press")
    def test_scroll_page_navigation(self, mock_press):
        res_pagedown = computer_control({"action": "scroll", "direction": "page_down"})
        self.assertEqual(res_pagedown, "Scrolled page down")
        mock_press.assert_called_with("pagedown")

        res_pageup = computer_control({"action": "scroll", "direction": "page_up"})
        self.assertEqual(res_pageup, "Scrolled page up")
        mock_press.assert_called_with("pageup")

    @patch("actions.computer_control._draw_shape")
    def test_draw_action_dispatch(self, mock_draw_shape):
        mock_draw_shape.return_value = "Successfully drew heart"
        res = computer_control({"action": "draw", "shape": "heart", "size": 180, "window": "Paint"})
        self.assertEqual(res, "Successfully drew heart")
        mock_draw_shape.assert_called_once()
        args = mock_draw_shape.call_args[1]
        self.assertEqual(args["shape"], "heart")
        self.assertEqual(args["size"], 180)
        self.assertEqual(args["window"], "Paint")

    @patch("actions.computer_control._draw_path")
    def test_draw_path_dispatch(self, mock_draw_path):
        mock_draw_path.return_value = "Drawn path with 3 points"
        pts = [[100, 100], [200, 200], [300, 150]]
        res = computer_control({"action": "draw_path", "points": pts})
        self.assertEqual(res, "Drawn path with 3 points")
        mock_draw_path.assert_called_once_with(points=pts, button="left")

    @patch("actions.computer_control._native_mouse_down")
    def test_mouse_down_dispatch(self, mock_mouse_down):
        res = computer_control({"action": "mouse_down", "button": "left"})
        self.assertIn("Mouse down [left]", res)
        mock_mouse_down.assert_called_once_with(button="left")

    @patch("actions.computer_control._native_mouse_up")
    def test_mouse_up_dispatch(self, mock_mouse_up):
        res = computer_control({"action": "mouse_up", "button": "left"})
        self.assertIn("Mouse up [left]", res)
        mock_mouse_up.assert_called_once_with(button="left")

    def test_safe_cursor_pos(self):
        pos = _safe_cursor_pos()
        self.assertIsInstance(pos, tuple)
        self.assertEqual(len(pos), 2)
        self.assertIsInstance(pos[0], int)
        self.assertIsInstance(pos[1], int)

    def test_generate_multi_stroke_objects(self):
        from actions.computer_control import _generate_multi_stroke_object
        test_objects = [
            ("house", {"green", "brown", "red", "orange", "blue", "yellow"}),
            ("tree", {"green", "brown", "red"}),
            ("cat", {"black", "pink", "green"}),
            ("dog", {"brown", "black", "blue", "red", "yellow"}),
            ("car", {"red", "black", "gray", "blue", "yellow"}),
            ("boat", {"brown", "black", "red", "yellow", "blue"}),
            ("flower", {"green", "yellow", "pink"}),
            ("sun", {"yellow", "orange"}),
            ("fish", {"orange", "red", "black", "blue"}),
            ("bird", {"blue", "yellow", "black"}),
            ("landscape", {"purple", "blue", "green", "brown", "yellow"}),
        ]
        for name, expected_colors in test_objects:
            strokes = _generate_multi_stroke_object(name, 500, 500, size=200)
            self.assertGreater(len(strokes), 0, f"Object {name} produced no strokes")
            found_colors = set(s["color"] for s in strokes)
            for exp in expected_colors:
                self.assertIn(exp, found_colors, f"Object {name} missing expected color {exp}")
            for s in strokes:
                self.assertIn("color", s)
                self.assertIn("points", s)
                self.assertGreaterEqual(len(s["points"]), 2)

    @patch("actions.computer_control._select_paint_color")
    def test_select_color_dispatch(self, mock_select_color):
        mock_select_color.return_value = True
        res = computer_control({"action": "select_color", "color": "red"})
        self.assertIn("Selected red color in Paint", res)
        mock_select_color.assert_called_with("red", window="Paint")

        res_set = computer_control({"action": "set_color", "color": "blue"})
        self.assertIn("Selected blue color in Paint", res_set)

    @patch("actions.computer_control._select_paint_color")
    @patch("actions.computer_control._draw_path")
    @patch("actions.computer_control._focus_window")
    def test_draw_object_multi_color_execution(self, mock_focus, mock_draw_path, mock_select_color):
        from actions.computer_control import _draw_object
        mock_select_color.return_value = True
        mock_draw_path.return_value = "Drawn"

        res = _draw_object(target="house", x=500, y=500, size=200, window="Paint")
        self.assertIn("Successfully painted house", res)
        # Should have called select_paint_color for different colors
        self.assertGreater(mock_select_color.call_count, 1)
        self.assertGreater(mock_draw_path.call_count, 1)

    @patch("actions.computer_control._get_api_key")
    @patch("core.gemini.call")
    def test_ai_generate_object_strokes(self, mock_gemini_call, mock_get_key):
        from actions.computer_control import _ai_generate_object_strokes
        mock_get_key.return_value = "fake_key"
        mock_resp = MagicMock()
        mock_resp.text = json.dumps([
            {"color": "green", "points": [[500, 480], [520, 460], [540, 490]]},
            {"color": "black", "points": [[530, 470], [535, 470]]}
        ])
        mock_gemini_call.return_value = mock_resp

        strokes = _ai_generate_object_strokes("a green dinosaur", 500, 500, 200)
        self.assertIsNotNone(strokes)
        self.assertEqual(len(strokes), 2)
        self.assertEqual(strokes[0]["color"], "green")
        self.assertEqual(len(strokes[0]["points"]), 3)


if __name__ == "__main__":
    unittest.main()

