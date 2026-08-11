# Research RAG

Research RAGは、論文や学習資料のPDFへ質問し、ローカルLLMの回答と根拠を一緒に確認できるmacOSデスクトップアプリケーションです。複数のPDFを名前付きの「資料セット」として保存し、再起動後も同じindexを利用できます。

```text
PDF
  → ローカルindex／embedding
  → 質問
  → 関連箇所を検索
  → OllamaのローカルLLMが回答
  → PDF名・ページ・根拠文章を表示
```

PDFはユーザーが選んだ元の場所に残り、Research RAGが原本を削除することはありません。抽出した文章とembeddingはMac上のSQLiteへ保存されます。回答は必ず正しいとは限らないため、表示されたcitationを原文と照合してください。

## できること

- テキストを含む1つ以上のPDFを横断検索する
- 資料セットへ名前を付け、再起動後も利用する
- ローカルのOllamaでembeddingと回答生成を行う
- 回答と一緒にPDF名、1始まりのページ番号、類似度、根拠文章を表示する
- 元PDFの変更・欠落を検出し、必要な文書だけ再インデックスする
- 資料セットへのPDF追加、文書削除、名前変更、資料セット削除を行う

v0.1.0には会話履歴がなく、質問は毎回独立して処理されます。

## 現在のstatus

v0.1.0のlocal-use goalは達成済みです。macOS Apple Silicon arm64で、credential-freeなpackaged GUI／DMGと実Ollamaを`PASS WITH KNOWN LIMITATIONS`として検証しました。このlocal artifactはad-hoc署名済み、non-notarizedで、自分のMacで利用することを対象としています。

Apple Developer Programには現時点で加入せず、Developer ID signing、notarization、Git tag、GitHub Release、public distributionはdeferredとします。公開済みのv0.1.0 releaseはありません。

- [RC validation report](docs/release_candidate_v0.1.0.md)
- [v0.1.0 local-use completion notes](docs/release_notes_v0.1.0.md)
- [v0.1.0 release readiness](docs/release_readiness_v0.1.0.md)
- [Known limitations](docs/known_limitations.md)

## 必要なもの

packaged appを使う初回ユーザーにPythonやvirtual environmentは不要です。次を用意してください。

