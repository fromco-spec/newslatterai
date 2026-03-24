import os
import csv
import io
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
                section_content += f"\n### {filename}\n{content}\n"

        sections.append(section_content)

    return "\n".join(sections) if sections else ""


async def generate_newsletter(
    prompt: str,
    tone: str = "professional",
    length: str = "medium",
    selected_files: list[str] | None = None,
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or _API_KEY
    model = os.environ.get("CLAUDE_MODEL") or _MODEL
    if not (api_key or "").strip():
        raise ValueError(
            "ANTHROPIC_API_KEY が未設定です。.env にAPIキーを設定してから再起動してください。"
        )

    reference_data = ""
    if selected_files:
        for filepath in selected_files:
            full_path = os.path.join(UPLOAD_DIR, filepath)
            if os.path.exists(full_path):
                content = read_file_content(full_path)
                reference_data += f"\n### {os.path.basename(filepath)}\n{content}\n"
    else:
        reference_data = gather_reference_data()

    length_guide = {
        "short": "300〜500文字程度の簡潔なメルマガ",
        "medium": "500〜1000文字程度の標準的なメルマガ",
        "long": "1000〜2000文字程度の詳細なメルマガ",
    }

    system_prompt = f"""あなたはプロのメルマガライターです。
以下の条件に従って、HTML形式のメルマガを作成してください。

【条件】
- トーン: {tone}
- 長さ: {length_guide.get(length, length_guide["medium"])}
- 出力はHTML形式のみ（完全なHTML。DOCTYPE宣言から</html>まで）
- レスポンシブデザイン対応
- インラインCSSを使用（メールクライアント互換性のため）
- テーブルレイアウトを推奨（メールクライアント互換性のため）
- 日本語で作成
- 見やすく美しいデザイン
- CTAボタンがある場合はリンク先を「#」にしてください

【重要】
- HTMLコードのみを出力してください
- 説明文やマークダウンは不要です
- ```html などのコードブロック記法は使わないでください"""

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
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    html_content = response.content[0].text

    # Clean up if wrapped in code blocks
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
