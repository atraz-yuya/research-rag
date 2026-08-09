# Retriever検索品質評価

## 評価目的

Retriever改善前後の検索品質を、質問ごとの正解ページに基づいて比較する。評価ではLLMの回答品質ではなく、`SearchResult`に含まれるページ番号だけを対象とする。

実PDFは著作物や大容量ファイルをGit管理しないため、リポジトリへ追加しない。評価者のローカル環境に置き、ここには質問、正解ラベル、検索結果、指標、考察だけを記録する。

## 指標

- **Hit@1**: rank 1が正解ページのいずれかなら成功
- **Hit@3**: rank 1から3に正解ページのいずれかがあれば成功
- **first relevant rank**: 最初に正解ページが現れたrank。なければ `None`
- **MRR**: ケースごとに `1 / first relevant rank`、正解なしを0として平均した値

判定単位はページ番号である。同じページの複数Chunkが検索されても、それぞれのrankは保持し、最初に現れたrankを評価に使う。

## 評価ケースの作り方

1. PDFを読み、質問に答えるために妥当なページを人間が確認する。
2. 表示上の1始まりのページ番号を `relevant_pages` に記録する。
3. 複数ページが同程度に正解なら、すべて許容する。
4. 現行設定でRetrieverを実行し、rank順のページとscoreを記録する。
5. `evaluate_retrieval`でケースごとの指標を計算する。
6. 複数結果を`aggregate_retrieval_results`へ渡してHit率とMRRを計算する。

```python
from research_rag.evaluation import (
    RetrievalEvaluationCase,
    aggregate_retrieval_results,
    evaluate_retrieval,
)

case = RetrievalEvaluationCase(
    question="Which open-source datasets are used?",
    relevant_pages=(12,),
)
result = evaluate_retrieval(case, search_results)
summary = aggregate_retrieval_results([result])
```

空の評価結果は率や平均を定義できないため、集計時に `ValueError` とする。

## 記録テンプレート

### Case `<ID>`

- PDF名: `<ローカルのPDF名。ファイル自体は追加しない>`
- 質問: `<question>`
- 質問種別: `<global / local>`
- relevant_pages: `(<1始まりのページ番号>, ...)`
- 正解ページと判断した理由: `<根拠>`
- embeddingモデル: `<model>`
- chunk_size: `<値>`
- overlap: `<値>`
- top_k: `<値>`
- retrieved_pages: `(<rank順のページ番号>, ...)`
- scores: `(<rank順のscore>, ...)`
- Hit@1: `<True / False>`
- Hit@3: `<True / False>`
- first relevant rank: `<rank / None>`
- 気づいた問題: `<参考文献の混入、言語差など>`

## 最初の評価対象

評価対象PDFは `文献レビューと実験的評価.pdf` とする。PDFファイル自体はローカルに置き、Gitへ追加しない。

### 実行前のページ確認

`relevant_pages` は印刷された本文中のページ表記ではなく、PDFファイル先頭を1とするアプリケーション表示上のページ番号である。baseline実行前にPDFを開き、各質問への回答根拠が候補ページに実際に含まれることを人間が確認する。

以下の質問とページ対応は、実際のPDFを確認して確定したbaselineケースである。実行前にも一覧を見直し、別版のPDFを使う場合はページずれがないことを確認する。

### Baseline確定12ケース

| Case | 質問 | relevant_pages | 確認状態 |
| --- | --- | --- | --- |
| 1 | 資金洗浄の3つの段階は何ですか？ | `(2,)` | 確認済み |
| 2 | What are the three stages of money laundering? | `(2,)` | 確認済み |
| 3 | この文献レビューでは、論文をどの7つの基準で分類していますか？ | `(3,)` | 確認済み |
| 4 | 文献レビューの83本の非レビュー論文について、最も多く利用されている学習方法は何ですか？ | `(9,)` | 確認済み |
| 5 | 2018年以降に利用が増え始めたネットワーク分析手法は何ですか？ | `(9,)` | 確認済み |
| 6 | AUC-PRがAUC-ROCよりAMLの評価に適している理由は何ですか？ | `(23,)` | 確認済み |
| 7 | 最も多くの研究で利用されているオープンソースデータセットは何で、何本の論文で使われていますか？ | `(11, 12)` | 確認済み |
| 8 | 実験評価ではどの2つのデータセットを使用していますか？ | `(20,)` | 確認済み |
| 9 | Ellipticデータセットには何個のノードとエッジがありますか？ | `(20,)` | 確認済み |
| 10 | Ellipticの教師あり学習でAUC-PRが最も高かったモデルは何ですか？ | `(24,)` | 確認済み |
| 11 | EllipticとIBM-AMLで教師なし学習の結果が大きく異なった理由として、著者らは何を挙げていますか？ | `(25, 26)` | 確認済み |
| 12 | 著者らがsynthetic dataを使ったAML評価について注意すべきだと結論づけている理由は何ですか？ | `(26, 29)` | 確認済み |

### Baseline runnerの実行

ページ対応を確認し、Ollamaと埋め込みモデルを準備してからリポジトリルートで実行する。候補ページを修正した場合は、`BASELINE_EVALUATION_CASES`ではなく確認済みのケース一覧を`cases`へ渡す。

```bash
ollama serve
ollama pull qwen3-embedding:0.6b
```

```python
from pathlib import Path

from research_rag.evaluation_runner import (
    BASELINE_EVALUATION_CASES,
    format_retrieval_evaluation_report,
    run_retrieval_evaluation,
)

report = run_retrieval_evaluation(
    Path("/path/to/文献レビューと実験的評価.pdf"),
    BASELINE_EVALUATION_CASES,
    embedding_model="qwen3-embedding:0.6b",
)
print(format_retrieval_evaluation_report(report))
```

runnerはPDF読み込み、Chunk分割、文書Chunk embeddingを1回だけ実行する。その後、12件の質問を個別にembeddingし、既存Retrieverの上位3件を評価する。LLM回答生成は実行しない。

### Preliminary run（評価ケース修正前）

最初の12ケース実行では、Q4の質問がp.9とp.12の異なる集計文脈を区別できず、Q7も同じ正解情報があるp.11を正解としていなかった。特にQ7の`relevant_pages`修正前の結果であり、評価定義が狭すぎたため、次の値は参考値としてのみ残し、正式baselineとして使用しない。

