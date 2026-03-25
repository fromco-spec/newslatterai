import os
import csv
import io
import re
from html.parser import HTMLParser
from anthropic import Anthropic
from PyPDF2 import PdfReader

try:
    from config import settings
    _UPLOAD_DIR = settings.UPLOAD_DIR
    _API_KEY = settings.ANTHROPIC_API_KEY
    _MODEL = settings.CLAUDE_MODEL
except Exception:
    _UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
    _API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    _MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

UPLOAD_DIR = _UPLOAD_DIR

MAX_CHARS_PER_FILE = 3000
MAX_TOTAL_REFERENCE_CHARS = 10000
MAX_SKELETON_CHARS = 2500


def _truncate(content: str, max_chars: int = MAX_CHARS_PER_FILE) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n\n...（以下省略）"


# ---------------------------------------------------------------------------
# HTML skeleton extractor
# ---------------------------------------------------------------------------
class _SkeletonBuilder(HTMLParser):
    """HTMLからテキスト内容を除去し、構造+スタイルの骨格を抽出"""

    SKIP_TAGS = {"script", "noscript"}
    PLACEHOLDER_TAGS = {"h1", "h2", "h3", "h4", "p", "li", "span", "a", "td", "th", "title"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0
        self._current_tag = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        self._current_tag = tag
        attrs_str = ""
        for k, v in attrs:
            if k in ("style", "class", "width", "height", "align", "valign",
                      "bgcolor", "cellpadding", "cellspacing", "border"):
                if v:
                    attrs_str += f' {k}="{v}"'
        self.parts.append(f"<{tag}{attrs_str}>")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._current_tag in self.PLACEHOLDER_TAGS:
            self.parts.append("[...]")
        # Other text (inside style tags etc) is kept
        elif self._current_tag == "style":
            self.parts.append(text)

    def get_skeleton(self) -> str:
        raw = "".join(self.parts)
        # Collapse repeated [...] placeholders
        raw = re.sub(r'(\[\.\.\.]\s*){2,}', '[...]', raw)
        return raw


def extract_style_summary(html_content: str) -> str:
    """HTMLテンプレートから構造骨格を抽出（テキスト除去、スタイル保持）"""
    builder = _SkeletonBuilder()
    try:
        builder.feed(html_content)
    except Exception:
        pass

    skeleton = builder.get_skeleton()

    if len(skeleton) > MAX_SKELETON_CHARS:
        skeleton = skeleton[:MAX_SKELETON_CHARS] + "\n<!-- 以下省略 -->"

    return skeleton


def extract_multi_template_summary(templates: list[tuple[str, str]]) -> str:
    """複数テンプレートから統合スタイル概要を生成。
    templates: [(name, html_content), ...]
    """
    if not templates:
        return ""

    if len(templates) == 1:
        name, html = templates[0]
        skeleton = extract_style_summary(html)
        return f"【装飾テンプレート: {name}】\n以下のHTML構造・デザインを忠実に再現してください。テキスト内容は[...]で省略されています。\n\n{skeleton}"

    parts = []
    per_template_limit = max(800, MAX_SKELETON_CHARS // len(templates))

    parts.append(f"【装飾テンプレート（{len(templates)}件）】")
    parts.append("以下の複数テンプレートに共通するデザインパターン・構造・配色・レイアウトを分析し、")
    parts.append("それらのスタイルを忠実に再現してメルマガを作成してください。")
    parts.append("テキスト内容は[...]で省略されています。\n")

    for i, (name, html) in enumerate(templates, 1):
        builder = _SkeletonBuilder()
        try:
            builder.feed(html)
        except Exception:
            continue
        skeleton = builder.get_skeleton()
        if len(skeleton) > per_template_limit:
            skeleton = skeleton[:per_template_limit] + "\n<!-- 省略 -->"
        parts.append(f"--- テンプレート{i}: {name} ---")
        parts.append(skeleton)
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------
def read_file_content(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        try:
            reader = PdfReader(filepath)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except Exception as e:
            return f"[PDF読み取りエラー: {e}]"

    elif ext == ".csv":
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = list(reader)
            output = io.StringIO()
            for row in rows:
                output.write(" | ".join(row) + "\n")
            return output.getvalue()
        except Exception as e:
            return f"[CSV読み取りエラー: {e}]"

    else:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"[ファイル読み取りエラー: {e}]"


def gather_reference_data() -> str:
    sections = []
    categories = {
        "products": "商品情報",
        "instructions": "指示書",
        "templates": "テンプレート・参考資料",
    }
    total_chars = 0
    for folder, label in categories.items():
        folder_path = os.path.join(UPLOAD_DIR, folder)
        if not os.path.exists(folder_path):
            continue
        files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        if not files:
            continue
        section_content = f"\n## {label}\n"
        for filename in files:
            filepath = os.path.join(folder_path, filename)
            content = read_file_content(filepath)
            if content.strip():
                truncated = _truncate(content)
                if total_chars + len(truncated) > MAX_TOTAL_REFERENCE_CHARS:
                    section_content += f"\n### {filename}\n{_truncate(content, MAX_TOTAL_REFERENCE_CHARS - total_chars)}\n"
                    total_chars = MAX_TOTAL_REFERENCE_CHARS
                    break
                section_content += f"\n### {filename}\n{truncated}\n"
                total_chars += len(truncated)
        sections.append(section_content)
        if total_chars >= MAX_TOTAL_REFERENCE_CHARS:
            break
    return "\n".join(sections) if sections else ""


# ---------------------------------------------------------------------------
# Newsletter generation
# ---------------------------------------------------------------------------
async def generate_newsletter(
    prompt: str,
    length: str = "medium",
    template_style_summary: str | None = None,
    selected_files: list[str] | None = None,
    extra_context: str | None = None,
    footer_html: str | None = None,
    custom_instructions: str | None = None,
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or _API_KEY
    model = os.environ.get("CLAUDE_MODEL") or _MODEL
    if not (api_key or "").strip():
        raise ValueError("ANTHROPIC_API_KEY が未設定です。")

    # Build reference data (with truncation)
    reference_data = ""
    if extra_context:
        reference_data = _truncate(extra_context, MAX_TOTAL_REFERENCE_CHARS)
    elif selected_files:
        total = 0
        for filepath in selected_files:
            full_path = os.path.join(UPLOAD_DIR, filepath)
            if os.path.exists(full_path):
                content = read_file_content(full_path)
                truncated = _truncate(content)
                reference_data += f"\n### {os.path.basename(filepath)}\n{truncated}\n"
                total += len(truncated)
                if total >= MAX_TOTAL_REFERENCE_CHARS:
                    break
    else:
        reference_data = gather_reference_data()

    length_guide = {
        "short": "800〜1200文字程度のメルマガ",
        "medium": "1500〜2500文字程度のメルマガ",
        "long": "3000〜5000文字程度の詳細で充実したメルマガ",
    }

    system_prompt = f"""あなたはプロのメルマガライターです。
以下の条件に従って、HTML形式のメルマガを作成してください。

【条件】
- 長さ: {length_guide.get(length, length_guide["medium"])}
- 出力はHTML形式のみ（完全なHTML。DOCTYPE宣言から</html>まで）
- レスポンシブデザイン対応
- インラインCSSを使用（メールクライアント互換性のため）
- テーブルレイアウトを推奨（メールクライアント互換性のため）
- 日本語で作成
- 十分なボリュームのコンテンツを作成すること
- CTAボタンがある場合はリンク先を「#」にしてください

【重要】
- HTMLコードのみを出力してください
- 説明文やマークダウンは不要です
- ```html などのコードブロック記法は使わないでください"""

    if template_style_summary:
        system_prompt += f"\n\n【装飾スタイル指定】\n{template_style_summary}"

    if custom_instructions:
        system_prompt += f"\n\n【追加指示（必ず従ってください）】\n{custom_instructions}"

    if footer_html:
        system_prompt += f"\n\n【フッター】\n以下のHTMLを</body>タグの直前にそのまま挿入してください。内容を変更しないでください。\n{footer_html}"

    user_message = prompt
    if reference_data:
        user_message = f"""以下の参考データを活用してメルマガを作成してください。

【参考データ】
{reference_data}

【作成指示】
{prompt}"""

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    html_content = response.content[0].text

    if html_content.startswith("```"):
        lines = html_content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html_content = "\n".join(lines)

    return {
        "html": html_content,
        "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
    }
