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

## Issue 012: Chunking Regression Diagnosis

実施日: 2026-08-08

### 実施内容

- BaselineとHeading-aware Candidateのfull ranking、Top 5、正解Chunkを直接比較する診断モジュールを追加した
- 正解ChunkがTop 5外でもfirst relevant rankとbest relevant scoreを取得できるようにした
- rank、ページ番号、chunk_index、score、文字数、本文を保持する診断用データを追加した
- relevant page上で各variantが生成した全Chunkの個数、chunk_index、文字数、本文を比較できるようにした
- 文書全体のChunk数と文字数の最小、最大、平均、中央値を標準ライブラリで計算するようにした
- PDF読み込みを1回、Baseline／CandidateのChunk embeddingを各1回とし、質問embeddingを両variantのfull rankingで再利用する設計にした
- 実PDFとOllamaを使わない単体テストで、診断情報、統計、処理回数、入力検証、レポートを確認した
- 初期診断対象をCase 5、6、8、10、11とし、任意の`RetrievalEvaluationCase`を渡せる設計を維持した

### 今回変更していないもの

本番Chunker、実験用Heading-aware Chunker、Retriever、Embedder、RAGサービス、CLI、chunk_size、overlap、埋め込みモデル、本番top_kは変更していない。Chunkingアルゴリズムの改善やCandidateの再採用も行っていない。

### 実PDF診断結果

- Case 8ではheading boundaryによるFigure／Table由来ノイズとsection本文の分離が有効だった
- p.26ではグラフ軸目盛りの`0.7`、`0.6`、`0.5`がnumber-only headingとして誤検出され、それぞれ3文字の極小Chunkになっていた
- 現在のregexでは`.`はすでにliteral periodとしてエスケープされており、number-only判定が小数値そのものを許容することがfalse positiveの原因だった
- 極小ChunkによってChunk数と検索ランキングが不要に変化している可能性が高いと判断した
- Case 11はrank 3からrank 4程度への変化であり、文脈破壊だけを原因と断定できないと記録した
- Issue 012では診断結果だけを記録し、Chunkingおよびheading detectionの実装は変更しなかった

### 次の段階

Chunking戦略を変えず、heading detectionのfalse positiveだけを改善する比較実験を行う。

## Issue 013: Heading Detection False-positive Fix Experiment

実施日: 2026-08-08

### 実施内容

- Candidate v1を保持したまま、heading detectionだけを保守的にしたCandidate v2を別モジュールへ追加した
- 同一行の番号付きheadingは維持し、number-only行は周辺のtitle-like行とbody-like行を確認してからsplit headingと判定するようにした
- 直前の非空行が数値の場合はsplit headingにしないことで、連続したグラフ軸目盛りのfalse positiveを抑制した
- `4.2`改行`Data`のような本物のsplit headingは、後続本文を含む文脈によって検出できるようにした
- Baseline、Candidate v1、Candidate v2のChunk数、Hit@1、Hit@3、MRR、3種類の差分、ケース別結果を比較するrunnerを追加した
- PDF読み込みを1回、Chunk embeddingをvariantごとに1回とし、各質問のembeddingを3 variantの検索で再利用する設計にした
- 通常テストではfakeとmonkeypatchを使い、実PDFやOllamaを必要とせずdetectorと処理回数を検証した

### 実装時に変更していないもの

本番Chunker、Candidate v1、Retriever、Embedder、RAGサービス、CLI、本番のchunk_size、overlap、top_k、埋め込みモデルは変更していない。比較実験コードの実装時点ではCandidate v2の採用判断を行わなかった。

### 実PDF比較結果

