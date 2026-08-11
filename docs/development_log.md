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

## Issue 021: Add persistent document lifecycle and change detection

実施日: 2026-08-09

### 実施内容

- SQLite schemaをversion 2へ更新し、既存schema v1のindex／document／chunk／embeddingとUUIDを維持する明示的かつtransactionalなv1→v2 migrationを追加した
- documentごとに`content_sha256`、`file_size`、`mtime_ns`、`indexed_at`を保存し、SHA-256を変更判定の正とした。v1から移行した文書と低水準`save_index()`で保存した文書はfingerprintを推測せず`UNKNOWN`とする
- schema v2の複合外部キーで、Chunkの`index_id`と別indexに属する`document_id`を組み合わせられないようにした
- 軽量な`get_index_metadata()`と、atomicな文書追加・削除・Chunk置換用store methodを追加した。metadata/status操作ではembedding BLOBを復元しない
- `PersistentRagDocumentManager`を追加し、`create_index()`、`inspect_documents()`、`add_document()`、`remove_document()`、`reindex_document()`を実装した
- source fileをstreaming SHA-256で処理し、create／add／reindexの前後で内容が変わっていないことを確認してから永続化するようにした
- `CURRENT`／`MODIFIED`／`MISSING`／`UNKNOWN`を区別し、inspectionからPDF extraction、Chunking、Ollama、検索、生成、DB mutationを分離した
- add／remove／reindexではindex IDを維持し、変更しないdocument IDとembeddingを再生成しない。reindexでは対象document IDとpositionを維持する
- mutation後のglobal Chunk順をdocument position順かつ連続に保ち、最後の検索可能文書を削除する操作を拒否するようにした
- schema migration、fingerprint/status、処理回数、ID保持、順序、cross-index制約、失敗時rollback、既存API互換性を`tmp_path`とmockだけで検証する単体テストを追加した
- Git管理外の3つの小型text PDFとローカルOllamaでcreate→`CURRENT`→source変更→`MODIFIED`→対象1冊のreindex→`CURRENT`→add→remove→store再生成→load→質問のsmoke testを実行した。同じindex ID、再index／未変更文書のdocument ID、`tides.pdf`→`aurora.pdf`の文書順を維持し、質問では`aurora.pdf p.1`がrank 1になった

### 今回変更・追加していないもの

既存CLI syntax、PDF Reader、production Chunker、Embedder、Retriever、RAG service、実験Chunker／reranker、chunk size、overlap、Top K、生成promptは変更していない。GUI、interactive管理CLI、file watcher、自動再index、background job、conversation history、vector DB、新しい外部依存は追加していない。

### 次の段階

永続corpusと文書状態を一覧し、追加・削除・再indexと`answer_question_from_index()`による質問を操作できる小さなPySide6 GUI foundationを検討する。

## Issue 022: Add PySide6 desktop GUI foundation

実施日: 2026-08-09

### 実施内容

- runtime依存へPySide6を追加し、`python -m research_rag.gui_app`で起動するQt WidgetsデスクトップGUIを追加した
- CLIとGUIがembedding model=`qwen3-embedding:0.6b`、generation model=`qwen3:4b-instruct`、top_k=`3`を同じ定数から参照するようにし、既存CLIの構文と動作を維持した
- `RagGuiService`を追加し、`SQLiteRagIndexStore`、`PersistentRagDocumentManager`、`answer_question_from_index()`を再利用して、WidgetからSQLとRAG処理を分離した
- 保存済み資料セット一覧、文書名・状態・source path、新規資料セット作成、PDF追加、再インデックス、削除、状態更新、質問と参照表示を1つのMainWindowへ実装した
- 資料セットと文書のUUIDはQt item dataに保持し、利用者向け表示ではPDF名を基にしたラベルを使用した
- GUIの既定DBを`QStandardPaths.AppDataLocation/indexes.sqlite3`とし、元PDFをコピーせず、資料削除でも元PDFを削除しないことを確認ダイアログとREADMEに明記した
- `QThreadPool`／`QRunnable`のfinite workerを追加し、作成・追加・削除・再インデックス・状態確認・質問をGUI thread外で実行するようにした。処理中は競合操作を無効化し、失敗時もエラー表示後にUIを復帰させる
- `QT_QPA_PLATFORM=offscreen`とmock／fakeを使う単体テストを追加し、実ユーザーデータ領域、実PDF、実Ollamaを通常テストで使用しないようにした
- Git管理外の一時DBと3つの小型text PDF、ローカルOllama、実際のMainWindow／Qt workerで、create→`CURRENT`→source変更→`MODIFIED`→reindex→`CURRENT`→add→remove→question→store／window再生成後の永続状態復元を確認した。削除対象の元PDFは残り、質問では`rank 1 / tides.pdf p.1`の根拠と回答が表示された

