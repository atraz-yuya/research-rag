# v0.1.0 Release Candidate Validation

実施日: 2026-08-11

対象: Issue 029 / project version `0.1.0`

## 判定

**RC verdict: PASS WITH KNOWN LIMITATIONS**

完全なstandalone `.app`、credential-free DMG、実Ollamaを使うproduction RAGライフサイクルに加え、ユーザー本人がDMGからコピーしたpackaged GUIを対話操作し、corpus作成、2 PDFのindexingと質問、再起動、文書変更とreindex、missing source、Ollama failure recovery、invalid PDF、空質問まで確認した。曖昧な複数PDF比較質問では、dense retrievalと既定`Top-K=3`により片方のPDFが検索結果から落ちる場合があるため、既知の制限を伴うPASSとする。

## Environment

- macOS 26.5.2 / Apple Silicon arm64
- Python 3.11.15
- PySide6 6.11.1 / Qt 6.11.1
- Nuitka 4.1.3
- project version `0.1.0`
- bundle identifier `io.github.atraz-yuya.research-rag`
- AppData: `~/Library/Application Support/ResearchRAG`
- corpus DB: AppData内の`indexes.sqlite3`、schema version 3
- GUI settings: AppData内の`settings.ini`。app bundleとは分離される

private PDF、生成したtest PDF、SQLite DB、`.app`、DMGはGitへ追加していない。

## Ollama and models

- Ollama 0.32.6 / `http://localhost:11434`
- embedding: `qwen3-embedding:0.6b`
- generation: `qwen3:4b-instruct`
- `GET /api/version`、1024次元の最小embedding request、`think: false`の最小generation requestを実行し、すべて成功した
- application defaultは変更しておらず、model pullも行っていない

## Packaged app and DMG

検証用一時領域で次を生成した。

- standalone app: `Research RAG.app`、約171 MB、arm64
- local DMG: `Research-RAG-0.1.0-macos-arm64.dmg`、約68 MB

`Info.plist`は次の値を保持した。

- `CFBundleIdentifier=io.github.atraz-yuya.research-rag`
- `CFBundleShortVersionString=0.1.0`
- `CFBundleVersion=0.1.0`
- `CFBundleIconFile=ResearchRAG.icns`

appにはQtCore、Cocoa platform plugin、423 KBのICNSが含まれ、`codesign --verify --deep --strict`に成功した。DMGは`hdiutil verify`に成功し、read-only mount上に`Research RAG.app`と`Applications -> /Applications`だけがあることを確認してclean detachした。mounted appを通常の一時directoryへコピーし、署名を再検証した。

コピーしたpackaged appは、source tree、venv、`PYTHONPATH`なしで通常起動と`QT_QPA_PLATFORM=offscreen`起動の両方に成功し、GUI event loopで稼働し続けた。既存AppDataには1 corpus／2 documentsがschema v3で残り、app bundle内に`indexes.sqlite3`、`settings.ini`、PDFは存在しない。到達不能なOllama URLを一時設定した状態でも起動し、設定を検証後に元の「settingsなし」の状態へ戻した。

Codexによる初回検証ではAccessibility権限不足のためwidget操作を自動化できなかった。その後、ユーザー本人が同じrelease-like packaged GUIを通常のmacOS sessionで対話操作し、以下の主要シナリオを完了した。production serviceのinstrumentation結果と手動GUI結果を併せて記録する。

## Test PDFs

PyMuPDFで一時領域へ生成した、OCRを必要としない複数ページのtext-based PDF 2冊を使用した。pre-extracted textは使わず、実際のPyMuPDF extractionからproduction chunking、embedding、retrieval、generationまでを通した。

- PDF A: `asteria_coastal_observatory.pdf`、沿岸eelgrass restorationの観測方法と結果。変更試験前は3ページ、変更後は4ページ
- PDF B: `boralis_library_energy.pdf`、公共図書館のenergy retrofit設備と測定結果、3ページ

