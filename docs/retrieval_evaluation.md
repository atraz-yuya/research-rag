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