- Hit@1: `0.4167`
- Hit@3: `0.7500`
- MRR: `0.5694`
- 扱い: `Q4/Q7修正前、かつQ7のrelevant_pages修正前のpreliminary run。正式Baseline v1には使用しない`

### Baseline v1

修正済みの12ケースを実PDFで再実行した正式baselineを次に記録する。

- Hit@1 rate: `0.4167`（`5/12`）
- Hit@3 rate: `0.8333`（`10/12`）
- MRR: `0.6111`
- Top3 miss: `Case 4`、`Case 8`
- embeddingモデル: `qwen3-embedding:0.6b`
- chunk_size: `1000`
- overlap: `150`
- 変更・補足: Q4の質問を明確化し、Q7の`relevant_pages`を`(11, 12)`へ修正した12ケースで再実行した。

## Issue 010: Retrieval failure diagnosis

### 目的

Retrieverをまだ変更せず、Baseline v1でTop3 missとなったCase 4とCase 8を観察する。正解ページに属するChunkの実順位、上位Chunkとのscore差、Chunk境界と本文を確認し、次の改善仮説を推測ではなく診断結果から決める。

初期診断対象は次の2ケースとする。

- Case 4: relevant_pages=`(9,)`、Baseline v1のTop3=`(2, 12, 12)`
- Case 8: relevant_pages=`(20,)`、Baseline v1のTop3=`(29, 12, 4)`

診断runnerはPDF読み込み、Chunk分割、文書Chunk embeddingをそれぞれ1回だけ実行し、両ケースで再利用する。各質問だけを個別にembeddingし、既存の`retrieve_similar_chunks`へ`top_k=len(embedded_chunks)`を渡して全Chunkのrankingを得る。表示用のTop 10とは別に、正解ページに属するすべてのChunkをfull rankingから抽出するため、正解がTop 10外でもfirst relevant rankを確認できる。

```python
from pathlib import Path

from research_rag.evaluation_runner import BASELINE_EVALUATION_CASES
from research_rag.retrieval_diagnostics import (
    format_retrieval_diagnostics_report,
    run_retrieval_diagnostics,
)

failure_cases = (
    BASELINE_EVALUATION_CASES[3],  # Case 4
    BASELINE_EVALUATION_CASES[7],  # Case 8
)
report = run_retrieval_diagnostics(
    Path("/path/to/文献レビューと実験的評価.pdf"),
    failure_cases,
    embedding_model="qwen3-embedding:0.6b",
    top_n=10,
)
print(format_retrieval_diagnostics_report(report))
```

### 実診断結果

#### Case 4

- relevant_pages: `(9,)`
- 日本語質問: `文献レビューの83本の非レビュー論文について、最も多く利用されている学習方法は何ですか？`
- 日本語質問のfirst relevant rank: `24`
- 日本語質問のbest relevant score: `0.361770`
- 英語質問: `Among the 83 non-review papers in the literature review, which learning method is used most frequently?`
- 英語質問のfirst relevant rank: `14`
- 英語質問のbest relevant score: `0.503058`

観察:

- 英語化によりfirst relevant rankが24位から14位へ改善したため、cross-lingual embeddingの影響はある。
- 英語でも正解ChunkはTop 10外であり、言語差だけでは検索失敗を説明できない。
- rank 2のp.12には、`unsupervised learning is by far the most applied method`という意味的に非常に近い記述がある。
- p.12はtop-cited papersについての記述であり、質問で指定した83 non-review papersとは対象範囲が異なる。
- 正解p.9には、83 non-review papersという対象範囲と`The most popular method is unsupervised learning`の両方が含まれている。
- Dense semantic retrievalが質問のscope constraintを十分に区別できていない可能性がある。

#### Case 8

- relevant_pages: `(20,)`
- 日本語質問: `実験評価ではどの2つのデータセットを使用していますか？`
- 日本語質問のfirst relevant rank: `7`
- 日本語質問のbest relevant score: `0.435093`
- 英語質問: `Which two data sets are used in the experimental evaluation?`
- 英語質問のfirst relevant rank: `6`
- 英語質問のbest relevant score: `0.546377`

観察:

- 英語化によるfirst relevant rankの改善は7位から6位のみであり、cross-lingual retrievalは主原因ではない。
- 正解p.20のchunk 0には、EllipticとIBM money launderingの記述が存在する。
- 同じChunkの前半にはFigure 5由来の大量の表・図テキストが含まれる。
- このchunk contaminationがembedding品質を低下させている可能性がある。
- `two data sets`などの類似表現を含むが答えを含まないページが上位に来る。

### 診断結果からの結論

現段階では、少なくとも次の2種類のfailureが存在する。

1. Chunk quality / PDF extraction noise
2. Dense retrievalが質問のscopeや条件を十分に区別できない問題

cross-lingual retrievalも多少影響するが、主要因ではない。単純に`top_k`を増やすだけではCase 4の正解Chunkが上位に来ない問題を解消できないため、根本的改善とはしない。

次のIssueでは一度に複数要因を変更せず、まず1つの要因だけを変更し、Baseline v1と比較する。

## Issue 011: Heading-aware Chunking Comparison Experiment

### 仮説

numbered section headingをChunkのhard boundaryとすることで、Figure／Table由来テキストと次section本文の混在を減らし、retrieval品質が改善する可能性がある。

この実験ではboundary placementだけを変更する。Figure／Table由来の文字列は削除せず、ページ境界、`chunk_size=1000`、`overlap=150`、埋め込みモデル、Retriever、`top_k=3`、評価ケースはBaseline v1と同じ条件を使う。本番`chunker.py`は置き換えず、Candidateの採否もコード側では判断しない。

Candidateは、`4 Data`、`4.2 Data`、`4.2.1 Elliptic.`、`6 Conclusion`、`6.1 Literature Review`のような行頭のnumbered headingを検出する。実PDF抽出で番号とタイトルが改行された`4.2`改行`Data`形式も、番号行の直前をhard boundaryとする。見出しは削除せず新section側へ含め、sectionが`chunk_size`を超える場合はsection内を従来どおり文字数とoverlapで分割する。

### 比較実験の実行方法