### 今回変更・追加していないもの

既存CLI syntax、SQLite schema、PDF Reader、production Chunker、Embedder、Retriever、RAG serviceのアルゴリズム、生成prompt、experimental Chunker／rerankerは変更していない。会話履歴、file watcher、自動再インデックス、vector DB、GUI専用のSQL／RAG再実装、`pytest-qt`などの追加依存も導入していない。

### 次の段階

GUI foundationを実機で検証し、必要に応じて資料セット名の編集、進捗表示、操作性改善を独立したIssueで検討する。

### Native teardown crashの追加調査

- macOS／Python 3.11／PySide6 6.11のoffscreen実行で報告された`EXC_BAD_ACCESS`を受け、active worker中のwindow close、worker完了直後のclose、application teardownを追加調査した
- PR初版の`setAutoDelete(False)`、strong reference、queued relayだけでは、active window close後にworkerが削除済みSignal sourceへemitする経路が残っていた。regression testで`Signal source has been deleted`を再現し、初版だけでは問題が完全には解消していないと判断した
- `QtTaskRunner`ごとの専用`QThreadPool`、新規受付停止、active task count、idle callback、同期shutdownを追加した。通常のwindow closeはactive task完了まで延期し、`QApplication.aboutToQuit`では`waitForDone()`後にQt objectを破棄する
- Signalとresult／error stateをGUI thread上のrelayへ移し、`QRunnable`はQtのauto-delete対象とした。queued callbackは削除済みworkerへアクセスせず、relay／stateは`_active_workers`からfinished callback後または同期shutdown後にだけ解放する
- test helperのnested `QEventLoop`を通常の`processEvents()`待機へ置き換え、重複していた`QApplication` fixtureをsession全体で1つのwrapperを保持する共通fixtureへ統合した。重複fixtureの破棄順序はpytest最終GCでSIGSEGVを再現する要因だった
- success／failure後のteardown、逐次25 worker、worker／relay解放、active close、close直前完了、application exit中のactive workerをregression testへ追加した
- 最終focused suite 24件をfaulthandler付きで成功させ、同じsuiteを別プロセスで20回連続実行してnative crashとlifetime errorが再発しないことを確認した

### QWidget teardown crashの追加調査

- active QRunnableを伴わない`QWidget::~QWidget`／`QLabel::~QLabel`／Shiboken wrapper／Python cyclic GC経路の`EXC_BAD_ACCESS`を別問題として調査した
- RAG処理を含まない`QApplication`＋`QMainWindow`＋`QWidget`＋`QLabel`の最小構成では、close-onlyを30プロセス×5,000 window、`close()`＋`deleteLater()`＋DeferredDelete処理を10プロセス×5,000 window実行してもcrashを再現しなかった。PySide6 6.11.1 offscreenの単純widget treeだけで必発する問題ではなかった
- PRの既存testは`window.close()`で非表示にするだけでC++ QObject treeの削除をPython GCへ残していた。Qt parent-child treeとchild signalからbound methodへのPython referenceが共存するため、test終了時のwrapper破棄順序を決定的にする必要があると判断した
- productionの`MainWindow`へ`WA_DeleteOnClose`を設定し、active worker完了後に受理されるclose eventでQt側がwindow treeを削除するようにした
- test session全体で1つの`QApplication` strong referenceを維持したまま、各test後にGUI threadでtop-level widgetをcloseし、必要なwidgetへ`deleteLater()`を発行し、`sendPostedEvents(..., DeferredDelete)`でC++ treeを削除してからPython GCを行う共通fixtureを追加した。`shiboken6.delete()`は使用していない
- RAGなしwidget tree 100回、実MainWindow 50回、worker success／failure／active close／完了直後closeをdeterministicに削除するregressionを追加し、MainWindowとchild wrapperのweak referenceがGC後に残らないことも確認した
- faulthandler付きfocused suite 27件を成功させ、同じsuiteをfresh processで30回連続実行してQWidget／QLabel teardown crashが再発しないことを確認した

## Issue 023: Add named corpus management and deletion

実施日: 2026-08-10

### 実施内容

