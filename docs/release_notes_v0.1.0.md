# Research RAG v0.1.0 Local-use Completion Notes

> v0.1.0は、自分のMacで使うcredential-freeなlocal applicationとして完成しました。artifactはad-hoc署名済み、non-notarizedで、公開配布用ではありません。

Research RAGは、研究資料のPDFへ質問し、ローカルLLMの回答と根拠を一緒に確認するmacOSデスクトップアプリケーションです。複数のPDFを名前付き資料セットとして保存し、PDFを横断して関連箇所を検索できます。

## 主な機能

- 1つ以上のtext-based PDFから名前付き資料セットを作成
- ローカルOllamaによるembedding、検索、回答生成
- 回答とともに検索rank、PDF名、1始まりのページ番号、類似度、source textを表示
- SQLiteに資料セット、抽出text、embeddingを保存し、再起動後も再利用
- 元PDFの変更／欠落を検出し、変更した文書だけを再インデックス
- PDF追加、文書削除、資料セットの名前変更／削除
- Embedding model、Generation model、Top-K、Ollama URLのGUI設定

## 動作要件

v0.1.0で実機検証したpackaged artifactはmacOS Apple Silicon `arm64`です。Intel Macおよびuniversal2 artifactは検証していません。

Ollamaを別途インストールして起動し、既定modelを準備してください。

```bash
ollama pull qwen3-embedding:0.6b
ollama pull qwen3:4b-instruct
```

Research RAGはOllama本体、model、PDFをappへ同梱しません。

## インストールと最初の質問

local helperで作成したarchitectureに合うDMGを開き、`Research RAG.app`を`Applications` shortcutへdragします。Ollamaを起動してからappを開き、`新しい資料セット`でPDFを選び、質問を入力します。この手順は、自分のMacで作成・利用するad-hoc signed／non-notarized artifactを対象とします。

各回答の下に表示されるcitationで、PDF名、ページ番号、score、source textを確認してください。scoreは正しさの確率ではありません。回答は必ず正しいとは限らないため、重要な判断では必ずcitationを元PDFと照合してください。

## 既知の制限

- OCRには対応せず、スキャン画像だけのPDFからはtextを抽出できない
- 会話履歴はなく、質問は毎回独立する
- dense retrievalと既定`Top-K=3`では、曖昧な複数PDF比較質問の片方が検索結果から落ちる場合がある
- indexingと質問には、設定したOllama modelがローカルで利用可能である必要がある
- v0.1.0で検証済みの配布architectureはApple Silicon arm64のみ
- Mac App Store、auto-update、cross-platform installerには対応しない

詳細と回避策は[Known Limitations](known_limitations.md)、使い方は[README](../README.md)を参照してください。

## Distribution status

v0.1.0のlocal-use goalは達成済みです。Phase Aで検証したcredential-free `.app`／DMGを現在の完成地点とし、real Developer ID signing、notarization、stapling、release用Gatekeeper assessment、Git tag、GitHub Release、asset upload、publishは行いません。public distributionはApple Developer Programへ加入するまでdeferredです。