PDFは1回だけ読み込み、同じ`PageText`からBaseline chunksとCandidate chunksを作る。それぞれのChunk embeddingは1回だけ生成する。各質問のembeddingも1回だけ生成し、同じquery embeddingをBaselineとCandidateの検索へ渡す。

```python
from pathlib import Path

from research_rag.chunking_experiment import (
    format_chunking_experiment_report,
    run_chunking_experiment,
)
from research_rag.evaluation_runner import BASELINE_EVALUATION_CASES

report = run_chunking_experiment(
    Path("/path/to/文献レビューと実験的評価.pdf"),
    BASELINE_EVALUATION_CASES,
    embedding_model="qwen3-embedding:0.6b",
)
print(format_chunking_experiment_report(report))
```

### 正式な比較結果

実PDFでBaselineとHeading-aware Candidateを同じ12ケースについて比較した。

| 指標 | Baseline | Candidate | Delta（Candidate - Baseline） |
| --- | ---: | ---: | ---: |
| Hit@1 | `0.4167` | `0.4167` | `+0.0000` |
| Hit@3 | `0.8333`（`10/12`） | `0.5833`（`7/12`） | `-0.2500` |
| MRR | `0.6111` | `0.4861` | `-0.1250` |

重要なケース別first relevant rankは次のとおり。

| Case | Baseline | Candidate | 変化 |
| --- | ---: | ---: | --- |
| 3 | `1` | `2` | 悪化 |
| 5 | `2` | `None` | 新たにTop3 miss |
| 6 | `2` | `None` | 新たにTop3 miss |
| 7 | `2` | `3` | 悪化 |
| 8 | `None` | `1` | Top3 missからrank 1へ改善 |
| 10 | `2` | `None` | 新たにTop3 miss |
| 11 | `3` | `None` | 新たにTop3 miss |

### 観察と採否判断

- Case 8では仮説どおり大幅に改善し、正解p.20がTop3 missからrank 1になった。
- この結果は、heading boundaryによってFigure／Table由来ノイズとsection本文を分離する考え方自体には効果があることを示す。
- 一方、Hit@3は10/12から7/12、MRRは`0.6111`から`0.4861`へ低下した。
- Case 5、6、10、11が新たにTop3 missとなった。
- 全numbered headingを一律にhard boundaryとする戦略は、必要な文脈を分断しすぎている可能性がある。

全体指標がBaseline v1を下回ったため、Heading-aware Candidateは本番Chunkerとして採用しない。ただし、Case 8の改善は重要な証拠であり、heading boundaryという考え方そのものが無効とは結論づけない。実験コードは再現性のため保持する。

次のIssueではアルゴリズムを変更する前に、Case 8で改善し、Case 5、6、10、11で悪化した理由を診断する。

## Issue 012: Chunking Regression Diagnosis

### 目的

Chunkingアルゴリズムを変更せず、Issue 011でCase 8が改善し、Case 5、6、10、11が悪化した理由を、Baseline ChunkとHeading-aware Candidate Chunkの直接比較から観察する。Case 3とCase 7を含む任意の`RetrievalEvaluationCase`にも使用できる汎用的な診断runnerとする。

初期診断対象は次の5ケースとする。

- Case 5: Baseline rank 2、Candidate Top3 miss
- Case 6: Baseline rank 2、Candidate Top3 miss
- Case 8: Baseline Top3 miss、Candidate rank 1
- Case 10: Baseline rank 2、Candidate Top3 miss
- Case 11: Baseline rank 3、Candidate Top3 miss

### 観察する仮説

- 仮説A: heading boundaryによってFigure／Tableノイズから本文が分離され、Case 8が改善した。
- 仮説B: heading boundaryによって意味的に必要な前後文脈まで切断され、Case 5、6、10、11が悪化した。
- 仮説C: Candidateが短いChunkを大量に生成し、ランキング構造そのものが変化した。
- 仮説D: heading境界を跨ぐoverlapがないため、重要情報が複数Chunkへ分断された。

診断コードでは、どの仮説が正しいかを判定しない。full ranking、Chunk本文、Chunk長、文書統計だけを提供し、実PDFの結果から改善方針を決める。

### 診断方法

PDF読み込みは1回だけ行い、同じ`PageText`からBaselineとCandidateのChunkを生成する。Chunk embeddingは各variantで1回、質問embeddingは1ケースにつき1回だけ生成し、同じquery embeddingを両variantへ渡す。full rankingは既存`retrieve_similar_chunks`へvariantごとの`top_k=len(embedded_chunks)`を渡して取得する。

```python
from pathlib import Path

from research_rag.chunking_diagnostics import (
    format_chunking_diagnostics_report,
    run_chunking_diagnostics,
)
from research_rag.evaluation_runner import BASELINE_EVALUATION_CASES

regression_cases = (
    BASELINE_EVALUATION_CASES[4],   # Case 5
    BASELINE_EVALUATION_CASES[5],   # Case 6
    BASELINE_EVALUATION_CASES[7],   # Case 8
    BASELINE_EVALUATION_CASES[9],   # Case 10
    BASELINE_EVALUATION_CASES[10],  # Case 11
)
report = run_chunking_diagnostics(
    Path("/path/to/文献レビューと実験的評価.pdf"),
    regression_cases,
    embedding_model="qwen3-embedding:0.6b",
    top_n=5,
)
print(format_chunking_diagnostics_report(report))
```

### 実診断結果

Heading-aware Candidateでは、グラフの軸目盛りがnumbered headingとして誤認識され、意味のない極小Chunkが生成されていた。p.26で確認した具体例は次のとおり。

```text
chunk_index=1
character_count=3
text: 0.7

chunk_index=2
character_count=3
text: 0.6

chunk_index=3
character_count=3
text: 0.5
```

`experimental_chunker.py`を実ファイルで確認すると、number-only headingの分岐は`\d+(?:\.\d+)+`であり、`.`はすでにliteral periodとしてエスケープされている。false positiveの原因はregex wildcardではなく、literal periodを使った現在のパターンでも`0.7`のような小数値そのものがnumber-only headingに一致することである。そのため、`.`を`\.`へ変更するだけの修正では解決せず、number-only headingの判定条件自体を見直す必要がある。

文書全体のChunk統計:

今回提供された診断結果には文書全体の集計値が含まれていないため、次の欄は未記録のままとする。