- SQLite schemaをversion 3へ更新し、`rag_indexes`へnullableな`display_name`を追加した。新規DBはv3を直接作成し、既存v1／v2 DBは1つのtransaction内でv1→v2→v3の順に移行する
- migrationでは既存index／document／chunk／embedding／fingerprint／UUID／順序／timestampを維持し、移行済みcorpusの`display_name`はNULLのままとした。途中失敗時はversionを進めず全DDLをrollbackする
- 低水準save APIを互換維持したままoptionalな表示名を同じsave transactionで保存できるようにし、`PersistentRagDocumentManager.create_index()`からverified indexと名前をatomicに作成できるようにした
- 表示名は前後空白を除去し、空文字と100 Unicode文字超を拒否する。`rename_index()`は1 transactionの軽量metadata更新だけを行い、重複名を許可し、index／document UUIDとembeddingを変更・復元しない
- `RagGuiService`へ名前付き作成、rename、corpus全体削除を追加し、Widget内へSQLやRAG処理を持ち込まなかった
- GUIでは永続表示名を優先し、名前がない既存corpusは従来のPDF名ベースラベルへfallbackする。UUIDはQt item dataだけに保持する
- `新しい資料セット`でPDF選択後に先頭PDFのstemを初期値として名前を入力し、`名前を変更`と`資料セットを削除`を追加した。削除確認ではSQLite内の索引データだけを削除し、元PDFを削除しないことを明示する
- corpus削除は既存worker経由で実行し、残るcorpusを決定的に選択する。最後のcorpus削除後は文書・回答・参照と依存操作を空状態へ戻す。失敗時は選択と入力を保ってUIを復帰する
- migration／display name保存／rename identity／duplicate name／embedding非更新／service delegation／dialog cancel／UUID選択／削除確認／空状態／失敗復帰の単体テストを追加した
- `QT_QPA_PLATFORM=offscreen`の全suite 371件を成功させた。faulthandler付きworker／MainWindow focused suite 37件をfresh processで5回連続実行し、native crashとteardown errorが再発しないことを確認した
- Git管理外の一時DB、3つの小型text PDF、ローカルOllama、実際のMainWindow／Qt workerで、2-PDF corpus `研究資料 A`作成→再起動後の名前保持→`研究資料 B`へrename→同じID・document ID・RAG内容の保持→質問→同名の第2 corpus作成→順次削除→最後の削除後の空表示→再起動後も空、を確認した。corpus削除後も3つの元PDFは存在した

### 互換性と安全性

既存CLI syntax、PDF Reader、production Chunker、Embedder、Retriever、RAG service、生成prompt、モデル既定値、duplicate basename ruleは変更していない。新しい外部依存も追加していない。Issue 022の`QtTaskRunner`、close延期、session-level `QApplication`、deterministic DeferredDelete fixture、native crash regression testを維持し、nested `QEventLoop.exec()`や`shiboken6.delete()`は追加していない。

## Issue 024: Add persisted GUI runtime settings

実施日: 2026-08-10

### 実施内容

- immutableな`GuiRuntimeSettings`と、明示的に注入できるINI pathへ`QSettings`で保存する`GuiSettingsStore`を追加した
- 既定値をembedding=`qwen3-embedding:0.6b`、generation=`qwen3:4b-instruct`、Top-K=`3`、Ollama URL=`http://localhost:11434`とし、空model名、不正Top-K、HTTP(S) hostでないURLを適用前に拒否するようにした
- 設定画面をnested event loopなしのnon-blocking modal dialogとして追加し、Embedding model、Generation model、Top-K、Ollama URLの編集、Cancel、デフォルト値へのfield resetを実装した
- GUI設定をcorpus SQLiteとは別の`settings.ini`へatomicに保存し、再起動時はservice生成前に読み込むようにした。初回と不正な保存snapshotは全体を既定値へfallbackする
- Embedding model設定は新規corpus作成だけに適用し、既存corpusへの質問、追加、再インデックスでは保存済みembedding modelを維持する。選択中corpusの実際のmodelをGUIへ表示した
- Generation modelとTop-Kは次の質問から即時反映し、Ollama URL変更時はnetwork callを行わずにGUI serviceとdocument managerを同一の新clientへ切り替えるようにした
- 設定保存に失敗した場合は直前のsettings snapshotと同じclientへrollbackし、live設定と永続設定の不一致を防ぐようにした
- worker実行中は設定ボタンを無効化し、Issue 022／023のworker ownership、close延期、session-level `QApplication`、DeferredDelete cleanupを維持した
- fake clientと`tmp_path`を使う単体テストで既定値、validation、round trip、再起動、atomic save failure、Cancel／Reset／OK、既存corpus model保持、即時反映、client共有、busy状態を確認し、実Ollama／networkと実ユーザー設定領域を使用しないようにした