- Chunk数はBaseline=`204`、Candidate v1=`316`、Candidate v2=`218`だった
- Candidate v2はHit@1=`0.4167`、Hit@3=`0.7500`、MRR=`0.5417`だった
- Candidate v2 - Candidate v1はHit@1=`+0.0000`、Hit@3=`+0.1667`、MRR=`+0.0556`だった
- Candidate v2 - BaselineはHit@1=`+0.0000`、Hit@3=`-0.0833`、MRR=`-0.0694`だった
- false positive修正によって不要なChunkが減少し、Hit@3とMRRが明確に回復した
- Case 8のrank 1を維持し、Case 10とCase 11はTop3へ回復した
- Case 3、5、6のregressionはCandidate v2にも残った
- Baselineの全体指標には届かないためCandidate v2を本番Chunkerへ採用せず、Candidate v1／v2は再現性のため保持することにした

### 次の段階

BaselineとCandidate v2についてCase 3、5、6のfull rankingとrelevant page Chunk構造を比較し、正しいheading boundary自体によるregressionを診断する。

## Issue 014: Strict Heading Regression Diagnosis

実施日: 2026-08-08

### 実施内容

- BaselineとCandidate v2のfull ranking、Top 5、first relevant rank、best relevant scoreを比較する診断モジュールを追加した
- relevant page上の全Chunkについて、full ranking上のrank、score、chunk index、文字数、本文を並べられるようにした
- Candidate v2の既存heading detectorを診断側で再利用し、Chunk先頭の`starts_with_heading`を記録するようにした
- PDF extractionを1回、Baseline／Candidate v2のChunk embeddingを各1回とし、各質問のembeddingを両variantの検索で共有するrunnerを追加した
- 既存Retrieverへvariantごとの全Chunk件数を`top_k`として渡し、コサイン類似度を再実装せずfull rankingを取得するようにした
- 実PDFとOllamaを使わない単体テストで、Top 5外の正解順位、正解ページの全Chunk、処理回数、query embeddingの同一性、入力検証、比較レポートを確認した
- 初期診断対象をCase 3、5、6、8としつつ、任意の`RetrievalEvaluationCase`を扱える設計にした

### 今回変更していないもの

本番Chunker、Candidate v1、Candidate v2、Retriever、Embedder、RAGサービス、CLI、chunk_size、overlap、top_k、埋め込みモデルは変更していない。新しいChunking戦略や検索精度改善は導入していない。

### 次の段階

実PDFでCase 3、5、6、8を診断し、見出し境界による本文移動、overlapの消失、Chunk短縮、競合Chunkのscore変化を比較して、次の改善実験で変更する要因を1つに絞る。

## Issue 015: Propagate section headings to continuation chunks

実施日: 2026-08-08

### 実施内容

- Candidate v2を変更せず、strict heading boundaryを再利用するCandidate v3を別モジュールへ追加した
- long sectionの継続Chunkだけへsection headingと改行を付加し、最初のChunkとbody windowはCandidate v2と同一にした
- headingの重複、section間およびページ間の誤伝播を防ぎ、prefix分だけ`chunk_size`を超え得ることを明記した
- Baseline、Candidate v2、Candidate v3を同じ12ケース、embedding model、`top_k=3`で比較するrunnerを追加した
- PDF extractionを1回、variantごとのChunk embeddingを各1回、question embeddingを1ケース1回とし、同じquery vectorを3 variantで再利用した
- 実PDFとOllamaを使わない単体テストでCandidate v3の境界動作、処理回数、query vector共有、集計、report、入力検証を確認した

### 実PDF比較結果

- Chunk数はBaseline=`204`、Candidate v2=`218`、Candidate v3=`218`だった
- Candidate v3はHit@1=`0.4167`、Hit@3=`0.6667`、MRR=`0.5139`だった
- Candidate v3 - Candidate v2はHit@1=`+0.0000`、Hit@3=`-0.0833`、MRR=`-0.0278`だった
- Case 5の直接回答Chunkはrank 8／score `0.476530`からrank 7／`0.479945`へ改善したがTop 3外だった
- Case 6の直接回答Chunkはrank 9／score `0.528817`からrank 7／`0.552513`へ改善したがTop 3外だった
- Case 3はrank 3／score `0.491621`のまま、Case 8はrank 1／`0.539355`を維持した
- Case 11がCandidate v2のrank 3からCandidate v3のTop3 missへ悪化した

### 採否と変更していないもの