| Variant | total count | min length | max length | mean length | median length |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | `<未記録>` | `<未記録>` | `<未記録>` | `<未記録>` | `<未記録>` |
| Candidate | `<未記録>` | `<未記録>` | `<未記録>` | `<未記録>` | `<未記録>` |

### 診断結果からの結論

- Case 8ではheading boundaryによってFigure／Table由来ノイズとsection本文を分離する効果があり、検索順位が改善した。
- Candidateではグラフ軸目盛りなどがheadingとして誤検出され、意味のない非常に短いChunkが生成されている。
- このfalse positiveによりChunk数と検索ランキングが不要に変化している可能性が高い。
- Case 11は正解がBaselineのrank 3からCandidateのrank 4程度へ下がったものであり、文脈破壊だけが原因とはまだ断定できない。
- 仮説AはCase 8の観察と整合し、仮説Cも極小Chunkの生成によって支持される。一方、仮説Bと仮説Dは今回の情報だけでは確定できない。

次の実験ではChunking戦略そのものを変更せず、heading detectionのfalse positiveだけを改善する。Issue 012では診断結果の記録に留め、実装ロジックは変更しない。

## Issue 013: Heading Detection False-positive Fix Experiment

### 仮説

Candidate v1ではグラフのnumeric axis valuesをsection headingとして誤検出しており、このfalse positiveを除去することでheading-aware chunkingの性能低下を軽減できる可能性がある。

Candidate v1と本番Chunkerは変更せず、heading boundary戦略を維持したCandidate v2を別モジュールとして比較する。変更する変数はheading detectorだけであり、ページ境界、`chunk_size=1000`、`overlap=150`、Figure／Table本文の保持、section内の文字数分割はCandidate v1と同じ条件とする。

### Candidate v2の判定

- `4 Data`、`4.2 Data`、`4.2.1 Elliptic.`などの番号とタイトルが同一行にあるheadingは直接検出する。
- number-only行は単独でheadingと判定しない。
- split headingは、直前の非空行が数値でなく、次の非空行がtitle-likeで、さらに次の非空行がbody-likeの場合だけ検出する。
- この周辺行確認により`4.2`改行`Data`改行`The methods are compared ...`を維持する。
- `0.7`、`0.6`、`2.5`、`5.0`などの連続したaxis values、文脈を伴わない`2022`や`49`はheadingにしない。
- 特定のsection名や数値はハードコードしない。

### 3-way比較の実行方法

PDFは1回だけ読み、同じ`PageText`からBaseline、Candidate v1、Candidate v2のChunkを作成する。Chunk embeddingはvariantごとに1回、質問embeddingは1ケースにつき1回だけ生成し、同じquery embeddingを3つのRetriever呼び出しへ渡す。Retriever、評価ロジック、`top_k=3`、`qwen3-embedding:0.6b`、12件の評価ケースは共通とする。

```python
from pathlib import Path

from research_rag.evaluation_runner import BASELINE_EVALUATION_CASES
from research_rag.heading_detection_experiment import (
    format_heading_detection_experiment_report,
    run_heading_detection_experiment,
)

report = run_heading_detection_experiment(
    Path("/path/to/文献レビューと実験的評価.pdf"),
    BASELINE_EVALUATION_CASES,
    embedding_model="qwen3-embedding:0.6b",
)
print(format_heading_detection_experiment_report(report))
```

### 正式な3-way比較結果

実PDFで12ケースを実行した結果を記録する。

| Variant | total chunks | Hit@1 | Hit@3 | MRR |
| --- | ---: | ---: | ---: | ---: |
| Baseline | `204` | `0.4167` | `0.8333` | `0.6111` |
| Candidate v1 | `316` | `0.4167` | `0.5833` | `0.4861` |
| Candidate v2 | `218` | `0.4167` | `0.7500` | `0.5417` |

| Delta | Hit@1 | Hit@3 | MRR |
| --- | ---: | ---: | ---: |
| Candidate v1 - Baseline | `+0.0000` | `-0.2500` | `-0.1250` |
| Candidate v2 - Baseline | `+0.0000` | `-0.0833` | `-0.0694` |
| Candidate v2 - Candidate v1 | `+0.0000` | `+0.1667` | `+0.0556` |

重要なケース別first relevant rankは次のとおり。

| Case | Baseline | Candidate v1 | Candidate v2 | 観察 |
| --- | ---: | ---: | ---: | --- |
| 3 | `1` | `2` | `3` | v2でも悪化 |
| 5 | `2` | `None` | `None` | v2でもTop3 miss |
| 6 | `2` | `None` | `None` | v2でもTop3 miss |
| 8 | `None` | `1` | `1` | heading boundaryによる改善を維持 |
| 10 | `2` | `None` | `3` | false positive修正後にTop3へ回復 |
| 11 | `3` | `None` | `3` | false positive修正後にBaseline順位へ回復 |

### 観察と採否判断

- Chunk数はCandidate v1の316からCandidate v2の218へ減少し、Baselineの204に近づいた。
- numeric axis valuesなどのheading誤検出が、不要なChunk大量生成の原因だったことが強く支持された。
- false positive修正により、Hit@3は`0.5833`から`0.7500`、MRRは`0.4861`から`0.5417`へ回復した。
- Case 8はCandidate v1とv2の両方でrank 1となり、heading boundaryによる改善はnumeric false positiveを除去しても維持された。
- Case 10とCase 11はTop3へ回復した一方、Case 3、5、6のregressionは残った。

heading detectorのfalse positive修正は有効であり、Candidate v2はCandidate v1より明確に改善した。ただしBaselineのHit@3とMRRには届かないため、本番Chunkerとしてはまだ採用しない。Candidate v1とCandidate v2は比較の再現性のため保持する。

次のIssueではBaselineとCandidate v2についてCase 3、5、6のfull rankingとrelevant page Chunk構造を比較し、正しいheading boundary自体がretrievalを悪化させる理由を診断する。

## Issue 014: Strict Heading Regression Diagnosis

### 目的

Candidate v2はnumeric headingのfalse positiveを大幅に抑制したが、BaselineよりHit@3とMRRが低い。新しいChunkerや検索改善は導入せず、BaselineとCandidate v2のfull rankingおよび正解ページのChunk境界を並べ、Case 3、5、6のregressionとCase 8の改善を観察する。

