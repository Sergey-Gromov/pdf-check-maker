"""Interactive CSV/JSON to PDF invoice generator (Python 3.10+)."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent


def load_data(path: Path) -> dict[str, list[dict]]:
    """Load flat records and group multiple product rows by invoice_id."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        if path.suffix.lower() == ".csv":
            sample = stream.read(8192)
            stream.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(stream, dialect=dialect)
            headers = reader.fieldnames or []
            if not headers or len(headers) != len(set(headers)):
                raise ValueError("Отсутствуют заголовки CSV или есть дубликаты.")
            records = list(reader)
        else:
            records = json.load(stream)
            if isinstance(records, dict):
                records = records.get("invoices", [records])
    if not isinstance(records, list) or not records:
        raise ValueError("Нужен непустой список записей.")
    grouped: dict[str, list[dict]] = {}
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict) or None in record or any(v is None for v in record.values()):
            raise ValueError(f"Запись {index}: неверная структура или пустое значение null.")
        invoice_id = record.get("invoice_id")
        if isinstance(invoice_id, bool) or not isinstance(invoice_id, (str, int)) or not str(invoice_id).strip():
            raise ValueError(f"Запись {index}: требуется непустой invoice_id (строка или целое число).")
        record = dict(record, invoice_id=str(invoice_id).strip())
        grouped.setdefault(record["invoice_id"], []).append(record)
    return grouped


def show_menu(title: str, labels: list[str]) -> None:
    print(f"\n{title}\n" + "─" * 48)
    for number, label in enumerate(labels, 1):
        print(f"  {number}. {label}")
    if not labels:
        print("  Нет доступных вариантов.")


def choose(label: str, options: list):
    while True:
        value = input(f"{label} (1–{len(options)}, 0 — выход): ").strip()
        if value == "0":
            raise KeyboardInterrupt
        if value.isascii() and value.isdecimal() and 1 <= int(value) <= len(options):
            return options[int(value) - 1]
        print("Введите номер из списка.")


def generate_pdf(template: Path, rows: list[dict], output: Path) -> Path:
    from jinja2 import FileSystemLoader, StrictUndefined, meta
    from jinja2.sandbox import SandboxedEnvironment
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration

    environment = SandboxedEnvironment(
        loader=FileSystemLoader(str(template.parent), encoding="utf-8-sig"),
        autoescape=True, undefined=StrictUndefined,
    )
    source = template.read_text(encoding="utf-8-sig")
    variables = meta.find_undeclared_variables(environment.parse(source))
    if len(rows) > 1 and "items" not in variables:
        raise ValueError("У чека несколько товаров: используйте шаблон с циклом по items (invoice.html).")
    context = dict(rows[0])
    context["items"] = rows
    rendered = environment.get_template(template.name).render(context)
    font_config = FontConfiguration()
    font_dir = BASE_DIR / "fonts"
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        if not (font_dir / name).is_file():
            raise ValueError(f"Не найден шрифт: {font_dir / name}")
    css = CSS(string=f"""
        @font-face {{ font-family: InvoiceSans; src: url('{(font_dir / 'DejaVuSans.ttf').as_uri()}'); }}
        @font-face {{ font-family: InvoiceSans; font-weight: bold; src: url('{(font_dir / 'DejaVuSans-Bold.ttf').as_uri()}'); }}
        body, body * {{ font-family: InvoiceSans, sans-serif !important; }}
        @page {{ size: A4; margin: 20mm; }}
    """, font_config=font_config)
    output.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^\w-]", "_", rows[0]["invoice_id"])[:60]
    destination = output / f"invoice_{safe_id}_{uuid4().hex}.pdf"
    # Render before creating the file so a rendering failure leaves no partial PDF.
    pdf = HTML(string=rendered, base_url=str(template.parent)).write_pdf(
        stylesheets=[css], font_config=font_config,
    )
    with destination.open("xb") as stream:
        stream.write(pdf)
    return destination.resolve()


def open_pdf(path: Path) -> None:
    path = path.resolve()
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    elif sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise OSError("Нет графической сессии Linux. Для сервера используйте --no-open")
        opener = shutil.which("xdg-open")
        if opener is None:
            raise OSError("Не найден xdg-open. Установите пакет xdg-utils или используйте --no-open")
        subprocess.run([opener, str(path)], check=True)
    else:
        raise OSError(f"Автоматическое открытие не поддерживается на {sys.platform}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Генератор PDF-чеков из CSV и JSON")
    parser.add_argument("--data-dir", type=Path, default=BASE_DIR / "data")
    parser.add_argument("--templates-dir", type=Path, default=BASE_DIR / "templates")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "output")
    parser.add_argument("--no-open", action="store_true", help="Не открывать PDF автоматически")
    args = parser.parse_args()
    print("\nГЕНЕРАТОР PDF-ЧЕКОВ")
    try:
        loaded = {}
        if not args.data_dir.is_dir() or not args.templates_dir.is_dir():
            raise ValueError("Проверьте наличие папок data и templates.")
        for path in sorted(args.data_dir.iterdir(), key=lambda p: p.name.casefold()):
            if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
                try:
                    loaded[path] = load_data(path)
                except (OSError, ValueError, csv.Error) as error:
                    print(f"Пропущен {path.name}: {error}")
        templates = sorted(
            (p for p in args.templates_dir.iterdir() if p.is_file() and p.suffix.lower() in {".html", ".htm"}),
            key=lambda p: p.name.casefold(),
        )
        show_menu("Файлы данных", [p.name for p in loaded])
        show_menu("HTML-шаблоны", [p.name for p in templates])
        if not loaded or not templates:
            raise ValueError("Добавьте корректный файл данных и HTML-шаблон.")
        data_path = choose("Номер файла данных", list(loaded))
        template = choose("Номер шаблона", templates)
        invoices = loaded[data_path]
        show_menu("Доступные чеки (invoice_id)", [f"{key} — позиций: {len(rows)}" for key, rows in invoices.items()])
        invoice_id = choose("Номер чека", list(invoices))
        destination = generate_pdf(template.resolve(), invoices[invoice_id], args.output_dir)
        print(f"\nPDF сохранён: {destination}")
        if not args.no_open:
            try:
                open_pdf(destination)
            except (OSError, subprocess.SubprocessError) as error:
                print(f"Не удалось открыть PDF автоматически: {error}. Откройте файл по указанному пути.")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nВыход.")
        return 0
    except Exception as error:
        print(f"\nОшибка: {error}", file=sys.stderr)
        print("Проверьте данные и зависимости; инструкция находится в README.md.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