Candidate v3はCandidate v2よりHit@3とMRRが低いため、本番Chunkerへ採用しない。Candidate v3は再現性のため実験コードとして保持する。本番Chunker、Candidate v1／v2、Retriever、Embedder、RAGサービス、CLI、chunk_size、overlap、production top_k、embedding model defaultは変更していない。

### 次の段階

headingを一律に反復する案から離れ、Case 3の競合Chunk、Case 5／6のcross-lingualまたはscope条件、Case 11の新規regressionを証拠に基づいて切り分ける。

## Issue 016: Diagnose query-language and scope sensitivity in dense retrieval

実施日: 2026-08-09

### 実施内容

- 任意の`RetrievalEvaluationCase`と複数のquery variantを受け取る診断専用モジュールを追加した
- 各variantについてfull ranking、first relevant rank、best relevant score、Hit@3、Top 5、relevant page上の全Chunkを保持し、基準variantとの差分を表示できるようにした
- PDF extraction、Baseline Chunk分割、文書Chunk embeddingを各1回だけ行い、各query variantを1回ずつembeddingするrunnerを追加した
- 既存Retrieverへ`top_k=len(embedded_chunks)`を渡し、コサイン類似度を再実装せずfull rankingを取得した
- 実PDFとOllamaを使わない単体テストで、処理回数、full ranking、Top 5差分、入力検証、レポートを確認した
- 実PDFのCase 4、5、6、8について`original_ja`、`english_equivalent`、`concise_scope_preserving_en`を比較した

### 実PDF診断結果

- Case 4は英語化でdirect-answer Chunkがrank 24から14へ改善したが、英語でもTop 5外であり、scope条件の識別問題が残った
- Case 5は簡潔な英語でdirect-answer Chunkがrank 1になった一方、忠実な英訳ではrank 4であり、英語化だけでは一貫した改善にならなかった
- Case 6は英語化でdirect-answer scoreが上昇したがrank 2から5へ悪化し、競合Chunkのscore変化が順位へ影響した
- Case 8は忠実な英訳でrank 7から6への小幅改善に留まり、簡潔な英語ではrank 7だった
- page-level first relevant rankとdirect-answer Chunkのrankが異なるCase 5、および理由がchunk 2／3の境界にまたがるCase 6を明示的に区別して記録した

### 今回変更していないもの

本番Chunker、Candidate v1／v2／v3、Retriever、Embedder、RAGサービス、CLI、chunk_size、overlap、production top_k、embedding model default、回答生成は変更していない。translation、query rewriting、reranking、hybrid retrievalもproductionへ追加していない。

### 次の段階

query-languageだけでは順位改善が一貫しなかったため、scope条件、競合Chunk、Chunk contaminationを分け、Baselineとの比較で1要因ずつ検証する。

## Issue 017: Evaluate LLM reranking over dense retrieval candidates

実施日: 2026-08-09

### 実施内容

- productionのBaseline dense retrieval Top 30を既存ローカル生成LLMで再順位付けする実験用rerankerを追加した
- stable candidate ID、scope／条件／直接回答を重視するprompt、strict JSON parserを分離した
- 重複IDは最初の出現だけを採用し、欠落候補はdense順で末尾へ補完し、未知IDとmalformed outputは明示的エラーにした
- PDF extraction、Baseline Chunk分割、文書embeddingを各1回、各元質問のembeddingとrerankingを各1回にした実験runnerを追加した
- 同じquery embeddingをBaseline Top 3、Dense Top 30、dense full rankingで再利用し、既存Retrieverだけで候補を生成した
- `OllamaClient.generate_chat()`へ任意のgeneration optionsを追加したが、未指定時のproduction requestは従来と同じに保った
- mockだけを使う単体テストで処理回数、ID検証、重複、未知ID、欠落候補、rank再付与、prompt、集計、report、入力検証を確認した

### 実PDF結果