診断対象は最初にCase 3、5、6、8とするが、診断runnerは任意の`RetrievalEvaluationCase`を受け取れる。実PDFによる診断結果と結論は、実行後に別途記録する。

### 診断内容

各ケースについて、BaselineとCandidate v2の次の情報を比較する。

- full rankingから求めたfirst relevant rankとbest relevant score
- rank、PDF名、ページ番号、chunk index、score、文字数、本文、`starts_with_heading`を含むTop 5
- relevant page上に生成された全Chunkと、それぞれのfull ranking上のrankおよびscore
- BaselineとCandidate v2のChunk本文を並べた境界比較

full rankingは既存`retrieve_similar_chunks`へ`top_k=len(embedded_chunks)`を渡して取得する。コサイン類似度は再実装しない。`starts_with_heading`は診断側からCandidate v2のheading detectorを利用して、Chunk先頭がstrict numbered headingとして認識されるかを記録する。productionの`Chunk`モデルには診断用metadataを追加しない。

PDF extractionは1回だけ行う。BaselineとCandidate v2のChunk embeddingはvariantごとに1回生成する。質問embeddingは1ケースにつき1回だけ生成し、その同じベクトルを両variantの検索へ渡す。

```python
from pathlib import Path

from research_rag.evaluation_runner import BASELINE_EVALUATION_CASES
from research_rag.strict_heading_diagnostics import (
    format_strict_heading_diagnostics_report,
    run_strict_heading_diagnostics,
)

diagnostic_cases = (
    BASELINE_EVALUATION_CASES[2],  # Case 3
    BASELINE_EVALUATION_CASES[4],  # Case 5
    BASELINE_EVALUATION_CASES[5],  # Case 6
    BASELINE_EVALUATION_CASES[7],  # Case 8
)
report = run_strict_heading_diagnostics(
    Path("/path/to/文献レビューと実験的評価.pdf"),
    diagnostic_cases,
    embedding_model="qwen3-embedding:0.6b",
    top_n=5,
)
print(format_strict_heading_diagnostics_report(report))
```

### 観察する仮説

- 仮説A: Case 8ではheading boundaryによってFigure／Tableノイズが正解本文から分離され、embeddingが改善した。
- 仮説B: Case 3、5、6ではBaselineのoverlapや前後文脈が有効だったが、heading hard boundaryによって失われた。
- 仮説C: Candidate v2が意味的に正しいsectionを作っていても、Chunkが短くなったことでqueryとのsemantic similarityが下がった。
- 仮説D: 正解Chunkのscore低下ではなく、競合Chunkのscore上昇によって順位が下がった。

診断コードはこれらの仮説を結論として扱わない。Top 5、正解Chunkの全体順位とscore、relevant pageのChunk本文・長さ・境界を人間が比較し、次の変更対象を証拠から決めるための観測情報だけを提供する。

## Issue 015: Propagate section headings to continuation chunks

### 仮説とCandidate v3

Issue 014では、Candidate v2のlong section内にある継続Chunkがsection headingを失い、Case 5とCase 6の直接回答Chunkのsemantic contextが弱くなる可能性を確認した。Candidate v3ではCandidate v2のstrict heading detection、hard boundary、ページ境界、body window、`chunk_size=1000`、`overlap=150`を維持し、検出済みsectionの継続Chunkだけに同じheadingと改行を付加する。

- sectionの最初のChunkはCandidate v2と同一にする
- 継続Chunkのbody windowは移動も短縮も行わない
- body windowがすでに同じheadingから始まる場合は重複させない
- heading contextはsectionおよびページを跨いで伝播しない
- Figure／Table本文の除去など、ほかのcleanupは行わない
- 継続Chunkはheading prefixの文字数分だけ`chunk_size`を超えることを許容する

Candidate v3は実験用の別実装であり、本番ChunkerおよびCandidate v2は変更しない。

### 実PDF 3-way比較

ローカルの`文献レビューと実験的評価.pdf`、正式12ケース、`qwen3-embedding:0.6b`、`top_k=3`で比較した。PDF extractionは1回、Chunk embeddingはvariantごとに1回、question embeddingは1ケースにつき1回とし、同じquery vectorを3 variantへ渡した。

| Variant | total chunks | Hit@1 | Hit@3 | MRR |
| --- | ---: | ---: | ---: | ---: |
| Baseline | `204` | `0.4167` | `0.8333` | `0.6111` |
| Candidate v2 | `218` | `0.4167` | `0.7500` | `0.5417` |
| Candidate v3 | `218` | `0.4167` | `0.6667` | `0.5139` |

| Delta | Hit@1 | Hit@3 | MRR |
| --- | ---: | ---: | ---: |
| Candidate v2 - Baseline | `+0.0000` | `-0.0833` | `-0.0694` |
| Candidate v3 - Baseline | `+0.0000` | `-0.1667` | `-0.0972` |
| Candidate v3 - Candidate v2 | `+0.0000` | `-0.0833` | `-0.0278` |

ケース別first relevant rankは次のとおり。`Top3 miss`は正式比較の上位3件にrelevant pageが存在しないことを表す。

| Case | Baseline | Candidate v2 | Candidate v3 |
| --- | ---: | ---: | ---: |
| 1 | `1` | `1` | `1` |
| 2 | `1` | `1` | `1` |
| 3 | `1` | `3` | `3` |
| 4 | `Top3 miss` | `Top3 miss` | `Top3 miss` |
| 5 | `2` | `Top3 miss` | `Top3 miss` |
| 6 | `2` | `Top3 miss` | `Top3 miss` |
| 7 | `2` | `2` | `2` |
| 8 | `Top3 miss` | `1` | `1` |
| 9 | `1` | `1` | `1` |
| 10 | `2` | `3` | `3` |
| 11 | `3` | `3` | `Top3 miss` |
| 12 | `1` | `1` | `1` |

### 直接回答Chunkの確認

Case 3、5、6、8では、各variantの全Chunk rankingから質問へ直接回答する本文を含むChunkを確認した。

