#!/bin/bash
echo "===================================="
echo " メルマガ自動作成AI - 起動中..."
echo "===================================="

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Python仮想環境を作成中..."
    python3 -m venv venv
    source venv/bin/activate
    echo "依存パッケージをインストール中..."
    pip install -r backend/requirements.txt
else
    source venv/bin/activate
fi

echo ""
echo "ブラウザで http://localhost:8000 を開いてください"
echo "初期ログイン: admin / .env の ADMIN_DEFAULT_PASSWORD で設定したパスワード"
echo "終了するには Ctrl+C を押してください"
echo "===================================="
echo ""

cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
