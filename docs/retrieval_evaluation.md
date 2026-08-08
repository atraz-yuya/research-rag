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
