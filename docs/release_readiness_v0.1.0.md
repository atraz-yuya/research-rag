# v0.1.0 Local-use Readiness

確認日: 2026-08-11

この文書はIssue 031 Phase Aのrelease-state安全確認と、credential-freeな最終preflightの証拠を記録する。2026-08-11の方針変更により、このpreflightで検証したad-hoc signed／non-notarized `.app`／DMGをv0.1.0のlocal-use完成地点とする。製品機能の詳細なE2E結果は[RC validation report](release_candidate_v0.1.0.md)を参照する。

## Source and release state

| 項目 | 確認結果 |
|---|---|
| Phase A開始時の`main` | `346e6b0f578435a93dca521afb7534e90575d91b` |
| source candidate | `346e6b0f578435a93dca521afb7534e90575d91b`（Issue 030のmerge commit） |
| project version | `0.1.0` (`pyproject.toml`) |
| tag policy | 現在のlocal-use goalでは作成しない |
| bundle identifier | `io.github.atraz-yuya.research-rag` |
| validated architecture | Apple Silicon `arm64` |
| RC verdict | `PASS WITH KNOWN LIMITATIONS` |

Phase Aではtracked completion notes／readiness recordを追加した。現在のlocal-use goalではrelease commitの固定、tag作成、GitHub Release作成を行わない。

read-only確認では、local tag、remote tag、GitHub Releaseのいずれにも`v0.1.0`は存在しなかった。既存tag／Releaseの削除、移動、上書き、再作成は行っていない。

## Credential availability

| 項目 | 確認結果 |
|---|---|
| Developer ID | **NOT AVAILABLE** (`security find-identity -v -p codesigning`: 0 valid identities) |
| Notary profile | **NOT CONFIGURED** (`RESEARCH_RAG_NOTARY_PROFILE`未設定) |
| Release identity configuration | `RESEARCH_RAG_DEVELOPER_ID_APPLICATION`未設定 |
| Phase B | **DEFERRED / OUT OF CURRENT GOAL** |

この確認ではsecretを表示せず、certificate export、Keychain変更、Appleへの通信を行っていない。Developer ID identity／notary profileがないことは、ad-hoc signed／non-notarized artifactを自分のMacで使う現在のgoalに対するblockerではない。

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

credential-free smoke DMGのSHA-256は`e7e7e2bdd5dee2fc6a8a1531dfedc3e47887e76145fe2f5ad9b255b49acee019`だった。これは一時preflight artifactの識別用であり、public release assetのchecksumではない。

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

## Local-use completion decision

Phase Aのsource、test、credential-free app／DMG、実Ollama smokeはpassedした。RC verdictは引き続き`PASS WITH KNOWN LIMITATIONS`であり、v0.1.0のlocal-use goalは**ACHIEVED**と判断する。対象は、自分のMacで利用するApple Silicon arm64のad-hoc signed／non-notarized artifactである。

Apple Developer Programには現時点で加入しない。したがって、次のpublic distribution作業はすべてdeferredであり、現在のgoalでは実行しない。

- Developer ID signing、notarization、stapling、Gatekeeper release assessment
- Git tag作成／push
- GitHub Release作成、asset upload、publish

public distributionを再検討するのはApple Developer Programへ加入した後とし、その場合は新しい方針と明示承認のもとでrelease workflowを再開する。現時点ではDeveloper ID release build、Apple notarization、Git tag作成／push、GitHub Release作成／変更、asset upload、publishを行っていない。