### 互換性と変更していないもの

corpus SQLite schemaはversion 3のまま維持し、既存corpusのindex／document／Chunk／embedding／UUID／`embedding_model`を変更していない。既存CLI syntax、PDF Reader、production Chunker、Embedder、Retriever、RAG serviceのアルゴリズム、生成prompt、worker実装は変更しておらず、新しい外部依存も追加していない。

## Issue 025: Improve GUI operation feedback and empty states

実施日: 2026-08-10

### 実施内容

- MainWindowの通常のQt widget treeへ操作メッセージlabelと`minimum=0`／`maximum=0`のindeterminate `QProgressBar`を追加し、信頼できないpercentageを表示しないようにした
- 既存`_run_task()`をbusy表示の一貫した境界として維持し、状態確認、corpus作成／rename／削除、文書追加／削除／再index、質問へ操作別のbusy／success messageを追加した
- failure時はindicatorを隠してcontrolsを復帰し、`処理に失敗しました`を表示するようにした。質問文と既存回答・参照、選択corpus、正常に描画済みの文書tableは成功するまで置き換えない
- create／deleteなどの成功後に状態確認workerが続く場合は、idle表示を描画せずbusy messageを状態確認へ遷移させ、最終的に元操作の完了messageを表示するようにした
- corpusなし／未選択時の独立したempty-state labelと、回答／参照欄のplaceholder guidanceを追加した。fakeなlist itemやtable rowは使用していない
- `DocumentStatus`の内部enumを維持したまま、GUI表示だけを`最新`／`変更あり`／`ファイルなし`／`未確認`へ変換し、各意味のtooltipを追加した
- document UUIDを従来どおりQt item dataへ保持し、資料名／状態／保存元columnをそれぞれinteractive／content-sized／stretch resizeに設定した。path tooltipも維持した
- 回答と参照のrank、PDF名、1始まりpage、score、source textのplain-text表示は変更せず、表示領域のminimum heightとplaceholderだけを追加した
- fake service／queued runnerを使うGUIテストでindeterminate busy state、全status表示、empty state、success／failure、逐次処理、follow-up refresh、failure時のstate保持、既存settings制御を確認した
- `QT_QPA_PLATFORM=offscreen`とfaulthandlerを使う全suite 410件を成功させ、worker／MainWindow focused suite 48件もfresh processで5回連続成功した

### 互換性と安全性

corpus SQLite schema v3、GUI settings semantics、UUID、DocumentStatus、PDF Reader、Chunker、Embedder、Retriever、RAG prompt、page numbering、citation data、model defaults、CLI syntax／outputは変更していない。既存`QtTaskRunner`、close延期、session-level `QApplication`、DeferredDelete cleanupを維持し、nested `QEventLoop.exec()`、`shiboken6.delete()`、workerからのwidget access、新しい外部依存は追加していない。

## Issue 026: Add reproducible macOS application packaging

実施日: 2026-08-10

### 実施内容

- repository直下へ薄い`run_gui.py`を追加し、`research_rag.gui_app.main()`の呼び出し以外のGUI起動処理やRAG処理を複製しないようにした
- PySide6公式`pyside6-deploy`用の`pysidedeploy.spec`を追加し、standalone mode、表示名`Research RAG`、出力先`build/deploy`、実測済みNuitka 4.1.3を記録した。PyInstallerは使用していない
- `scripts/build_macos_app.sh`を追加し、macOS判定、`pyside6-deploy`存在確認、specからのNuitka version適用、dry-run、環境固有値を書き戻さない一時spec、stale bundle除去、実行ファイル確認を実装した
- macOSがcodesign前に拒否するFinder／resource-fork extended attributeを除去し、ローカル用ad-hoc署名とstrict検証まで成功した場合だけbuild成功とするようにした。Developer ID署名は行っていない
- `build/`、`deployment/`、`.app`、一時deploy specをGit ignore対象とし、build成果物や中間生成物をcommit対象から除外した
- launcher delegation、standalone spec、出力／ignore設定、user dataとOllama非bundle、非macOS／tool不足エラー、dry-runの一時specとversion指定、署名検証境界を確認するpackaging integration testを追加した。通常のpytestではfull Nuitka buildを実行しない