packaged GUIの手動確認では、同じ識別可能なfactを含む`RC-Test-A.pdf`と`RC-Test-B.pdf`を同一資料セットへ追加した。両文書が`最新`になるまで処理が完了し、以下のcitationを実際のpage textと照合した。

## Questions and citations

### PDF A

- question: `What was the primary driver of eelgrass recovery?`
- expected fact / answer: underwater light availability
- top citation: `asteria_coastal_observatory.pdf`, page 1, rank 1, score 0.735606
- source text: `underwater light availability was the primary driver of eelgrass recovery`
- result: answer、PDF名、1始まりpage、rank、score、source textが一致した

### PDF B

- question: `By what percentage did annual grid electricity use fall?`
- expected fact / answer: 41 percent
- top citation: `boralis_library_energy.pdf`, page 3, rank 1, score 0.809614
- source text: `annual grid electricity use fell by 41 percent`
- result: answer、PDF名、1始まりpage、rank、score、source textが一致した

### Multiple documents

- question: `Which report focuses on environmental restoration, and which report focuses on building energy performance?`
- answer: Asteria reportをenvironmental restoration、Boralis reportをbuilding energy performanceとして正しく区別した
- citations: rank 1はBoralis page 1（score 0.352900）、rank 2はBoralis page 2（0.338305）、rank 3はAsteria page 1（0.293127）
- result: 両PDF名、1始まりpage、source textが回答を支持した

探索中の別質問`Compare the percentage outcomes reported by the two documents.`では、既定Top-K 3にAsteria page 3が入らず一方の数値を回答できなかった。これは状態破損ではなく、現在のdense retrieval／Top-Kの既知の品質限界として扱い、retrieval設定は変更していない。

### Packaged GUI manual confirmation

- PDF A質問: `underwater light availability`を回答し、top citationは`RC-Test-A.pdf` page 1だった
- PDF B質問: `41 percent`を回答し、top citationは`RC-Test-B.pdf` page 3だった
- 曖昧なcross-PDF比較質問: Top 3がPDF Bだけとなり誤答した。片方のPDFがcandidateから落ちる既知制限として記録する
- 資料名と期待範囲を明示したcross-PDF質問: PDF A／Bの両方がTop 3へ入り、両資料を正しく区別した
- source表示のPDF名、1始まりpage、rank、score、本文を確認し、成功した各質問の主要citationが実際の根拠textと一致した

## Restart and persistence

storeとserviceを作り直して同じindexをloadした。

- corpus表示名と2文書のmetadataが維持された
- source PDFの再追加は不要だった
- `How many fixed monitoring stations were used?`へ`Twelve`と回答し、Asteria page 2をrank 1（score 0.678676）で引用した
- 記録されたembedding callは質問1件だけで、document extraction／chunking／document embeddingは再実行されなかった
- packaged GUIでも通常終了後に再起動し、corpus／documentsが残り、再追加なしで`12`と回答して`RC-Test-A.pdf` page 2をtop citationにした

## Modified document and reindex

PDF Aだけへ4ページ目のfactを追加した。

- refresh前後: PDF A=`MODIFIED`、PDF B=`CURRENT`
- PDF Aをreindex後: 両方=`CURRENT`
- PDF Aの`document_id`は維持された
- PDF BのChunk／embeddingはbyte-for-byte相当で維持された
- document embedding callはPDF Aの4 chunksだけで、PDF B本文は含まれなかった
- `How many juvenile seahorses were counted in the 2025 follow-up?`へ`94`と回答し、Asteria page 4をrank 1（score 0.799951）で引用した
- packaged GUIでもPDF A=`変更あり`／PDF B=`最新`からPDF Aだけをreindexし、両方=`最新`へ戻った。変更後factは`94`と回答し、`RC-Test-A.pdf` page 4をtop citationにした

## Missing source

一時PDF Bだけを別名へ移動してrefreshした。

