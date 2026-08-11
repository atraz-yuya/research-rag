# v0.1.0 Release Candidate Validation

実施日: 2026-08-11

対象: Issue 029 / project version `0.1.0`

## 判定

**RC verdict: FAIL（packaged GUIの対話的E2E validation未完了）**

完全なstandalone `.app`、credential-free DMG、実Ollamaを使うproduction RAGライフサイクルは確認できた。一方、このCodex実行環境ではmacOS Accessibility権限がなく、DMGからコピーしたpackaged GUIのボタン操作を自動化できなかった。そのため、packaged app上でのcorpus作成から質問までを実際にクリック操作したとは扱わず、Issue 029のcompletion criteriaを満たしたPASSとは判定しない。

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

ただしAccessibility権限不足のためpackaged GUIのwidget操作は実行できなかった。以下のRAG、永続化、変更検出、失敗回復は、packaged appと同じproduction service／SQLite schema／AppData lifecycleを実Ollamaへ接続して確認したものであり、packaged GUIのクリック操作結果ではない。

## Test PDFs

PyMuPDFで一時領域へ生成した、OCRを必要としない複数ページのtext-based PDF 2冊を使用した。pre-extracted textは使わず、実際のPyMuPDF extractionからproduction chunking、embedding、retrieval、generationまでを通した。

- PDF A: `asteria_coastal_observatory.pdf`、沿岸eelgrass restorationの観測方法と結果。変更試験前は3ページ、変更後は4ページ
- PDF B: `boralis_library_energy.pdf`、公共図書館のenergy retrofit設備と測定結果、3ページ

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

## Restart and persistence

storeとserviceを作り直して同じindexをloadした。

- corpus表示名と2文書のmetadataが維持された
- source PDFの再追加は不要だった
- `How many fixed monitoring stations were used?`へ`Twelve`と回答し、Asteria page 2をrank 1（score 0.678676）で引用した
- 記録されたembedding callは質問1件だけで、document extraction／chunking／document embeddingは再実行されなかった

## Modified document and reindex

PDF Aだけへ4ページ目のfactを追加した。

- refresh前後: PDF A=`MODIFIED`、PDF B=`CURRENT`
- PDF Aをreindex後: 両方=`CURRENT`
- PDF Aの`document_id`は維持された
- PDF BのChunk／embeddingはbyte-for-byte相当で維持された
- document embedding callはPDF Aの4 chunksだけで、PDF B本文は含まれなかった
- `How many juvenile seahorses were counted in the 2025 follow-up?`へ`94`と回答し、Asteria page 4をrank 1（score 0.799951）で引用した

## Missing source

一時PDF Bだけを別名へ移動してrefreshした。

- PDF A=`CURRENT`、PDF B=`MISSING`
- corpusと他文書は利用可能なままだった
- 保存済みPDF B内容への質問は引き続き`41 percent`と回答し、Boralis page 3をrank 1（score 0.817925）で引用した
- source fileを元のpathへ戻した

## Ollama unavailable and recovery

live serviceの接続先を一時的に`http://127.0.0.1:1`へ変更した質問は、`OllamaError`とconnection refusedで失敗した。以前のcorpusを変更せず、元のclient／settingsへ戻した次の質問は成功し、Asteria page 1を引用した。

packaged app自体も同じ到達不能URLを保存した状態でOllamaへ接続せず起動できた。GUIのprogress解除、controls復帰、以前のanswer表示保持は既存mock GUI regression testでは確認済みだが、今回のpackaged GUIではAccessibility制約により対話確認していない。

## Invalid PDF and empty question

- PDFでない一時fileの追加は`Failed to open PDF file`で失敗した
- corpus metadataは前後で一致し、部分documentは保存されなかった
- 直後の有効な質問は成功し、Boralis page 3を正しく引用した
- whitespace-only questionは`question must not be empty`で拒否され、embedding／generation callは0件だった
- packaged GUI上のdialogと入力保持は今回の対話確認対象外である

## Release blocker fixed

FileProvider属性によりNuitkaの内部codesignが失敗した場合、`pyside6-deploy`がexit code 0を返し、Qt runtimeを欠く約14 MBのpartial `.app`を既存helperが成功扱いすることを再現した。このbundleは起動時に`ModuleNotFoundError`となった。

local／release helperに、`QtCore`と`libqcocoa.dylib`の存在を必須とするpost-build validationを追加した。不完全bundleは署名やartifact化へ進まず、明確なerrorで失敗する。isolated fake deployを使うregression testを追加し、通常pytestはNuitka full buildへ依存しない。安全な一時filesystem上でofficial `pyside6-deploy`を実行して、完全なstandalone appを改めて生成・検証した。

## Known limitations

- scanned-image PDFのOCRはv0.1.0の対象外
- embedding／generationにはOllamaと指定modelがローカルに必要
- 初回indexingはPDF量とlocal model速度に応じて時間がかかる
- dense retrievalはscopeや複数factの質問で必要なevidenceをTop-Kへ入れない場合がある
- experimental rerankingはlatencyのためproductionへ有効化していない
- Developer ID Application identityとnotary profileがなかったため、real Developer ID signing、DMG notarization、stapling、Gatekeeper release assessmentは未実施
- Accessibility権限がなかったため、packaged GUIの対話的E2Eは未実施。最終RC acceptanceには別の対話可能なmacOS sessionで同じ手順を完了する必要がある

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
