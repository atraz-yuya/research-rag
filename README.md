# research-rag

## プロジェクト概要

`research-rag` は、研究資料として使用するPDFをローカル環境で検索し、その内容に基づく回答と根拠を提示するRAGアプリケーションです。

## 現在の開発段階

テキストを含む1つ以上のPDFへ質問できるCLI版MVPと、保存済み資料セットを管理して質問できるPySide6デスクトップGUIを実装済みです。選択したPDFを1つの共有検索空間として扱い、ページ境界を保って全文書を横断検索します。Ollamaが生成した回答と、根拠となるPDF名・ページ番号・類似度・文章を表示します。SQLiteへ保存した資料セットでは、表示名の作成・変更・資料セット全体の削除、文書の変更検出と文書単位の追加・削除・再インデックスも利用できます。

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

GUIテストだけをheadless環境で実行する場合は、Qtのoffscreen platformを指定します。`pytest-qt`は使用していません。

```bash
QT_QPA_PLATFORM=offscreen python -m pytest \
    tests/test_gui_service.py \
    tests/test_gui_worker.py \
    tests/test_gui_app.py \
    tests/test_main_window.py -v
```

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
metadata = store.save_index(index, pdf_paths, display_name="卒業研究 関連論文")

# 別プロセス相当の新しいstore instanceから読み込む
reopened_store = SQLiteRagIndexStore(db_path)
reopened_store.initialize()
loaded_index = reopened_store.load_index(metadata.index_id)

