# 開発ログ

## Issue 001: 開発基盤とMVP仕様の整備

実施日: 2026-08-06

### 実施内容

- プロジェクト概要、CLI版MVPの対象範囲、エラー条件、完了条件を文書化した
- READMEにmacOS向けの仮想環境構築、開発用インストール、テストの手順を追加した
- Pythonパッケージおよびpytestの設定を `pyproject.toml` に集約した
- Python向けの生成物、ローカル設定、データを `.gitignore` に追加した

### 採用した開発基盤

- 対象Pythonバージョンを3.11以上とした
- パッケージ構成にsrcレイアウトを採用した
- ビルドシステムにsetuptoolsを採用した
- PDFからのテキスト抽出に使用する実行時依存としてPyMuPDFを追加した
- テスト用のdev依存としてpytestを追加した

### 今回実装していないもの

今回はアプリケーションコードおよびテストケースを実装していない。Ollama、PySide6、FAISS、Chroma、CLIエントリーポイントも設定していない。

### 次のIssue

次のIssueでは、テキストを含む単一PDFからページ単位で文章を取得するPDF読み込み機能と、そのテストを実装する。

## Issue 002: PDF読み込み機能

実施日: 2026-08-06

### 実施内容

- PDF名、1始まりのページ番号、抽出文章を保持する不変な `PageText` データモデルを追加した
- PyMuPDFで単一PDFを開き、ページ順を維持してページ単位の文章を抽出する処理を実装した
- 一部の空ページは `text=""` として保持し、全文が空のPDFはエラーとして区別した
- 存在しないパス、通常のファイルではないパス、非PDFファイルを区別するエラー処理を追加した

### 追加したテスト

- 複数ページの文章、1始まりのページ番号、PDF名、ページ順を検証するテスト
- 文章前後の空白除去と1ページPDFを検証するテスト
- 一部の空ページを保持するテスト
- 存在しないファイル、ディレクトリ、非PDFファイル、全文空PDFのエラーを検証するテスト

### 今回実装していないもの

チャンク分割、埋め込み、検索、Ollama連携、CLI、GUI、データベースは実装していない。

### 次のIssue

次のIssueでは、各ページの文章をページ境界をまたがずに分割するチャンク分割機能と、そのテストを実装する。

## Issue 003: チャンク分割機能

実施日: 2026-08-07

### 実施内容

- PDF名、1始まりのページ番号、ページ内の位置、文章を保持する不変な `Chunk` データモデルを追加した
- `PageText` の文章を単純な文字数ベースで分割する処理を実装した
- デフォルトのチャンクサイズを1000文字、オーバーラップを150文字とした
- 各ページを独立して処理し、1つのチャンクがページ境界をまたがない設計とした
- 空文字または空白のみのページからはチャンクを生成しないようにした
- `chunk_index` はページごとに0から始まり、生成したチャンクに連番で付与するようにした
- チャンクサイズ、オーバーラップ、空のページリストに関する入力と境界条件のテストを追加した

### 今回実装していないもの

埋め込み生成、ベクトル検索、Ollama連携、CLI、GUI、SQLiteは実装していない。

### 次のIssue

次のIssueでは、チャンクから検索用ベクトルを作成する埋め込み生成機能と、そのテストを実装する。

## Issue 004: Ollamaによる埋め込み生成

実施日: 2026-08-07

### 実施内容

- 元の `Chunk` と変更されにくい埋め込みベクトルを保持する、不変な `EmbeddedChunk` データモデルを追加した
- 複数の `Chunk.text` をOllamaの埋め込みAPIへ渡し、元の順番を維持して `EmbeddedChunk` へ変換する機能を追加した
- OllamaとのHTTP通信を `ollama_client.py`、Chunkとの対応付けを `embedder.py` に分離した
- Ollamaの接続先と埋め込みモデル名を呼び出し側から差し替えられるようにした
- HTTP通信にはPython標準ライブラリを使用し、新しい外部依存は追加しなかった
- 応答件数、空ベクトル、数値、有限値、次元数を検証し、不正な応答をエラーにした
- 単体テストではHTTP通信をfakeまたはmonkeypatchで差し替え、実際のOllamaへ接続しないようにした