- PDF A=`CURRENT`、PDF B=`MISSING`
- corpusと他文書は利用可能なままだった
- 保存済みPDF B内容への質問は引き続き`41 percent`と回答し、Boralis page 3をrank 1（score 0.817925）で引用した
- source fileを元のpathへ戻した
- packaged GUIでもPDF B=`ファイルなし`／PDF A=`最新`を表示し、MISSINGのまま保存済みindexから`41 percent`と回答して`RC-Test-B.pdf` page 3を引用した。PDF Bを元pathへ戻すと`最新`へ復旧した

## Ollama unavailable and recovery

live serviceの接続先を一時的に`http://127.0.0.1:1`へ変更した質問は、`OllamaError`とconnection refusedで失敗した。以前のcorpusを変更せず、元のclient／settingsへ戻した次の質問は成功し、Asteria page 1を引用した。

packaged app自体も同じ到達不能URLを保存した状態でOllamaへ接続せず起動できた。手動GUI確認では`http://127.0.0.1:1`への質問で明示的なconnection refused dialogを表示し、app継続、progress終了、controls復帰、corpus／document／question状態維持を確認した。`http://localhost:11434`へ戻した次の質問は成功し、`underwater light availability`へ`RC-Test-A.pdf` page 1を引用した。

## Invalid PDF and empty question

- PDFでない一時fileの追加は`Failed to open PDF file`で失敗した
- corpus metadataは前後で一致し、部分documentは保存されなかった
- 直後の有効な質問は成功し、Boralis page 3を正しく引用した
- whitespace-only questionは`question must not be empty`で拒否され、embedding／generation callは0件だった
- packaged GUIでもinvalid PDFに`Failed to open PDF file: .../invalid.pdf`を表示し、crashせず既存stateを維持した
- packaged GUIのwhitespace-only questionは`質問を入力してください。`と警告し、不要なRAG処理を開始しない既存実装と一致した

## Release blocker fixed

FileProvider属性によりNuitkaの内部codesignが失敗した場合、`pyside6-deploy`がexit code 0を返し、Qt runtimeを欠く約14 MBのpartial `.app`を既存helperが成功扱いすることを再現した。このbundleは起動時に`ModuleNotFoundError`となった。

local／release helperに、`QtCore`と`libqcocoa.dylib`の存在を必須とするpost-build validationを追加した。不完全bundleは署名やartifact化へ進まず、明確なerrorで失敗する。isolated fake deployを使うregression testを追加し、通常pytestはNuitka full buildへ依存しない。安全な一時filesystem上でofficial `pyside6-deploy`を実行して、完全なstandalone appを改めて生成・検証した。

## Known limitations

v0.1.0の制限一覧は[`known_limitations.md`](known_limitations.md)を正とする。このRCで特に観察した事項は次のとおり。

- scanned-image PDFのOCRはv0.1.0の対象外
- embedding／generationにはOllamaと指定modelがローカルに必要
- 初回indexingはPDF量とlocal model速度に応じて時間がかかる
- 曖昧な複数PDF比較質問では、dense retrievalと既定`Top-K=3`により片方のPDFがretrieval結果から落ち、誤答する場合がある。資料名や対象範囲を明示した比較質問では両PDFがTop 3へ入り成功した
- experimental rerankingはlatencyのためproductionへ有効化していない
- Developer ID Application identityとnotary profileがなかったため、real Developer ID signing、DMG notarization、stapling、Gatekeeper release assessmentは未実施

real tag、GitHub Release、publishは行っていない。

## Automated and release-workflow verification

- `QT_QPA_PLATFORM=offscreen python -X faulthandler -m pytest`: 442 passed、5 warnings
- worker／MainWindow focused suite: 48 passedをfaulthandler付きfresh processで5回連続実行
- `git diff --check`: success
- local app build dry-run: success
- release helper dry-run: success。署名、Keychain変更、Apple network requestなし
- GitHub Release helper dry-run: success。tag作成／push、Release作成、asset uploadなし
- real local standalone build、icon／bundle metadata、strict ad-hoc signature、credential-free DMG作成／verify／mount／detach、safe-copy launch: success

Developer ID Application identityは0件だったため、real Developer ID／notarizationの項目はNOT EXECUTEDであり、PASSではない。