| Case | Variant | page / chunk | full rank | score | 観察 |
| --- | --- | --- | ---: | ---: | --- |
| 3 | Baseline | p.3 / chunk 0 | `1` | `0.491621` | 7分類基準を直接含む |
| 3 | Candidate v2 | p.3 / chunk 0 | `3` | `0.491621` | 本文とscoreはBaselineと同一 |
| 3 | Candidate v3 | p.3 / chunk 0 | `3` | `0.491621` | 最初のChunkなのでv2から不変 |
| 5 | Baseline | p.9 / chunk 5 | `3` | `0.501974` | post-2018 methodsを直接含む |
| 5 | Candidate v2 | p.9 / chunk 6 | `8` | `0.476530` | 継続Chunkに`3.2.1 Methods.`がない |
| 5 | Candidate v3 | p.9 / chunk 6 | `7` | `0.479945` | heading付加後もTop 3外 |
| 6 | Baseline | p.23 / chunk 3 | `2` | `0.592461` | AUC-PRが適する理由を直接含む |
| 6 | Candidate v2 | p.23 / chunk 3 | `9` | `0.528817` | 継続Chunkに`4.4 Performance Metrics`がない |
| 6 | Candidate v3 | p.23 / chunk 3 | `7` | `0.552513` | heading付加で改善したがTop 3外 |
| 8 | Baseline | p.20 / chunk 0 | `7` | `0.435093` | Figure 5由来ノイズと同居 |
| 8 | Candidate v2 | p.20 / chunk 1 | `1` | `0.539355` | `4.2 Data`を独立させた最初のChunk |
| 8 | Candidate v3 | p.20 / chunk 1 | `1` | `0.539355` | 最初のChunkなのでv2の改善を維持 |

### 結論

- heading propagationはCase 5とCase 6の直接回答Chunkのscoreとfull rankを改善したが、Top 3回復には不十分だった。
- Case 8のノイズ分離効果は維持され、Candidate v2と同じrank 1になった。
- Case 3は本文とscoreが不変でrankも3のままであり、heading contextでは競合Chunkの問題を解決できなかった。
- Candidate v3はCase 11を新たなTop3 missにし、全体のHit@3とMRRもCandidate v2より低下した。

Candidate v3はCandidate v2より全体性能が低いため、本番Chunkerとして採用しない。実験コードは仮説と結果の再現性のため保持する。次の改善ではheadingを一律に反復するのではなく、競合Chunk、queryとの言語差、またはretrieval側の条件識別を別要因として検証する必要がある。

### 予備観測

- PDF名: `文献レビューと実験的評価.pdf`（ローカルのみ）
- 質問: `この資料の主な内容を説明してください`
- 質問種別: `global`
- relevant_pages: `未設定。本文確認後に複数ページを許容してラベル付けする`
- retrieved_pages: `(3, 35, 12)`
- 実行結果: rank 1がp.3、rank 2が参考文献ページのp.35、rank 3がp.12
- 指標: `relevant_pages未設定のため未計算`
- 気づいた問題: 文書全体を尋ねるglobal questionに対し、局所Chunkの類似度だけでは主題を代表するページを安定して選べない可能性がある

## 今後評価する改善候補

このIssueでは以下を変更せず、評価ケースと結果だけを蓄積する。

- 参考文献ページが上位に来る問題
- 日本語質問と英語資料の言語差
- chunk_sizeとoverlap
- top_k
- AbstractやIntroductionの優先
- metadata filtering
- global questionとlocal retrievalの役割分担

次のIssueでは、複数のlocal questionとglobal questionを分けて測定し、指標と失敗例に基づいて改善対象を選ぶ。

## Issue 016: Query-language and scope sensitivity diagnosis

### 目的と実行条件

productionの検索挙動を変更せず、質問の言語とscope表現だけがdense retrievalの順位へ与える影響を観察した。実PDFのCase 4、5、6、8について、次の3 variantを比較した。

- `original_ja`: Baseline v1の日本語質問
- `english_equivalent`: 制約と意味を保った英訳
- `concise_scope_preserving_en`: 条件を残した短い英語表現

実行にはローカルの`文献レビューと実験的評価.pdf`と`qwen3-embedding:0.6b`を使用した。PDF extraction、Baseline Chunkerによる分割、204件の文書Chunk embeddingはそれぞれ1回だけ行い、12個のquery variantは個別に1回ずつembeddingした。各queryは既存`retrieve_similar_chunks()`へ`top_k=204`として渡し、full rankingからfirst relevant rank、best relevant score、Top 5、relevant page上の全Chunkを取得した。回答生成LLMは使用していない。

### 使用したquery variant

| Case | Variant | Query |
| ---: | --- | --- |
| 4 | `original_ja` | 文献レビューの83本の非レビュー論文について、最も多く利用されている学習方法は何ですか？ |
| 4 | `english_equivalent` | Among the 83 non-review papers in the literature review, which learning method is used most frequently? |
| 4 | `concise_scope_preserving_en` | Across all 83 non-review papers, which learning method is used most frequently? |
| 5 | `original_ja` | 2018年以降に利用が増え始めたネットワーク分析手法は何ですか？ |
| 5 | `english_equivalent` | Which network analysis methods began to be used more frequently from 2018 onward? |
| 5 | `concise_scope_preserving_en` | Which network methods increased in use from 2018 onward? |
| 6 | `original_ja` | AUC-PRがAUC-ROCよりAMLの評価に適している理由は何ですか？ |
| 6 | `english_equivalent` | Why is AUC-PR more suitable than AUC-ROC for evaluating AML? |
| 6 | `concise_scope_preserving_en` | Why prefer AUC-PR over AUC-ROC in AML evaluation? |
| 8 | `original_ja` | 実験評価ではどの2つのデータセットを使用していますか？ |
| 8 | `english_equivalent` | Which two data sets are used in the experimental evaluation? |
| 8 | `concise_scope_preserving_en` | Which two datasets are used in the experiment? |

### 実測結果

`best relevant score`はrelevant pageに属する全Chunkの最大scoreであり、質問へ直接回答するChunkのscoreとは一致しない場合がある。

