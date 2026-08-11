# v0.1.0 Known Limitations

この文書はResearch RAG v0.1.0で確認済みの制限をまとめる。回答や検索結果が必ず正しいことを保証するものではない。実測を伴うrelease candidateの結果は[`release_candidate_v0.1.0.md`](release_candidate_v0.1.0.md)を参照する。

## PDF processing

- 対象はテキストを抽出できるPDFである。スキャン画像だけのPDFをOCRする機能はない
- 壊れたfileやPDFとして開けないfileは追加できない
- 同一資料セット内ではcitationをファイル名で識別するため、同じbasenameを持つ複数PDFは追加できない
- folder／globによる一括収集、source fileの常時監視、自動再インデックスは行わない。状態更新と再インデックスはユーザー操作で行う

## Local models and runtime

- indexingと回答生成には、Ollamaがローカルで起動している必要がある
- 設定したembedding／generation modelは事前にOllamaへ用意する必要があり、Research RAGは自動downloadしない
- 初回indexingの時間は、PDFの量、model、Macの性能に左右される
- cloud LLMには接続せず、Ollama以外のruntimeを選ぶUIはない

## Retrieval and answers

- 既定のdense retrievalと`Top-K=3`は、関連する根拠を必ずTop 3へ含めるものではない
- 特に「2資料の数値を比較して」のように資料や対象範囲が曖昧な複数PDF比較質問では、片方のPDFが検索結果から落ち、回答が不足または誤る場合がある
- 資料名、topic、比較するfactを質問に明示すると改善する場合があるが、正しい検索や回答を保証しない
- Top-Kを増やすと候補は広がる一方、関連性の低い文脈が増え、回答品質と待ち時間へ影響する場合がある
- experimentalなLLM rerankingはlatencyが大きいためproduction GUI／CLIでは有効化していない
- 会話履歴はない。各質問は独立して処理される

回答と一緒に表示されるPDF名、1始まりページ、source textを必ず確認する。

## Desktop distribution

- 実機検証済みのpackaged app／DMGはmacOS Apple Silicon arm64である。Intelまたはuniversal2 buildは検証していない
- v0.1.0の完成地点は、自分のMacで使うad-hoc signed／non-notarizedなlocal app／DMGである。public distribution用のGatekeeper-friendly artifactではない
- Apple Developer Programには現時点で加入せず、real Developer ID signing、notarization、stapling、Gatekeeper release assessmentは行わない
- Git tag、GitHub Release、publishを行わず、public distributionはApple Developer Programへ加入するまでdeferredである
- Mac App Store、auto-update、cross-platform installerはv0.1.0の対象外である

## Persistence boundaries

- GUIの資料セットはローカルSQLiteへ保存するが、元PDF自体はAppDataへコピーしない
- 元PDFを移動または削除すると`ファイルなし`になる。保存済みindexは質問に使えるが、再インデックスには元のsource pathを復元する必要がある
- CLIのindexは実行ごとのmemory内だけで、GUIの保存済み資料セットへ自動保存されない