### 実機確認

- macOS 26.5.2 arm64、Python 3.11.15、PySide6 6.11.1、Nuitka 4.1.3で`./scripts/build_macos_app.sh --dry-run`を成功させた
- 同環境でbuild helperを通し実行し、171 MBの`build/deploy/Research RAG.app`を生成した。helperは最終的にexit code 0となり、arm64 Mach-O実行ファイル、Info.plistの`Research RAG`表示名、ad-hoc署名のstrict validationを確認した
- bundle内に`indexes.sqlite3`、`settings.ini`、PDF、Ollama本体、Ollama modelがないことを確認した
- Ollamaを使用せず、生成bundleをoffscreen実行とmacOSの`open -n`の両方で起動した。空GUIがevent loopへ入り、初回DBがbundle外の`~/Library/Application Support/ResearchRAG/indexes.sqlite3`へschema version 3として作成されることを確認した
- settingsは値を保存する操作を行わなかったため起動smokeでは新規作成されていないが、既存のpath unit testで同じbundle外AppDataLocationの`settings.ini`へ解決されることを確認している
- smoke前に存在しなかった`ResearchRAG` AppDataディレクトリは、schema確認後に検証残骸として削除して実行前の状態へ戻した
- 実Ollamaを使うRAG質問smokeは行っていない。今回確認したのはOllamaなしでの空GUI起動と保存先だけである
- `QT_QPA_PLATFORM=offscreen python -X faulthandler -m pytest`で最終的に全417件を成功させ、worker／MainWindow teardown 48件をfaulthandler付きfresh processで5回連続成功させた。packaging focused testは7件成功した

### 互換性と今回の対象外

`python -m research_rag.gui_app`、既存CLI、corpus SQLite schema v3、QStandardPathsによるruntime保存先、Ollama URL設定、QtTaskRunner／teardown、PDF Reader、Chunker、Embedder、Retriever、RAG serviceは変更していない。Developer ID signing、hardened runtime、notarization、DMG、Mac App Store、custom app icon、auto update、cross-platform installerは追加していない。

## Issue 027: Add macOS release metadata and notarization-ready signing workflow

実施日: 2026-08-10

### 実施内容

- macOS bundle identifierを`io.github.atraz-yuya.research-rag`へ固定し、`pyproject.toml`の`[project].version`だけをversion sourceとして`CFBundleShortVersionString`と`CFBundleVersion`へ反映するpackaging helperを追加した。production Python packageへversion定数は追加していない
- Nuitka 4.1.3の`--macos-app-version`が`CFBundleShortVersionString`だけを生成するため、専用Nuitka user pluginを追加した。pluginはNuitka自身がInfo.plistを書き出す時点で、同じproject versionを`CFBundleVersion`へ追加する
- 既存`scripts/build_macos_app.sh`をcredential-freeなローカル開発用として維持し、identifierと両version fieldをbundle署名前に完成させてから従来のad-hoc署名とstrict検証を行うようにした
- 独立した`scripts/release_macos_app.sh`を追加した。Developer ID Application identityとnotarytool Keychain profileを外部環境変数で必須化し、ad-hoc署名へfallbackしない
- release buildではNuitka native signing optionだけを使用し、Developer ID署名後にInfo.plistを変更・再署名しない。Nuitka署名済みbundleのhardened runtime、secure timestamp、signing authority、`get-task-allow`不在を検証してからnotarizationへ進む
- review指摘を受け、release helperから`codesign --force --deep`によるproduction再署名を削除した。`codesign --verify --deep --strict`はverificationとして維持し、release signingに`--deep`／`--force`を使わないregression testを追加した
- `.app`を`ditto`で事前ZIP化し、`xcrun notarytool submit --wait`へ送信する。Accepted後にstapler staple／validate、codesign、可能な場合はGatekeeper assessmentを行い、実際のarchitectureとproject versionを名前に含む最終ZIPを生成する
- notarization failure時はresult JSON、submission ID、notarytool logを確認できるようにした。`--dry-run`はbuild、署名、Keychain変更、Appleへのnetwork requestを行わない
- certificate、秘密鍵、password、Team ID、notary credentialをrepositoryへ保存せず、notarytoolにはKeychain profile名だけを渡す。`altool`は使用しない
- metadata、local build互換性、credential validation、dry-runの非作用、fake Developer ID／notary accepted／rejected workflow、処理順、actual architecture filenameを検証するpackaging integration testを追加した。自動テストは実certificate、秘密鍵、Keychain profile、Apple notary serviceを使用しない

