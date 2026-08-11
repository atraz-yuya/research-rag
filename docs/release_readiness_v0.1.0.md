# v0.1.0 Release Readiness — Phase A

確認日: 2026-08-11

この文書はIssue 031 Phase Aのrelease-state安全確認と、credential-freeな最終preflightの証拠を記録する。製品機能の詳細なE2E結果は[RC validation report](release_candidate_v0.1.0.md)を参照する。

## Source and release state

| 項目 | 確認結果 |
|---|---|
| Phase A開始時の`main` | `346e6b0f578435a93dca521afb7534e90575d91b` |
| source candidate | `346e6b0f578435a93dca521afb7534e90575d91b`（Issue 030のmerge commit） |
| project version | `0.1.0` (`pyproject.toml`) |
| expected tag | `v0.1.0` |
| bundle identifier | `io.github.atraz-yuya.research-rag` |
| validated architecture | Apple Silicon `arm64` |
| RC verdict | `PASS WITH KNOWN LIMITATIONS` |

Phase Aではtracked release notes／readiness recordを追加するため、上記SHAはpreflightを開始したsource baselineである。実際にtagを付ける最終release commitは、このPhase A draft PRのreview／merge後に`main`上で改めて明示的に固定し、Phase Cの別承認前に再確認する必要がある。

read-only確認では、local tag、remote tag、GitHub Releaseのいずれにも`v0.1.0`は存在しなかった。既存tag／Releaseの削除、移動、上書き、再作成は行っていない。

## Credential availability

| 項目 | 確認結果 |
|---|---|
| Developer ID | **NOT AVAILABLE** (`security find-identity -v -p codesigning`: 0 valid identities) |
| Notary profile | **NOT CONFIGURED** (`RESEARCH_RAG_NOTARY_PROFILE`未設定) |
| Release identity configuration | `RESEARCH_RAG_DEVELOPER_ID_APPLICATION`未設定 |
| Phase B | **NOT CURRENTLY POSSIBLE** |

この確認ではsecretを表示せず、certificate export、Keychain変更、Appleへの通信を行っていない。profile名が将来設定されても、Appleが受理することの確認はPhase Bに属する。

## Automated validation

- `QT_QPA_PLATFORM=offscreen python -X faulthandler -m pytest`: **442 passed**, 5 warnings
- worker／MainWindow focused suite: **48 passed × 5 fresh processes**（各回faulthandler有効）
- `git diff --check`: **passed**
- 通常pytestは実Ollama／networkへ接続していない

## Credential-free application and DMG

FileProvider／xattrの影響を避けるため、tracked `main` sourceを通常の一時filesystemへ展開し、既存helperだけでrelease-like smokeを行った。

- `build_macos_app.sh --dry-run`: passed
- deterministic ICNS generation: passed
- official `pyside6-deploy` standalone build: passed
- application: `Research RAG.app`, 171 MB、Mach-O `arm64`
- required QtCore runtimeとCocoa platform plugin: present
- Info.plist:
  - `CFBundleIdentifier=io.github.atraz-yuya.research-rag`
  - `CFBundleShortVersionString=0.1.0`
  - `CFBundleVersion=0.1.0`
  - `CFBundleIconFile=ResearchRAG.icns`
- local ad-hoc signature: `codesign --verify --deep --strict` passed
- app bundleに`indexes.sqlite3`、`settings.ini`、PDFが含まれないことを確認
- credential-free DMG: `Research-RAG-0.1.0-macos-arm64.dmg`, 68 MB
- `hdiutil verify`: passed
- read-only mount内容: `Research RAG.app`と`Applications -> /Applications`の2項目だけ
- mounted appを安全な一時directoryへcopyし、strict signatureを再確認
- source tree、virtual environment、`PYTHONPATH`なしでpackaged GUIがoffscreen event loopへ到達
- runtime DB／settingsの解決先はapp bundle外のQStandardPaths application data locationで、bundle内には生成されない
- `/Applications`へ書き込まず、DMGをclean detach

credential-free smoke DMGのSHA-256は`e7e7e2bdd5dee2fc6a8a1531dfedc3e47887e76145fe2f5ad9b255b49acee019`だった。これは一時preflight artifactの識別用であり、Developer ID署名／notarization／stapling後に作る正式release checksumではない。

## Real Ollama smoke

ローカルOllama `0.32.6`と既に導入済みのdefault modelを使い、非公開資料を使用しない合成3ページPDFをproduction RAG serviceへ通した。

- embedding model: `qwen3-embedding:0.6b`
- embedding result: 1024 dimensions
- generation model: `qwen3:4b-instruct`
- question: `How many nesting pairs did the Meridian field station record in May 2025?`
- answer: `27`
- citation: rank 1、`meridian-field-report.pdf`、1始まりp.2、score `0.883073`
- source textに`27 nesting pairs`を含むことを確認

modelのdownloadやdefault変更は行っていない。

## Readiness decision and remaining gates

Phase Aのsource、test、credential-free app／DMG、実Ollama smokeはpassedした。RC verdictは引き続き`PASS WITH KNOWN LIMITATIONS`である。ただしDeveloper ID identityとnotary profileがないため、適切な公開用macOS releaseに必要なPhase Bは現時点で実行できない。

残る作業は次のとおりで、各phaseには新しい明示承認が必要である。

1. Phase A draft PRをreviewし、必要なら`main`へ人間がmergeする
2. credentialを準備し、別承認後にPhase BのDeveloper ID signing／notarization／stapling／post-staple checksumを実行する
3. 別承認後、正確な`main` commitへ`v0.1.0` tagを作り、draft GitHub Releaseとartifactを用意する
4. downloadしたdraft artifactを手動smokeする
5. さらに別の明示承認後にGitHub Releaseをpublishする

Phase AではDeveloper ID release build、Apple notarization、Git tag作成／push、GitHub Release作成／変更、asset upload、publish、`main` mergeを行っていない。