- Apple Silicon搭載Mac。v0.1.0で実機検証したartifactはarm64です
- テキストを選択・検索できるPDF。スキャン画像だけのPDFには対応しません
- [Ollama for macOS](https://ollama.com/download/mac)
- embedding model `qwen3-embedding:0.6b`
- generation model `qwen3:4b-instruct`

## macOSへインストールする

公開済みのnotarized DMGはありません。現在対象とするのは、自分のMacでcredential-free helperから作成したad-hoc signed／non-notarized local DMGです。public distribution用のGatekeeper-friendly artifactとして再配布しないでください。

1. Macのarchitectureに合う`Research-RAG-<version>-macos-<architecture>.dmg`を入手する
2. DMGを開く
3. `Research RAG.app`をDMG内の`Applications` shortcutへdragする
4. Finderでmounted DMGをejectする
5. ApplicationsからResearch RAGを起動する

インストールした`.app`にOllama、model、PDF、資料セットDBは含まれません。資料セットとGUI設定はbundle外の次の場所に保存されます。

```text
~/Library/Application Support/ResearchRAG/indexes.sqlite3
~/Library/Application Support/ResearchRAG/settings.ini
```

## Ollamaを準備する

1. Ollamaを公式download pageからインストールして起動する
2. Terminalで現在の既定modelを取得する

```bash
ollama pull qwen3-embedding:0.6b
ollama pull qwen3:4b-instruct
```

modelを確認するには次を実行します。

```bash
ollama list
```

既定の接続先とmodelは次のとおりです。

| 設定 | 既定値 | 用途 |
|---|---|---|
| Ollama URL | `http://localhost:11434` | ローカルOllama APIへの接続先 |
| Embedding model | `qwen3-embedding:0.6b` | PDFと質問を検索用vectorへ変換 |
| Generation model | `qwen3:4b-instruct` | 検索された根拠から回答を生成 |
| Top-K | `3` | 回答へ渡す検索結果の件数 |

Research RAGはmodelを自動downloadしません。別modelや別hostのOllamaを使う場合はGUIの`設定`で変更できます。

## 最初の5分

1. Research RAGを起動する
2. `新しい資料セット`を押す
3. 1つ以上のtext-based PDFを選ぶ
4. 内容が分かる資料セット名を入力する
5. indexingが終わるまで待つ。処理中は進捗indicatorが動き、完了後に文書が`最新`と表示される
6. 資料セットを選び、質問欄へ具体的な質問を入力する
7. `質問する`を押す
8. 回答を読み、その下の`参照`でPDF名、ページ、score、source textを確認する

複数PDFを比較する質問では、「PDF Aの回復率とPDF Bの削減率を比較して」のように資料名、topic、比較するfactを具体的にすると検索範囲が明確になります。それでも検索や回答の正しさを保証するものではありません。

## Citationの読み方

各sourceは次の形式で表示されます。

```text
[1] document.pdf p.12
score: 0.812345
回答の根拠候補となったPDF本文
```

- `[1]`: 検索順位。1が最上位です
- `document.pdf`: 根拠候補を抽出した元PDF名です
- `p.12`: PDF内の利用者向け1始まりページ番号です
- `score`: 質問とChunkのcosine similarityです。正しさの確率ではありません
- source text: 回答生成へ渡した根拠候補です

回答文だけで判断せず、主張を支えるPDF名・ページ・文章が表示されているか確認してください。

## 資料を管理する

Research RAGは元PDFの内容をSHA-256 fingerprintと比較し、次の状態を表示します。

| 表示 | 意味 | 対応 |
|---|---|---|
| `最新` | 現在の元PDFがindex作成時と一致する | そのまま利用できます |
| `変更あり` | 元PDFがindex作成後に変わった | 文書を選び`再インデックス`します |
| `ファイルなし` | 記録したsource pathにPDFがない | 再インデックスする場合は元のpathへ戻します |
| `未確認` | 比較用の信頼できるfingerprintがない | 必要に応じて元PDFから再インデックスします |

`ファイルなし`でも、すでに保存したindexは質問に利用できます。ただし、その文書を再インデックスするには元PDFを記録済みpathへ復元する必要があります。

Research RAG内で文書や資料セットを削除しても、元PDFは削除されません。SQLite内のindex dataだけが削除されます。

## 設定

GUIの`設定`から次を変更できます。設定は`settings.ini`へ保存され、再起動後も有効です。

### Embedding model

PDFと質問を検索用vectorへ変換するmodelです。変更は、新しく作成する資料セットだけに適用されます。既存資料セットへの質問、PDF追加、再インデックスは、その資料セットに保存済みのembedding modelを使い続けます。

### Generation model

検索されたsource textから回答を作るmodelです。変更は次の質問から反映されます。

### Top-K

質問に近いChunkを上位何件まで回答生成へ渡すかを指定します。既定値は3です。増やすと広い根拠を含められる一方、関連性の低い文章も増え、回答品質や処理時間へ影響する場合があります。

### Ollama URL

Ollama APIの接続先です。既定値は`http://localhost:11434`です。変更後の文書処理と質問から新しい接続先を使用し、設定を保存するだけではnetwork requestを行いません。

## Troubleshooting

### `Could not connect to Ollama`

- Ollama applicationが起動しているか確認する
- GUIのOllama URLを確認する。既定値は`http://localhost:11434`
- Terminalで`ollama list`が成功するか確認する
- `curl http://localhost:11434/api/version`でAPIへ到達できるか確認する
- 設定を戻した後、同じ質問をもう一度実行する

Research RAGはOllamaが停止中でも起動できますが、indexingと質問はOllamaなしでは実行できません。

### Modelが見つからない

現在の既定modelを取得し、`ollama list`で名前を確認します。

```bash
ollama pull qwen3-embedding:0.6b
ollama pull qwen3:4b-instruct
ollama list
```

GUIで別model名を設定した場合は、そのmodelも別途取得してください。

### PDFを開けない

拡張子だけでなく、実際にPDFとして開けるfileか確認してください。壊れたPDFやPDFではないfileは拒否され、資料セットへ有効な文書として保存されません。

### `ファイルなし`と表示される

Research RAGは追加時の元PDF pathを記録します。FinderでPDFを移動・rename・削除した場合は、元のpathへ戻して`状態を更新`してください。保存済みindexへの質問は可能ですが、再インデックスには元PDFが必要です。

### スキャンPDFを検索できない

OCRは実装していません。文字を選択できない画像だけのPDFからは検索用textを抽出できません。OCR済みのtext-based PDFを用意してください。

### 検索結果から片方の資料が落ちる

既定のdense retrievalとTop-K 3では、曖昧な複数資料比較質問の根拠が片方だけになる場合があります。資料名、section、topic、比較したいfactを質問へ明示してください。必要ならTop-Kを意図的に調整できますが、値を増やせば常に改善するわけではありません。

詳細は[Known limitations](docs/known_limitations.md)を参照してください。

## 開発する

### 環境構築

Python 3.11以上が必要です。macOSではrepository rootでvirtual environmentを作成します。

```bash
python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

このprojectでは、macOSのFileProvider属性がeditable install用`.pth`を隠した事例を避けるため、開発用directory名に`venv`を使用しています。

### GUIをsourceから起動する

```bash
python -m research_rag.gui_app
```

### CLIを使う

CLIは実行ごとにmemory内indexを作り、SQLiteへ自動保存しません。

```bash
python -m research_rag.cli \
  main-paper.pdf \
  "主な提案手法は何ですか？" \
  --pdf supplementary-material.pdf
```

主なoptionは`--embedding-model`、`--generation-model`、`--top-k`、`--ollama-base-url`、繰り返し指定可能な`--pdf`です。異なるdirectoryにあっても同じbasenameのPDFは同時に指定できません。

### Test

通常の自動testは実Ollamaへ接続しません。

```bash
QT_QPA_PLATFORM=offscreen python -X faulthandler -m pytest
```

## Engineering scope

Research RAGは、次の要素を小さな責務へ分けて実装しています。

- PyMuPDFによるpage-aware text extraction
- ページをまたがないChunking、Ollama embedding、cosine similarity retrieval
- local LLM answer generationとgrounded citation表示
- reusable in-memory indexとSQLite schema v3 persistence
- SHA-256によるsource change detectionと文書単位のatomic reindex
- PySide6 GUIとbackground worker／deterministic teardown
- deterministic icon、standalone `.app`、DMG、signing／notarization-ready workflow
- mock中心のautomated test、retrieval evaluation、実Ollama RC validation

仕様と設計判断は[MVP specification](docs/mvp_spec.md)、実装の経緯は[development log](docs/development_log.md)を参照してください。

## Release／packaging

### Local smoke artifact

PySide6公式`pyside6-deploy`でcredential-freeなarm64 `.app`とlocal-use DMGを作成できます。この経路がv0.1.0の現在の完成地点です。artifactはad-hoc署名済み、non-notarizedで、自分のMacでの利用を対象とし、公開配布用ではありません。

```bash
./scripts/build_macos_app.sh --dry-run
./scripts/build_macos_app.sh
./scripts/package_macos_dmg.sh "build/deploy/Research RAG.app"
```

generated `.app`、DMG、iconset、ICNS、DB、PDFはGit管理しません。

### External release preparation

repositoryにはDeveloper ID、notarytool、stapling、checksum、draft GitHub Releaseまでのhelperを保持していますが、public distributionはApple Developer Programへ加入するまでdeferredです。Developer ID signing、notarization、tag、GitHub Release、publishは現在のv0.1.0 local-use goalには含めず、実行しません。

- [Release checklist](docs/release_checklist.md)
- [RC validation report](docs/release_candidate_v0.1.0.md)

## Documentation

- [Project overview](docs/project_overview.md)
- [MVP specification](docs/mvp_spec.md)
- [Known limitations](docs/known_limitations.md)
- [v0.1.0 RC validation](docs/release_candidate_v0.1.0.md)
- [v0.1.0 local-use completion notes](docs/release_notes_v0.1.0.md)
- [v0.1.0 release readiness](docs/release_readiness_v0.1.0.md)
- [macOS release checklist](docs/release_checklist.md)
- [Development log](docs/development_log.md)

Screenshotsは、private PDF／pathを含めず安全に手動captureできる段階で追加します。このdocumentation更新では新しいmacOS Accessibility／screen-recording permissionを要求せず、画像を作成・捏造していません。