- 使用モデルはembedding=`qwen3-embedding:0.6b`、generation=`qwen3:4b-instruct`
- Candidate poolはTop 30、final cutoffはTop 3、generationは`num_ctx=32768`、`num_predict=512`、`temperature=0`、`think=false`とした
- Candidate-pool Recall@30は`12/12`だった
- BaselineのHit@1／Hit@3／MRR=`0.4167 / 0.8333 / 0.6111`に対し、rerankingは`0.8333 / 1.0000 / 0.9028`だった
- Case 4、5、7、8、11が改善し、Case 10はrank 2から3へ悪化したがTop 3を維持した
- Case 4のdirect-answer Chunkはrank 24から1、Case 5は3から1、Case 8は7から1へ移動した
- Case 6では結論側のp.23 / chunk 3がrank 2から4へ下がった一方、具体的理由を含むchunk 2がrank 8から2へ上がった
- promptは`28,162`〜`32,431`文字、rerankingは合計`556.278`秒、平均約`46.4`秒、全experimentは`592.720`秒だった
- 実行時はgeneration modelが32K contextで`7.4 GB`、embedding modelが`2.4 GB`のGPU memoryを使用した

### 採否と変更していないもの

品質条件は満たしたが、1質問約35〜63秒の追加遅延は既定のローカルRAGとして重いため、Issue 017ではproductionへ採用しない。実験コードと結果は再現性のため保持する。本番Retriever、Chunker、Embedder、RAGサービス、CLI、production top_k、query、回答生成promptは変更しておらず、translationやquery rewriteも追加していない。

### 次の段階

Retrieval tuningは一度区切る。LLM rerankingを統合する場合は別Issueでopt-in動作、latency表示、context／memory要件、失敗時のfallbackを明確にする。それ以外は複数PDF、永続化／文書管理、会話履歴、GUIなどのapplication機能へ進む。

## Issue 018: Add in-memory multi-PDF RAG support

実施日: 2026-08-09

### 実施内容

- 1つ以上のPDFを受け取る`answer_question_from_pdfs()`を追加し、既存の`answer_question_from_pdf()`を互換ラッパーとして維持した
- PDFを入力順に各1回だけ抽出し、結合したページ群をproduction Chunkerへ1回だけ渡すようにした
- 全PDFのChunkをまとめて1回だけembeddingし、質問も1回だけembeddingして、既存Retrieverで全PDF横断のglobal rankingを行うようにした
- `document_name`とPDFごとに1始まりの`page_number`を既存データモデルのまま保持した
- 同じbasenameのPDFが複数ある場合は抽出前にエラーとし、出典名の衝突を防ぐようにした
- 文章を抽出できないPDFだけを識別する`NoExtractableTextError`を`ValueError`互換のサブクラスとして追加した。一部のPDFだけが空なら続行し、全PDFから検索可能なChunkを作れない場合は明確なエラーにした
- CLIの既存の位置引数形式を維持し、追加PDFを繰り返し`--pdf`で指定できるようにした
- fakeを使う単体テストで、処理回数、入力順、global ranking、複数文書の出典、入力検証、空PDF、下流エラー、単一PDF互換性を確認した
- Git管理外の1ページtext PDFを2件作成してローカルOllamaでCLI smoke testを行い、質問に対応する`borealis.pdf p.1`がglobal rank 1、`atlas.pdf p.1`がrank 2として表示されることを確認した

### 今回追加していないもの

永続化、SQLite、FAISS／ChromaなどのベクトルDB、GUI、フォルダ自動収集、rerankingは追加していない。PDF Reader、production Chunker、Embedder、Retrieverのアルゴリズムと既定設定は変更していない。

### 次の段階

複数質問で同じ文書集合を再利用する場合のindex lifecycleと、必要性を評価したうえでの永続化／文書管理を検討する。

## Issue 019: Add reusable in-memory RAG index lifecycle

実施日: 2026-08-09

### 実施内容