| Case | Relevant pages | Variant | First relevant rank | Best relevant score | Hit@3 | Top 5 pages |
| ---: | --- | --- | ---: | ---: | --- | --- |
| 4 | `(9,)` | `original_ja` | `24` | `0.361770` | `False` | `(2, 12, 12, 4, 7)` |
| 4 | `(9,)` | `english_equivalent` | `14` | `0.503058` | `False` | `(2, 12, 6, 4, 7)` |
| 4 | `(9,)` | `concise_scope_preserving_en` | `14` | `0.500292` | `False` | `(2, 12, 6, 6, 4)` |
| 5 | `(9,)` | `original_ja` | `2` | `0.510878` | `True` | `(19, 9, 9, 2, 17)` |
| 5 | `(9,)` | `english_equivalent` | `2` | `0.617590` | `True` | `(19, 9, 2, 9, 17)` |
| 5 | `(9,)` | `concise_scope_preserving_en` | `1` | `0.506914` | `True` | `(9, 19, 9, 2, 9)` |
| 6 | `(23,)` | `original_ja` | `2` | `0.592461` | `True` | `(29, 23, 28, 23, 24)` |
| 6 | `(23,)` | `english_equivalent` | `5` | `0.611624` | `False` | `(29, 28, 27, 24, 23)` |
| 6 | `(23,)` | `concise_scope_preserving_en` | `5` | `0.630956` | `False` | `(29, 28, 27, 24, 23)` |
| 8 | `(20,)` | `original_ja` | `7` | `0.435093` | `False` | `(29, 12, 4, 11, 11)` |
| 8 | `(20,)` | `english_equivalent` | `6` | `0.546377` | `False` | `(29, 4, 12, 11, 17)` |
| 8 | `(20,)` | `concise_scope_preserving_en` | `7` | `0.477123` | `False` | `(29, 12, 31, 11, 17)` |

### Direct-answer Chunk

relevant pageが初めて現れる順位と、実際に質問へ直接回答する本文を含むChunkの順位を分けて確認した。

| Case | Direct-answer Chunk | Variant | Full rank | Score |
| ---: | --- | --- | ---: | ---: |
| 4 | p.9 / chunk 3 | `original_ja` | `24` | `0.361770` |
| 4 | p.9 / chunk 3 | `english_equivalent` | `14` | `0.503058` |
| 4 | p.9 / chunk 3 | `concise_scope_preserving_en` | `14` | `0.500292` |
| 5 | p.9 / chunk 5 | `original_ja` | `3` | `0.501974` |
| 5 | p.9 / chunk 5 | `english_equivalent` | `4` | `0.606418` |
| 5 | p.9 / chunk 5 | `concise_scope_preserving_en` | `1` | `0.506914` |
| 6 | p.23 / chunk 3 | `original_ja` | `2` | `0.592461` |
| 6 | p.23 / chunk 3 | `english_equivalent` | `5` | `0.611624` |
| 6 | p.23 / chunk 3 | `concise_scope_preserving_en` | `5` | `0.630956` |
| 8 | p.20 / chunk 0 | `original_ja` | `7` | `0.435093` |
| 8 | p.20 / chunk 0 | `english_equivalent` | `6` | `0.546377` |
| 8 | p.20 / chunk 0 | `concise_scope_preserving_en` | `7` | `0.477123` |

Case 6の理由説明はBaselineの境界上にあり、p.23 / chunk 2が不均衡データでAUC-ROCのfalse-positive rateが過小に見える理由を含み、p.23 / chunk 3がAUC-PRの適合性を明示する。chunk 2のrank／scoreは`original_ja=8 / 0.540168`、`english_equivalent=14 / 0.576299`、`concise_scope_preserving_en=15 / 0.595144`だった。

### 観察

- Case 4は英語化によりdirect-answer Chunkがrank 24から14へ、scoreが`0.361770`から約`0.50`へ改善した。しかし全variantでTop 5外であり、短文化してもrank 14から改善しなかった。p.2やp.12など、literature reviewやmethodsを含むが「83 non-review papers」というscopeへ直接回答しないChunkが引き続き上位を占めた。cross-lingual sensitivityは存在するが、scope識別の弱さも残っている。
- Case 5はpage-level first relevant rankだけを見ると日本語と忠実な英訳がともにrank 2だが、そのChunkは直接回答Chunkではない。direct-answerのp.9 / chunk 5はrank 3から英訳でrank 4へ下がった一方、簡潔な英語ではrank 1になった。短い表現が有効な例だが、英語化だけで一貫して改善するわけではない。
- Case 6は英語化でdirect-answer scoreが上昇したにもかかわらず、rankは2から5へ悪化した。p.27〜29やp.24のAUC指標表・結論Chunkのscoreも上がり、Top 5の競合構成が変化したためである。正解Chunk自体のscoreだけでは順位変化を説明できない。
- Case 8は忠実な英訳でrank 7から6、scoreは`0.435093`から`0.546377`へ改善したがTop 5には入らなかった。簡潔な英語ではrank 7へ戻った。p.29の「only two data sets」やデータ一覧ページが上位に残り、言語差よりFigure 5由来ノイズを含むdirect-answer Chunkの品質と競合表現の影響が大きいというIssue 010の診断と整合する。
- 4ケースを通じて、英語化はrelevant scoreを概ね上げたが、順位やHit@3を必ず改善しなかった。Case 4ではcross-lingualとscope、Case 5ではqueryの簡潔さ、Case 6では競合Chunk、Case 8ではChunk contaminationがそれぞれ異なる形で作用している。

このIssueではtranslation、query rewriting、reranking、hybrid retrievalをproductionへ導入しない。診断結果は、単一のquery-language施策を直ちに採用する根拠ではなく、次の実験で変更する要因を絞るための観測値として扱う。

## Issue 017: LLM reranking over dense retrieval candidates

### 実験条件

productionの検索挙動を変更せず、Baseline dense retrievalのTop 30を既存のローカル生成LLMで再順位付けした。正式12ケースは`BASELINE_EVALUATION_CASES`に保存された元の質問文をそのまま使用し、翻訳やquery rewriteは行っていない。正式定義上、Case 2だけは元から英語であり、それ以外は元の日本語質問である。

- PDF: `文献レビューと実験的評価.pdf`（ローカルのみ）
- Baseline chunks: `204`
- Embedding model: `qwen3-embedding:0.6b`
- Generation model: `qwen3:4b-instruct`、4.0B、`Q4_K_M`
- Dense candidate pool: `30`
- Final evaluation cutoff: Top 3
- Generation options: `think=false`、`num_ctx=32768`、`num_predict=512`、`temperature=0`
- モデルが公開するcontext上限: `262144`
- `ollama ps`で確認した実行時context: `32768`