### 手動接続確認

通常の単体テストとは別に、Ollamaを起動して使用する埋め込みモデルを用意したうえで、モデル名を指定して確認する。

```bash
ollama serve
ollama pull <embedding-model>
python -c 'from research_rag.ollama_client import OllamaClient; print(OllamaClient().embed_texts(["manual embedding test"], model="<embedding-model>"))'
```

### 今回実装していないもの

ベクトル類似度検索、回答生成、CLI、GUI、SQLite、FAISS、Chromaは実装していない。

### 次のIssue

次のIssueでは、埋め込みベクトルを用いたベクトル類似度検索と、そのテストを実装する。

## Issue 005: ベクトル類似度検索

実施日: 2026-08-07

### 実施内容

- 2つの有限な非ゼロベクトル間のコサイン類似度を計算する処理を実装した
- NumPyなどの外部依存を追加せず、Python標準ライブラリの `math` で内積とノルムを計算した
- 元の `Chunk`、コサイン類似度、1始まりの順位を保持する不変な `SearchResult` データモデルを追加した
- `EmbeddedChunk` を類似度の降順に並べ、デフォルトで上位3件を返す検索処理を実装した
- 同じscoreの結果はPythonの安定ソートにより入力順を維持し、決定的な結果にした
- 空、次元不一致、ゼロ、非有限値を含むベクトルと、不正な `top_k` をエラーにした
- Retrieverを純粋な検索処理とし、Ollama通信や質問文の埋め込み生成を含めない設計にした

### 今回実装していないもの

質問文の埋め込み生成との統合、LLMによる回答生成、RAGサービス統合、CLI、GUI、SQLite、FAISS、Chromaは実装していない。

### 次のIssue

次のIssueでは、LLM回答生成、または質問の埋め込み生成から検索までを接続するRAGサービス統合を実装する。

## Issue 006: 検索結果を根拠とする回答生成

実施日: 2026-08-07

### 実施内容

- Retrieverが返した `SearchResult` を根拠として、Ollamaの生成モデルへ回答生成を依頼できるようにした
- LLMの回答本文と実際に使用した検索結果を保持する、不変な `RagAnswer` データモデルを追加した
- LLMへ、与えた資料だけを根拠にし、判断できない場合はその旨を示し、資料にない内容を推測で断定しないよう指示した
- 検索順位、PDF名、1始まりのページ番号、チャンク本文をrank順にLLMのコンテキストへ渡すようにした
- 引用情報はLLM出力から解析せず、アプリケーションが保持する元の `SearchResult` から `RagAnswer.sources` を構成する設計にした
- OllamaとのHTTP通信を `ollama_client.py`、プロンプト構築と根拠の対応付けを `rag_service.py` に分離した
- Ollamaの非ストリーミングチャットAPIに対応し、回答フィールドと空回答を検証する処理を追加した
- 単体テストではfakeとmonkeypatchを使い、実際のOllamaへ接続しないようにした

### 今回実装していないもの

PDF読み込みから回答生成までの一括実行、質問embedding生成との統合、CLI、GUI、SQLite、会話履歴、FAISS、Chromaは実装していない。

### 次のIssue

次のIssueでは、PDF読み込みから回答生成までのRAGパイプラインとCLIを統合する。

## Issue 007: 単一PDFへ質問できるCLI版MVP

実施日: 2026-08-07

### 実施内容

