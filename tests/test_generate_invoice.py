import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from generate_invoice import choose, load_data, open_pdf


class InvoiceTests(unittest.TestCase):
    def test_csv_bom_semicolon_and_grouping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("invoice_id;product;price;qty\n001;Ручка;45;1\n001;Папка;120;2\n", encoding="utf-8-sig")
            data = load_data(path)
            self.assertEqual(list(data), ["001"])
            self.assertEqual(len(data["001"]), 2)

    def test_json_shapes_and_invalid_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            row = {"invoice_id": "001", "product": "Ручка"}
            for payload in (row, [row], {"invoices": [row]}):
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual(load_data(path)["001"][0], row)
            for payload in ([], [{"product": "Ручка"}], [{"invoice_id": True}]):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_data(path)

    def test_menu_retries(self):
        with patch("builtins.input", side_effect=["abc", "-1", "3", "2"]):
            self.assertEqual(choose("Выбор", ["a", "b"]), "b")

    def test_platform_openers(self):
        path = Path("invoice.pdf").resolve()
        with patch("generate_invoice.sys.platform", "win32"), patch("generate_invoice.os.startfile", create=True) as start:
            open_pdf(path)
            start.assert_called_once_with(str(path))
        with patch("generate_invoice.sys.platform", "darwin"), patch("generate_invoice.subprocess.run") as run:
            open_pdf(path)
            run.assert_called_once_with(["open", str(path)], check=True)

    def test_linux_x11_and_wayland(self):
        path = Path("чек с пробелами.pdf").resolve()
        for session in ({"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-0"}):
            with self.subTest(session=session), patch("generate_invoice.sys.platform", "linux"), patch.dict("os.environ", session, clear=True), patch("generate_invoice.shutil.which", return_value="/usr/bin/xdg-open"), patch("generate_invoice.subprocess.run") as run:
                open_pdf(path)
                run.assert_called_once_with(["/usr/bin/xdg-open", str(path)], check=True)

    def test_linux_without_desktop_or_opener(self):
        with patch("generate_invoice.sys.platform", "linux"), patch.dict("os.environ", {}, clear=True), patch("generate_invoice.subprocess.run") as run:
            with self.assertRaisesRegex(OSError, "Нет графической сессии"):
                open_pdf(Path("invoice.pdf"))
            run.assert_not_called()
        with patch("generate_invoice.sys.platform", "linux"), patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True), patch("generate_invoice.shutil.which", return_value=None):
            with self.assertRaisesRegex(OSError, "xdg-utils"):
                open_pdf(Path("invoice.pdf"))


if __name__ == "__main__":
    unittest.main()