### 実機確認

- macOS 26.5.2 arm64、Python 3.11.15、PySide6 6.11.1、Nuitka 4.1.3でlocal build dry-runとrelease `--dry-run`を成功させた。release dry-runにはversion `0.1.0`、bundle identifier、arm64想定ZIP、全stageが表示され、build、署名、Keychain変更、Appleへの通信は行われなかった
- PR初版でcredential-freeなlocal standalone buildを実行し、171 MBのarm64 `Research RAG.app`を生成した。Info.plistは`CFBundleIdentifier=io.github.atraz-yuya.research-rag`、`CFBundleShortVersionString=0.1.0`、`CFBundleVersion=0.1.0`となり、bundle内にDB、settings、PDFを含まないことを確認した。review修正版ではbuild-time plugin注入をlocal／release dry-runと自動テストで確認し、full Nuitka buildは再実行していない
- Codex managed filesystemが付与する`com.apple.provenance`／Finder属性によりhelper内のcodesignが一度拒否された。これはIssue 026と同じ環境固有条件で、許可された外側で生成bundleの属性を除去した後、local ad-hoc署名と`codesign --verify --deep --strict`を成功させた
- Developer ID Application identityは0件で、`RESEARCH_RAG_NOTARY_PROFILE`も未設定だった。そのため実Developer ID signing、実notary submission、stapling、Gatekeeper verification、最終release ZIP生成は実施していない。accepted／rejected release workflowはfake command integration testでのみ確認した
- review修正後にlocal build dry-runとrelease dry-runを再実行し、Nuitka commandへbuild-time metadata pluginが渡されることと、release dry-runが署名／Keychain／networkへ触れないことを確認した
- `QT_QPA_PLATFORM=offscreen python -X faulthandler -m pytest`で全428件を成功させ、worker／MainWindow teardown 48件をfaulthandler付きfresh processで5回連続成功させた

### 互換性と今回の対象外

GUI、RAG pipeline、CLI、corpus SQLite schema v3、QStandardPaths、QtTaskRunner／teardownは変更していない。DMG、Mac App Store、custom icon、auto update、cross-platform installer、GitHub Release automationは追加していない。

## Issue 028: Add macOS app icon, DMG packaging, and draft GitHub release flow

実施日: 2026-08-10

### 実施内容

- PySide6の`QImage`／`QPainter`だけで、documentとconnected evidence nodesを表すsquare／unmaskedな1024px master iconを決定的に描画するgeneratorを追加した。文字、`RAG` lettering、他製品markは使用していない
- 同じmasterから16／32／128／256／512 pointのstandard／Retina PNGを生成し、macOSの`iconutil`で`build/generated/ResearchRAG.icns`へ変換する。generated PNG／iconset／ICNSはGit管理しない
- FileProvider管理workspaceのquarantine／provenance属性で`iconutil`がvalid iconsetを拒否する環境に対応するため、削除対象を既知のgenerated iconset／ICNSだけに限定して属性を除去するようにした
- local／release helperの一時`pyside6-deploy` specへgenerated ICNSを渡し、app署名前に`Contents/Resources/ResearchRAG.icns`と`CFBundleIconFile`を完成させるようにした。Developer ID署名後のicon／Info.plist書換えは行わない
- build済みappを受け取り、temporary stagingへ`Research RAG.app`と`Applications -> /Applications`だけを置いてread-only UDZO DMGを作るhelperを追加した。actual Mach-O architectureとproject versionをartifact名に使い、`hdiutil verify`成功を完了条件とした
- canonical release artifactをZIPからDMGへ変更した。NuitkaがDeveloper ID署名したappを検証後、DMGを`io.github.atraz-yuya.research-rag.dmg`としてDeveloper ID Applicationで署名し、DMG自体を`notarytool submit --wait`へ送る。Accepted後はDMGへstapleし、codesign／hdiutil／Gatekeeper検証後にchecksumを生成する
- DMG signingでは`codesign --deep`を使用せず、appもDMG作成後に再署名しない。checksumはstaplingでartifactが確定した後にだけ作成する
- `prepare_github_release.sh`を追加し、dry-runはtag／Release／assetを変更せずversion、期待tag、artifact、draft状態を表示するようにした。実pathも既存local／remote tagとintended HEADを検証し、`gh release create --verify-tag --draft`でDMGとchecksumを添付するだけで、tag作成／pushとpublishは行わない
- icon、DMG staging、notary対象、署名順、checksum順、architecture名、tag検証、draft-only GitHub Release、生成artifact非追跡をfake command／`tmp_path`で確認する単体テストを追加した。通常testでfull Nuitka build、real mount、Apple credential、GitHub Releaseを使用しない
- `docs/release_checklist.md`を追加し、tests、teardown、local app／icon／DMG、Developer ID、notarization、checksum、tag、draft Release、downloaded artifact smoke、最後のmanual publishを順に確認できるようにした