- PDF Reader、Chunker、Embedder、Retriever、回答生成を統合し、単一PDFから `RagAnswer` まで一連の処理を実行できるようにした
- PDF、`PageText`、`Chunk`、`EmbeddedChunk`、質問embedding、`SearchResult`、`RagAnswer` の順に既存機能を接続した
- Chunkと質問のembeddingに同じ埋め込みモデル名と同じ `OllamaClient` を使用する設計にした
- 質問は1件の文字列として直接埋め込みAPIへ渡し、質問用の不要な `Chunk` を作成しないようにした
- 検索件数 `top_k` のデフォルトを3とした
- `argparse`を使用し、PDFパス、質問、埋め込みモデル、生成モデル、検索件数、Ollama接続先を指定できるCLIを追加した
- 回答本文と引用情報を分離して表示し、PDF名、1始まりのページ番号、検索順位、類似度、根拠本文は `RagAnswer.sources` の `SearchResult` から取得するようにした
- PDF、質問、Ollama、モデル、検索に関する下位レイヤーのエラーをCLIで人間向けに表示し、非0で終了するようにした
- 通常の単体テストではfakeとmonkeypatchを使用し、実際のOllamaへ接続しないようにした
- PDFを指定して質問し、回答と根拠を表示するCLI版MVPの完成条件を満たした

### 実機確認

- 実PDFから回答と参照情報まで正常に出力できることを確認した
- `qwen3:4b` ではthinkingが回答本文へ混入したため、最終回答だけを生成できた `qwen3:4b-instruct` をデフォルト生成モデルに変更した

### 開発環境

macOSで `.venv` 内のeditable install用 `.pth` にhiddenフラグが付いた事例があったため、現在の仮想環境ディレクトリ名に合わせてREADMEの手順を `venv` へ更新した。

### 今回実装していないもの

GUI、SQLite、複数PDF、会話履歴、FAISS、Chroma、OCR、引用ページへの移動、LaTeX出力、App Store対応、LangChain、LlamaIndexは実装していない。

### 次の段階

実際の研究PDFを用いて、抽出品質、チャンク設定、モデル選択、検索精度、回答品質を評価し改善する。

## Issue 008: Retriever検索品質の評価基盤

実施日: 2026-08-08

### 実施内容

- Retrieverのアルゴリズムを改善する前に、`SearchResult`と正解ページを比較する純粋な評価基盤を追加した
- 質問ごとに複数の正解ページを許容し、Hit@1、Hit@3、first relevant rankを記録できるようにした
- 複数ケースのHit@1率、Hit@3率、Mean Reciprocal Rank（MRR）を標準ライブラリだけで集計できるようにした
- 空の評価結果は率と平均を定義できないため、集計時にエラーとする設計にした
- 実PDFはGit管理せず、質問、正解ページ、検索結果、指標、考察を `docs/retrieval_evaluation.md` に記録する方針とした
- 文書全体を問うglobal questionと局所Chunkを検索するlocal retrievalの性質の違いを、今後の改善候補として記録した

### 今回変更していないもの

Retriever、埋め込みモデル、chunk_size、overlap、RAGサービス、回答生成、CLIは変更していない。

### 次のIssue

複数の評価ケースを実PDFで測定し、そのHit率、MRR、失敗例に基づいてRetrieverの改善方法を決定する。

## Issue 009: 実PDF用baseline evaluation runner

実施日: 2026-08-08

### 実施内容

- Issue 008の評価ロジックをPDF Reader、Chunker、Embedder、Retrieverへ接続するbaseline runnerを追加した
- 同一PDFの読み込み、Chunk分割、文書Chunk embeddingを1回だけ実行し、全評価ケースで再利用する設計にした
- 各質問は個別にembeddingし、既存Retrieverの上位3件を`evaluate_retrieval`へ渡すようにした
- ケースごとのquestion、正解ページ、取得ページ、first relevant rank、Hit@1、Hit@3と、集計したHit@1率、Hit@3率、MRRを整形して表示できるようにした
- 実PDFで確認した12件のbaselineケースを追加し、実行前に1始まりのページ対応を人間が確認できる形で文書化した
- 通常テストではfakeを使用し、実PDFとOllamaを必要としないようにした
- LLM回答生成は接続せず、Ollamaは質問と文書のembedding生成だけに使用する設計を維持した