saved_indexes = reopened_store.list_indexes()
renamed = reopened_store.rename_index(metadata.index_id, "研究資料 2026")
deleted = reopened_store.delete_index(metadata.index_id)
```

保存形式はschema version 3です。schema version 1／2のDBは`initialize()`時に1つのtransaction内でv1→v2→v3の順に移行し、既存のindex・文書・Chunk・embedding・UUIDを維持します。資料セットの`display_name`は表示専用metadataで、機械的な永続identityは引き続き`index_id`です。移行した既存資料セットの名前はNULLのままとし、GUIでは名前を設定するまで従来のPDF名ベース表示へfallbackします。文書・indexには永続UUIDを付け、embeddingはpickleを使わずlittle-endian IEEE-754 float64 BLOBとして保存します。元PDFの絶対source pathも管理情報として保持しますが、loadや質問時にPDFが存在する必要はありません。現在のCLIは永続化を自動的に使用せず、構文も従来どおりです。

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
    display_name="卒業研究 関連論文",
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

## デスクトップGUIの実行

GUIはPySide6を使用し、CLIとは別のエントリーポイントで起動します。先にOllamaを起動し、CLIと同じ埋め込みモデルと生成モデルを準備してください。

```bash
ollama pull qwen3-embedding:0.6b
ollama pull qwen3:4b-instruct
python -m research_rag.gui_app
```

GUIでは、保存済み資料セットの一覧、文書の`CURRENT`／`MODIFIED`／`MISSING`／`UNKNOWN`状態、source pathを確認できます。複数PDFから名前付き資料セットを作成し、後から名前を変更できます。PDFの追加、選択文書の再インデックスと削除、状態更新、資料セットへの質問にも対応します。`資料セットを削除`は、その資料セットに属するSQLite内のindex・文書・Chunk・embeddingをまとめて削除しますが、元PDFファイルそのものは削除しません。表示名の重複は許可され、内部のUUIDで資料セットを区別します。

PDF抽出やOllama処理などの実行中は、正確な進捗率を取得できないため、割合を表示しないindeterminate progress indicatorと操作内容を表示します。処理中は競合する操作と設定変更を無効化し、完了後は操作ごとの成功メッセージを表示します。失敗時もindicatorを解除して操作可能な状態へ戻り、質問文、既存の回答・参照、資料セット、正常に表示済みの文書状態を不要に消去しません。

資料セットがない場合と未選択の場合は、次に行う操作をempty-state labelで案内します。回答・参照欄の説明はplaceholderであり、実データとしてコピーされません。文書状態はGUI上で`最新`（保存時と一致）、`変更あり`（元PDFが変更済み）、`ファイルなし`（保存元に存在しない）、`未確認`（比較用fingerprintなし）と表示し、詳細はtooltipで確認できます。内部のstatus値と変更検出ロジックは従来どおりです。

`設定`画面では、Embedding model、Generation model、Top-K（1〜100）、Ollama URLを変更できます。設定は検証後に`settings.ini`へ保存され、GUI再起動後も引き継がれます。Embedding modelの変更は、新しく作成する資料セットだけに適用されます。既存資料セットへの質問、PDF追加、再インデックスは、その資料セットに保存済みのembedding modelを引き続き使用し、選択中の実際のモデル名は資料セット一覧の下に表示されます。Generation modelとTop-Kは次の質問から反映され、Ollama URLを変更すると以後の文書処理と質問が同じ新しい接続先を使います。設定の適用だけではOllamaへ接続しません。

既定のSQLite DBはQtの`QStandardPaths.AppDataLocation`配下に作成されます。macOSでは通常、`~/Library/Application Support/ResearchRAG/indexes.sqlite3`です。GUI設定は同じディレクトリの`settings.ini`へ、corpus SQLiteとは分離して保存します。元PDFの本文はSQLiteへChunkとembeddingとして保存されますが、元PDFファイルをアプリケーションデータ領域へコピーしません。そのため、追加後に元PDFを移動・変更・削除すると、状態はそれぞれ`MISSING`または`MODIFIED`になります。保存済みChunkは引き続き質問に利用でき、再インデックスには元のsource pathにPDFが必要です。

資料セット作成、追加、再インデックス、状態確認、質問はQtのworker threadで実行されます。処理中にwindowを閉じた場合は、実行中の有限処理が安全に終了してからwindowを閉じます。Ollamaへ接続できない場合や処理に失敗した場合はエラーダイアログを表示し、質問入力を保持したまま操作可能な状態へ戻ります。会話履歴は保持せず、質問ごとに独立して回答します。

## macOSアプリケーションのビルド

macOSでは、PySide6公式の`pyside6-deploy`を使ってstandaloneな`Research RAG.app`を再現できます。PyInstallerは使用しません。仮想環境を有効化して開発用installを済ませたリポジトリルートで、最初にdry-runを確認し、その後build helperを実行します。

```bash
./scripts/build_macos_app.sh --dry-run
./scripts/build_macos_app.sh
```

成果物は`build/deploy/Research RAG.app`です。build helperはdry-runを含めて内部で`pyside6-deploy`を呼び、specに記録したNuitka versionも明示的に適用します。macOS以外、または有効な環境に`pyside6-deploy`がない場合は理由を表示して失敗します。実ビルドでは環境固有の値が追跡中の設定へ書き戻されないよう、repositoryの`pysidedeploy.spec`を一時コピーして使用します。生成後はFinder/resource-fork属性を除去してローカル用のad-hoc署名を付け、strict検証まで成功した場合だけbuild完了とします。これはDeveloper ID署名ではありません。開発時の`python -m research_rag.gui_app`とCLIは従来どおり利用できます。

ローカルでbuildしたDeveloper ID未署名（ad-hoc署名）のアプリは、次のように起動できます。

```bash
open "build/deploy/Research RAG.app"
```

`.app`には`indexes.sqlite3`、`settings.ini`、PDF、Ollama本体、Ollama modelを含めません。DBと設定は起動後も`QStandardPaths.AppDataLocation`（macOSでは通常`~/Library/Application Support/ResearchRAG`）へ保存され、app bundle内部には書き込みません。Ollamaは別途起動・model準備が必要で、接続先にはGUIで保存したOllama URLを使います。

このbuildはローカル動作確認用です。Developer ID署名、hardened runtime、notarization、DMG、Mac App Store配布、custom icon、auto update、cross-platform installerはまだ対象外です。

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

OCR、会話履歴、FAISS／ChromaなどのベクトルDB、クラウドLLMには対応していません。フォルダやglobによるPDFの自動収集、ファイル監視、自動再インデックスも行いません。