### 実機確認

- macOS 26.5.2 arm64、Python 3.11.15、PySide6 6.11.1、Nuitka 4.1.3でreal icon generatorを実行し、標準10 representationsを含む423 KBの`ResearchRAG.icns`を生成した。`iconutil`によるiconsetへの読み戻しにも成功した
- local build dry-runでNuitkaへ`--macos-app-icon=.../ResearchRAG.icns`が渡されることを確認し、real standalone buildで170 MBのarm64 appを生成した。Info.plistはbundle identifier、両version、`CFBundleIconFile=ResearchRAG.icns`が正しく、Resources内ICNSも確認した
- Codex managed workspaceではNuitkaとhelperのad-hoc codesignがFileProvider属性により拒否された。生成appを`ditto --norsrc`で通常filesystemへcopyし、その限定copyで属性除去、ad-hoc署名、`codesign --verify --deep --strict`を成功させた
- ad-hoc署名済みappからcredential-freeな`Research-RAG-0.1.0-macos-arm64.dmg`を実作成し、`hdiutil verify`に成功した。read-only mountにはappと`Applications` symlinkの2項目だけがあり、symlinkが正確に`/Applications`を指すことを確認した
- mounted appを安全な一時領域へcopyし、署名を再検証してOllamaなしのoffscreen empty GUI event loopへ到達した。DBはbundle外の`~/Library/Application Support/ResearchRAG/indexes.sqlite3`、settings pathも同じbundle外directoryへ解決され、app内にDB／settings／PDFがないことを確認してclean detachした
- local build、release、GitHub Release preparationの各dry-runを成功させた。GitHub Release dry-runではtag作成、push、Release作成、asset uploadを行っていない
- Developer ID Application identityは0件で、notary profileも未設定だった。そのためreal DMG signing、real DMG notarization、stapling、Gatekeeper release検証、checksum生成は実施していない。real GitHub tag／Releaseも作成していない
- `QT_QPA_PLATFORM=offscreen python -X faulthandler -m pytest`で全441件を成功させ、worker／MainWindow teardown 48件をfaulthandler付きfresh processで5回連続成功させた

### 互換性と今回の対象外

GUI／RAG／CLI、corpus SQLite schema v3、QStandardPaths、model defaults、citation semantics、QtTaskRunner／teardown、Issue 027のNuitka Developer ID app-signing設計は変更していない。Mac App Store、auto update、custom DMG background、real tag／public GitHub Releaseは追加していない。

## Issue 029: Validate the v0.1.0 release candidate end to end

実施日: 2026-08-11

### 実施内容

- macOS 26.5.2 arm64、Python 3.11.15、PySide6／Qt 6.11.1、Nuitka 4.1.3、Ollama 0.32.6でv0.1.0 RCを検証した。defaultの`qwen3-embedding:0.6b`と`qwen3:4b-instruct`を使い、version endpoint、1024次元embedding、`think: false` generationが成功した
- private資料を使わず、PyMuPDFで一時生成した3ページ以上のtext-based PDF 2冊を実際のPDF extractionからproduction chunking／embedding／retrieval／generationへ通した。PDF A、PDF B、両資料を区別する3質問で、回答、PDF名、1始まりpage、rank、score、source textを照合した
- SQLite store／service再生成後もcorpusと文書が残り、質問embedding 1回だけで回答でき、document embeddingを再実行しないことを記録した
- PDF Aだけを変更して`MODIFIED`→対象だけreindex→`CURRENT`を確認し、同じdocument IDを維持した。PDF BのChunk／embeddingは変わらず、変更factをAの新しいpageから回答した
- PDF Bを一時的に移動して`MISSING`を確認し、保存済みcontentへの質問と他文書の利用を継続できた。sourceは元へ戻した
- Ollamaを到達不能endpointへ切り替えたfailureと設定復元後の成功、invalid PDF追加のatomic failureと直後の正常質問、空質問のpreflight rejectionとnetwork call 0件を確認した
- official `pyside6-deploy`で約171 MBのarm64 standalone appを生成し、bundle identifier、両version、ICNS、Qt runtime、strict ad-hoc signatureを確認した。約68 MBのcredential-free DMGをverify／mountし、appと`Applications -> /Applications`だけを確認して安全な一時領域へcopy／detachした
- copied packaged appはsource tree／venv／`PYTHONPATH`なしで通常起動とoffscreen起動に成功し、schema v3のAppData corpusをbundle外に維持した。到達不能Ollama URLでも起動できた
- FileProvider属性によりNuitkaの内部codesignが失敗した際、`pyside6-deploy`がexit 0とpartial bundleを残す事象をRC blockerとして再現した。local／release helperへQtCoreとCocoa platform pluginの必須検証を追加し、不完全bundleを明示的に失敗させるregression testを追加した
- `QT_QPA_PLATFORM=offscreen python -X faulthandler -m pytest`で全442件を成功させ、worker／MainWindow focused suite 48件をfaulthandler付きfresh processで5回連続成功させた。`git diff --check`、local build／release／GitHub Release preparationの各dry-runも成功した

