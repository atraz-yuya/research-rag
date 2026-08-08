# research-rag

## プロジェクト概要

`research-rag` は、研究資料として使用するPDFをローカル環境で検索し、その内容に基づく回答と根拠を提示するRAGアプリケーションです。

## 現在の開発段階

テキストを含む単一PDFへ質問できるCLI版MVPを実装済みです。PDFから抽出した文章をページ境界を保って検索し、Ollamaが生成した回答と、根拠となるPDF名・ページ番号・類似度・文章を表示します。

MVPの範囲と完了条件は [`docs/mvp_spec.md`](docs/mvp_spec.md) を参照してください。

## 必要な環境

- Python 3.11以上

## 開発環境のセットアップ

macOSでは、リポジトリのルートで次のコマンドを実行して仮想環境を作成し、有効化します。

```bash
python3.11 -m venv venv
source venv/bin/activate
```

このプロジェクトでは、macOSで `.venv` 内のeditable install用 `.pth` にhiddenフラグが付き、パッケージをimportできなくなった事例を避けるため、仮想環境ディレクトリとして `venv` を使用しています。

続いて、プロジェクト本体と開発用依存ライブラリを編集可能モードでインストールします。

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## テスト

仮想環境を有効化し、開発用依存ライブラリをインストールした状態で実行します。

```bash
python -m pytest
```

通常の単体テストはOllamaへ接続しません。

## CLIの実行

### 1. 仮想環境を有効化する

```bash
source venv/bin/activate
```

### 2. Ollamaを起動する

別のターミナルでOllamaを起動します。すでにサービスとして起動している場合、この操作は不要です。

```bash
ollama serve
```

### 3. モデルを準備する

埋め込みモデルと生成モデルをそれぞれ取得します。

```bash
ollama pull qwen3-embedding:0.6b
ollama pull qwen3:4b-instruct
```

### 4. PDFへ質問する

```bash
python -m research_rag.cli \
    sample.pdf \
    "この論文の主な提案手法は何ですか？" \
    --embedding-model qwen3-embedding:0.6b \
    --generation-model qwen3:4b-instruct \
    --top-k 3
```

モデル指定を省略した場合は、上記の2モデルを使用します。Ollamaの接続先はデフォルトで `http://localhost:11434` です。別のモデルや接続先を使用する場合は、次のオプションで変更できます。

```text
--embedding-model MODEL
--generation-model MODEL
--top-k NUMBER
--ollama-base-url URL
```

CLIは回答本文に続けて、検索順位、PDF名、1始まりのページ番号、コサイン類似度、根拠文章を表示します。

## MVPの対象外

OCR、複数PDF、GUI、SQLite、会話履歴、FAISS／Chromaによる永続化、クラウドLLMには対応していません。