- 文書名、build時のembedding model、準備済み`EmbeddedChunk`だけを保持するimmutableな`RagIndex`を追加した
- `build_rag_index()`へPDF extraction、production chunking、文書embeddingを分離し、複数PDFの文書側処理を1回で完了できるようにした
- `answer_question_from_index()`へ質問embedding、global retrieval、回答生成を分離し、質問embeddingには常にindexに記録されたモデルを使うようにした
- `RagIndex`にはOllama clientとgeneration modelを保持せず、純粋なインメモリデータとして扱う設計にした
- 既存の`answer_question_from_pdfs()`をbuild＋answerの合成へ変更し、`answer_question_from_pdf()`とCLIのAPI・構文・出典表示を維持した
- 同じindexへ2回質問してもPDF extraction、chunking、文書embeddingが再実行されず、質問embedding、retrieval、generationだけが各2回実行されることを単体テストで確認した
- 複数PDFの入力順、`document_name`、PDFごとに1始まりのページ番号、duplicate basename、no-text PDF、下流エラーの既存動作を維持した
- 手動構築された空index、空のembedding model、空質問、空generation model、不正な`top_k`を質問処理前に拒否するテストを追加した
- Git管理外の2つの小型text PDFからindexを1回buildし、同じindexへwind／solarの2質問を実行するローカルOllama smoke testを行った。各回答で`borealis.pdf p.1`／`atlas.pdf p.1`がそれぞれglobal rank 1になり、同じindex objectと複数文書の出典が再利用された

### 今回追加・変更していないもの

SQLite、ファイル保存、serialization、永続embedding、vector DB、GUI、conversation history、rerankingは追加していない。PDF Reader、Chunker、Embedder、Retriever、実験モジュールのアルゴリズム、chunk size、overlap、Top K既定値、生成prompt、CLI syntaxは変更していない。

### 次の段階

永続化／文書管理のIssueで、durable document ID、PDF更新検出、prepared chunk／embeddingの保存形式、追加・削除・再indexの挙動を決定する。

## Issue 020: Persist reusable RAG indexes with SQLite

実施日: 2026-08-09

### 実施内容

- Python標準の`sqlite3`だけを使う専用永続化層`SQLiteRagIndexStore`を追加し、complete indexのinitialize／save／load／list／deleteを実装した
- `store_metadata`へ`schema_version=1`を保存し、初期化をidempotentにするとともに未対応versionを`RagIndexStoreError`で拒否するようにした
- 保存indexと各documentへUUIDを割り当て、documentの入力順、名前、正規化した絶対source path、chunkのglobal orderを保存するようにした
- 検索用embeddingをpickleではなくlittle-endian IEEE-754 float64 BLOBとして保存し、dimension、BLOB長、非有限値をload時に検査するようにした
- saveを単一SQLite transactionとし、途中失敗時のrollbackを確認した。deleteはforeign key cascadeで関連document／chunkを削除する
- `list_indexes()`はembedding列をSELECTせず、作成日時、embedding model、文書metadata、chunk数だけを返すようにした
- source PDFが存在しなくても、新しいstore instanceから`RagIndex`を復元できるようにした。復元時にPDF extractionやOllamaは呼ばない
- loadしたindexを既存`answer_question_from_index()`へそのまま渡せることを、Ollamaを使わない単体テストで確認した
- `tmp_path`だけを使うfocused testでschema、UUID、path検証、round trip、float64 encoding、破損検出、軽量list、cascade、rollback、invalid IDを確認した
- Git管理外の2つの小型text PDFでbuild→SQLite save→新しいstore instance→load→質問のローカルsmoke testを実行し、`loaded == built`、2文書／2Chunkの保持、`borealis.pdf p.1`のglobal rank 1回答を確認した

### 今回追加・変更していないもの

外部DBライブラリ、SQLAlchemy、pickle、FAISS／Chroma、incremental document mutation、自動再index、file hash／mtime監視、GUI、conversation history、production rerankingは追加していない。`RagIndex`、既存RAG service、PDF Reader、Chunker、Embedder、Retriever、生成prompt、CLI syntaxは変更していない。

### 次の段階

document-management lifecycleのIssueで、既存indexへの追加・削除・再index、PDF変更検出、ユーザーがpersistent corpusを選択・管理する方法を設計する。