### RC判定

初回記録後、ユーザー本人がDMGから通常directoryへコピーしたpackaged GUIを操作し、2 PDF corpus作成と両文書の`最新`表示、PDF A／B／明示的cross-PDF質問とcitation、再起動後の永続利用、PDF Aだけの`変更あり`→reindex→`最新`、PDF Bの`ファイルなし`と復旧、到達不能Ollamaのerror／UI復帰／再接続、invalid PDF、空質問を確認した。

曖昧なcross-PDF比較質問ではTop 3がPDF Bだけとなり誤答した一方、対象を明示した質問ではPDF A／Bの両方がTop 3に入った。これはdense retrievalと既定`Top-K=3`の既知制限として記録し、retrieval設定は変更していない。packaged GUIの主要completion criteriaが手動でも満たされたため、最終verdictを`PASS WITH KNOWN LIMITATIONS`へ更新した。詳細は`docs/release_candidate_v0.1.0.md`へ記録した。

GUI／RAG／CLI、SQLite schema v3、QStandardPaths、model defaults、retrieval／citation semanticsは変更していない。Developer ID identityとnotary profileがないためreal signing／notarization／stapling／Gatekeeper release assessmentは未実施で、real tag／GitHub Release／publishも行っていない。

## Issue 030: Add first-user onboarding and release documentation

実施日: 2026-08-11

### 実施内容

- `AGENTS.md`の単一PDF CLI milestoneを、macOSデスクトップv0.1.0のonboarding／release readiness段階へ更新した。GUI／RAG／SQLite schema v3が実装済みであること、QStandardPaths identityを維持すること、明示許可なしにtag／Release／publishしないこと、generated artifactをcommitしないことを記録した
- READMEを初回ユーザーの導線に合わせ、製品概要、現在のstatus、macOS DMG導入、Ollamaと既定model準備、最初の資料セットと質問、citation、文書状態、settings、troubleshooting、開発、packagingの順へ再構成した
- `docs/known_limitations.md`を追加し、OCR未対応、Ollama／model要件、初回indexing時間、会話履歴なし、dense retrieval／Top-K 3の複数資料比較制限、experimental reranking、arm64 validation範囲、未実施のDeveloper ID／notarization、auto-update／Mac App Store対象外を集約した
- project overview、MVP仕様、RC reportを現在の複数PDF GUI／永続化／release readiness段階とknown limitations文書へ接続した
- portfolio向けに、page-aware PDF pipeline、citation、SQLite、fingerprint lifecycle、PySide6、Ollama、macOS packaging、automated／RC validationの範囲を簡潔に記録した
- 新しいAccessibility／screen-recording permissionを要求せず、private PDFやprivate pathを含まないscreenshotは手動captureが可能になるまで保留した。画像を捏造せず、READMEはtextだけで完結するようにした
- Markdownのlocal linkがすべて存在することと、記載したmodel／Top-K／Ollama URL／AppData identity／schema versionを実装と照合した。offscreen／faulthandler付きfull pytest 442件と`git diff --check`が成功した

### 変更していないもの

productionのGUI／RAG／CLI、SQLite schema v3、QStandardPaths application identity／保存先、model defaults、citation semantics、Qt worker／teardown、release workflowは変更していない。real Developer ID signing／notarization、tag、GitHub Release、publishは行っていない。