### 今回変更していないもの

Retriever、コサイン類似度、embeddingモデル、chunk_size、overlap、RAG回答生成、CLIは変更していない。実PDFもGitへ追加していない。

### 次の段階

確定した12ケースでbaseline runnerを実行し、Hit@1、Hit@3、MRRと失敗例を記録する。

## Issue 010: Retrieval failure diagnosis

実施日: 2026-08-08

### 実施内容

- Retrieverを変更する前に、full rankingから検索失敗の原因を観察する診断機能を追加した
- 診断表示用のTop Nと、正解ページに属するすべてのChunkを分けて保持できるようにした
- 正解ChunkがTop 10外でもfirst relevant rank、score、chunk_index、本文を確認できるようにした
- PDF読み込み、Chunk分割、文書Chunk embeddingを1回だけ実行し、複数の診断ケースで再利用するrunnerを追加した
- 各質問だけを個別にembeddingし、既存Retrieverへ全Chunk件数を`top_k`として渡す設計にした
- 実PDFとOllamaを使わない単体テストで、full ranking、複数の正解Chunk、処理回数、入力検証、レポート出力を確認した
- 初期診断対象をBaseline v1でTop3 missとなったCase 4とCase 8とした

### 今回変更していないもの

Retriever、コサイン類似度、chunk_size、overlap、embeddingモデル、本番RAGのtop_k、RAGサービス、CLI、生成モデルは変更していない。検索精度そのものの改善も行っていない。

### 次の段階

実PDFでCase 4とCase 8を診断し、正解Chunkの実順位、score差、Chunk境界を記録したうえで、証拠に基づく改善仮説を決定する。

## Issue 011: Heading-aware Chunking Comparison Experiment

実施日: 2026-08-08

### 実施内容

- numbered section headingをhard boundaryとして扱う実験用Candidate Chunkerを追加した
- 1行の番号付き見出しと、PDF抽出で番号とタイトルが改行された見出しを一般的な正規表現で検出するようにした
- 見出しを削除せず新section側に残し、section内は既存と同じ文字数ベース、デフォルト1000文字、overlap 150文字で分割するようにした
- Figure／Table由来テキストを削除せず、boundary placementだけをBaselineから変更した
- 同じ12ケースについてBaselineとCandidateのHit@1、Hit@3、MRR、差分、ケース別検索結果を比較するrunnerを追加した
- PDF読み込みを1回、Baseline／CandidateのChunk embeddingを各1回とし、各質問のembeddingを両方の検索で再利用する設計にした
- 通常テストではfakeとmonkeypatchを使い、実PDFやOllamaへ接続せず処理回数と比較結果を確認した

### 実装時に変更していないもの

本番Chunker、Retriever、Embedder、RAGサービス、CLI、本番のchunk_size、overlap、埋め込みモデル、top_k、生成モデルは変更していない。比較実験コードの実装時点ではCandidateの採用判断を行わなかった。

### 実PDF比較結果

- BaselineはHit@1=`0.4167`、Hit@3=`0.8333`、MRR=`0.6111`だった
- CandidateはHit@1=`0.4167`、Hit@3=`0.5833`、MRR=`0.4861`だった
- Candidateの差分はHit@1=`+0.0000`、Hit@3=`-0.2500`、MRR=`-0.1250`だった
- Case 8はTop3 missからrank 1へ改善し、heading boundaryによるノイズ分離の効果を確認できた
- Case 5、6、10、11は新たにTop3 missとなり、一律のhard boundaryが文脈を分断しすぎる可能性が示された
- 全体指標が悪化したためCandidateは本番Chunkerへ採用せず、実験コードは再現性のため保持することにした

### 次の段階

アルゴリズムを変更する前に、Case 8が改善し、Case 5、6、10、11が悪化した理由を診断する。
