# research-rag

## プロジェクト概要

`research-rag` は、研究資料として使用するPDFをローカル環境で検索し、その内容に基づく回答と根拠を提示するRAGアプリケーションです。

## 現在の開発段階

テキストを含む1つ以上のPDFへ質問できるCLI版MVPを実装済みです。選択したPDFを1つの共有検索空間として扱い、ページ境界を保って全文書を横断検索します。Ollamaが生成した回答と、根拠となるPDF名・ページ番号・類似度・文章を表示します。SQLiteへ保存したcorpusでは、文書の変更検出と文書単位の追加・削除・再indexも利用できます。

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

## 再利用可能なインメモリindex

同じPDF集合へ複数回質問する場合は、文書側の処理を`build_rag_index()`で1回だけ実行し、返されたimmutableな`RagIndex`を再利用できます。質問embeddingには、index作成時に記録された埋め込みモデルが自動的に使われます。

```python
from pathlib import Path

from research_rag.ollama_client import OllamaClient
from research_rag.rag_service import (
    answer_question_from_index,
    build_rag_index,
)

client = OllamaClient()
index = build_rag_index(
    [Path("main-paper.pdf"), Path("supplement.pdf")],
    embedding_model="qwen3-embedding:0.6b",
    client=client,
)

first_answer = answer_question_from_index(
    index,
    "主な提案手法は何ですか？",
    generation_model="qwen3:4b-instruct",
    client=client,
)
second_answer = answer_question_from_index(
    index,
    "実験ではどのデータセットを使っていますか？",
    generation_model="qwen3:4b-instruct",
    client=client,
)
```

`RagIndex`自身による再利用は同じPythonプロセスのメモリ内に限られます。永続化には次節の専用storeを使います。既存のCLIと`answer_question_from_pdf()`／`answer_question_from_pdfs()`は従来どおり利用でき、内部で同じbuild＋answerライフサイクルを1回ずつ実行します。

## SQLiteへのindex保存

`SQLiteRagIndexStore`を使うと、準備済みindexをPython標準ライブラリのSQLiteへ保存し、別プロセスで読み直せます。データベースはリポジトリ外のユーザーデータ領域へ置いてください。

```python
from pathlib import Path

from research_rag.index_store import SQLiteRagIndexStore

pdf_paths = [Path("main-paper.pdf"), Path("supplement.pdf")]
db_path = Path.home() / ".research-rag" / "indexes.sqlite3"

store = SQLiteRagIndexStore(db_path)
store.initialize()
metadata = store.save_index(index, pdf_paths)

# 別プロセス相当の新しいstore instanceから読み込む
reopened_store = SQLiteRagIndexStore(db_path)
reopened_store.initialize()
loaded_index = reopened_store.load_index(metadata.index_id)

saved_indexes = reopened_store.list_indexes()
deleted = reopened_store.delete_index(metadata.index_id)
```

保存形式はschema version 2です。schema version 1のDBは`initialize()`時にtransaction内でv2へ移行し、既存のindex・文書・Chunk・embeddingを維持します。文書・indexには永続UUIDを付け、embeddingはpickleを使わずlittle-endian IEEE-754 float64 BLOBとして保存します。元PDFの絶対source pathも管理情報として保持しますが、loadや質問時にPDFが存在する必要はありません。現在のCLIは永続化を自動的に使用せず、構文も従来どおりです。

## 永続corpusの文書管理

新しく永続corpusを作る場合は`PersistentRagDocumentManager`を使用します。作成時に各PDFのSHA-256をindex処理の前後で確認し、保存済み内容とsource fileの関係を信頼できる形で記録します。

```python
from pathlib import Path

from research_rag.document_manager import PersistentRagDocumentManager
from research_rag.index_store import SQLiteRagIndexStore
from research_rag.ollama_client import OllamaClient

store = SQLiteRagIndexStore(Path.home() / ".research-rag" / "indexes.sqlite3")
store.initialize()
manager = PersistentRagDocumentManager(store, client=OllamaClient())

metadata = manager.create_index(
    [Path("main-paper.pdf"), Path("supplement.pdf")],
    embedding_model="qwen3-embedding:0.6b",
)

statuses = manager.inspect_documents(metadata.index_id)
added = manager.add_document(metadata.index_id, Path("related-paper.pdf"))
reindexed = manager.reindex_document(
    metadata.index_id,
    metadata.documents[0].document_id,
)
removed = manager.remove_document(metadata.index_id, added.document_id)
```

`inspect_documents()`は、保存時と現在のSHA-256を比較して`CURRENT`、`MODIFIED`、`MISSING`、`UNKNOWN`を返します。SHA-256を変更判定の正とし、sizeとmtimeは表示・診断用です。schema v1から移行した文書と、低水準の`save_index()`で保存した文書には信頼できるfingerprintがないため`UNKNOWN`になります。inspectionはPDF抽出やOllamaを実行しません。

追加と再indexでは、対象PDFだけをproduction pipelineで処理し、保存済みembedding modelを使用します。削除では対象文書だけを削除します。いずれも既存の`index_id`と変更しない文書の`document_id`を維持し、既存文書を再embeddingしません。source fileが処理中に変わった場合や外部処理・DB処理が失敗した場合は、保存済みcorpusを変更しません。最後の検索可能文書の削除は拒否されるため、corpus全体を消す場合は`delete_index()`を使用します。

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

従来どおり、1つのPDFへ質問できます。

```bash
python -m research_rag.cli \
    sample.pdf \
    "この論文の主な提案手法は何ですか？" \
    --embedding-model qwen3-embedding:0.6b \
    --generation-model qwen3:4b-instruct \
    --top-k 3
```

追加のPDFは`--pdf`を繰り返して指定します。最初の位置引数のPDF、各`--pdf`の順に読み込みますが、検索順位はPDFごとに分けず、すべてのチャンクを対象に一度だけ計算します。

```bash
python -m research_rag.cli \
    main-paper.pdf \
    "これらの資料に共通する結論は何ですか？" \
    --pdf supplementary-material.pdf \
    --pdf related-paper.pdf
```

出典の識別にファイル名を使うため、異なるディレクトリにあっても同じbasename（例: `paper.pdf`）を持つPDFは同時に指定できません。テキストを抽出できないPDFが含まれていても、ほかに検索可能なPDFがあれば処理を続行します。すべてのPDFから検索可能なチャンクを作れない場合はエラーになります。

モデル指定を省略した場合は、上記の2モデルを使用します。Ollamaの接続先はデフォルトで `http://localhost:11434` です。別のモデルや接続先を使用する場合は、次のオプションで変更できます。

```text
--embedding-model MODEL
--generation-model MODEL
--top-k NUMBER
--ollama-base-url URL
--pdf PDF
```

CLIは回答本文に続けて、検索順位、PDF名、PDF内で1始まりのページ番号、コサイン類似度、根拠文章を表示します。PDFの抽出・チャンク・埋め込みは実行ごとのメモリ内だけに保持され、永続化されません。

## MVPの対象外

OCR、GUI、会話履歴、FAISS／ChromaなどのベクトルDB、クラウドLLMには対応していません。フォルダやglobによるPDFの自動収集、ファイル監視、自動再indexも行いません。