PDF extraction、Baseline Chunk分割、文書Chunk embeddingは各1回だけ実行した。各質問は1回だけembeddingし、同じquery embeddingをBaseline Top 3、Dense Top 30、dense full rankingで再利用した。各ケースのTop 30全文Chunkは1回の生成リクエストで相互比較し、通常のRAG回答生成は呼び出していない。

LLMには`C001`から始まるdense順位ベースのstable ID、PDF名、ページ番号、chunk index、全文を渡した。出力は`{"ranking": [...]}`というstrict JSONだけを許可する。未知IDとmalformed outputは明示的な実験エラーとし、重複IDは最初の出現だけを採用し、返されなかった候補は元のdense順で末尾へ補完する。

### 正式12ケースの比較結果

| Variant | Hit@1 | Hit@3 | MRR |
| --- | ---: | ---: | ---: |
| Baseline Top 3 | `0.4167` (`5/12`) | `0.8333` (`10/12`) | `0.6111` |
| Dense Top 30 + LLM reranking Top 3 | `0.8333` (`10/12`) | `1.0000` (`12/12`) | `0.9028` |

Candidate-pool relevant-page Recall@30は`1.0000`（`12/12`）だった。すべてのケースで少なくとも1つのrelevant-page ChunkがTop 30へ入り、rerankerが評価可能な候補集合になっていた。

| Case | Dense full first relevant rank | Baseline Top 3 first rank | Reranked first rank | 判定 |
| ---: | ---: | ---: | ---: | --- |
| 1 | `1` | `1` | `1` | unchanged |
| 2 | `1` | `1` | `1` | unchanged |
| 3 | `1` | `1` | `1` | unchanged |
| 4 | `24` | `None` | `1` | improved |
| 5 | `2` | `2` | `1` | improved |
| 6 | `2` | `2` | `2` | unchanged at page level |
| 7 | `2` | `2` | `1` | improved |
| 8 | `7` | `None` | `1` | improved |
| 9 | `1` | `1` | `1` | unchanged |
| 10 | `2` | `2` | `3` | regressed, but remains Top 3 |
| 11 | `3` | `3` | `1` | improved |
| 12 | `1` | `1` | `1` | unchanged |

改善はCase 4、5、7、8、11の5件、悪化はCase 10の1件だった。Case 10はrank 2から3への低下でHit@3を維持し、既存Baseline成功ケースのTop3 missは発生しなかった。

### Case 4／5／6／8のdirect-answer Chunk

| Case | Chunk | Dense full rank / Top-30 position | Reranked position | Reranked Top 3 |
| ---: | --- | ---: | ---: | --- |
| 4 | p.9 / chunk 3 | `24 / 24` | `1` | Yes |
| 5 | p.9 / chunk 5 | `3 / 3` | `1` | Yes |
| 6 | p.23 / chunk 3 | `2 / 2` | `4` | No |
| 6 | p.23 / chunk 2 | `8 / 8` | `2` | Yes |
| 8 | p.20 / chunk 0 | `7 / 7` | `1` | Yes |

- Case 4では、83 non-review papersのscopeと回答を含むp.9 / chunk 3がrank 24から1へ移動した。p.2 / chunk 4とp.12 / chunk 4はrank 1／2から2／3へ下がり、scopeの異なる関連文より直接回答が優先された。
- Case 5では、post-2018 network methodsを直接含むp.9 / chunk 5がrank 3から1へ移動した。p.19 / chunk 4は1から2、同じrelevant pageだが直接回答ではないp.9 / chunk 2は2から3へ下がった。
- Case 6では、従来direct-answerとして追跡していたp.23 / chunk 3がrank 2から4へ下がった一方、AUC-ROCが不均衡データでfalse positivesに鈍感になる具体的理由を含むp.23 / chunk 2がrank 8から2へ上がった。p.29 / chunk 0はrank 1から3、AUC表のp.28 / chunk 0はTop 3外へ下がった。page-level順位は2のままだが、理由を含むChunkを関連表や結論文より優先できた点は重要である。
- Case 8では、Figure 5由来ノイズを含むものの2つのデータセット名を直接含むp.20 / chunk 0がrank 7から1へ移動した。p.20 / chunk 3もrank 2へ入り、p.29 / chunk 5はrank 1から3、p.12 / chunk 0とp.4 / chunk 1はTop 3外へ下がった。

### Prompt sizeとruntime制約

Top 30全文を含むpromptは、ケースごとに`28,162`〜`32,431`文字だった。文字数はtoken数ではないが、Ollamaは指定どおり`32768` contextをGPU上で確保し、12リクエストすべてを切り詰めやHTTPエラーなしで完了した。

- LLM reranking合計: `556.278`秒
- 1ケース平均: 約`46.4`秒
- 1ケース最小／最大: `34.843`秒／`63.225`秒
- PDF処理とembeddingを含むexperiment全体: `592.720`秒（約9分53秒）
- `ollama ps`で表示されたgeneration modelのGPU memory: `7.4 GB`
- 同時にロードされたembedding modelのGPU memory: `2.4 GB`

1質問あたり約35〜63秒のrerankingは、通常の回答生成より前に追加される遅延としては大きい。また、32K contextの4Bモデルとembeddingモデルを同時にロードした実測GPU memoryも約9.8 GBだった。この環境では実験を完走できたが、より小さいメモリの端末や対話的な待ち時間では明確な制約になる。

### 採否判断

品質面では、Hit@3=`12/12`、Case 4のdirect-answer rank 1、Baseline成功ケースのTop3 missなし、Case 6の理由Chunk rank 2を達成し、採用条件1〜4を満たした。一方、1質問平均約46秒の追加処理はローカルデスクトップRAGの既定動作としては重く、実用性に関する条件5を十分満たすとは判断しない。

そのためIssue 017ではproductionへ採用せず、Baseline retrieverを維持する。LLM rerankingは品質改善の有力な実験結果として保持するが、統合する場合は別Issueでopt-in化、latency表示、context／memory要件、失敗時動作を明示して検討する。追加のretrieval tuningはここで一度区切る。
