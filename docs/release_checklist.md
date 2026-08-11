# macOS Release Checklist

このchecklistは、Research RAGのmacOS DMGを外部公開するときに上から順に確認する。helperはdraftまでしか作成せず、最後のpublishは必ず人間が行う。

Issue 031 Phase Aで完了したpreflight evidenceは[`release_readiness_v0.1.0.md`](release_readiness_v0.1.0.md)に記録した。以下のcheckboxは実際のrelease artifactに対する作業記録として残し、credential-free preflightだけではDeveloper ID／notarization／tag／publish項目を完了扱いにしない。

## Source and tests

- [ ] `pyproject.toml`の`[project].version`を意図して更新した
- [ ] release対象commitと差分をreviewした
- [ ] offscreen／faulthandler付きfull pytestが成功した
- [ ] worker／MainWindow teardown testが複数fresh processで成功した
- [ ] `git diff --check`が成功した

## Local application and icon

- [ ] `scripts/generate_app_icon.py`でreal `.icns`を生成した
- [ ] local `Research RAG.app` buildが成功した
- [ ] `Contents/Resources/ResearchRAG.icns`が存在する
- [ ] Info.plistのbundle identifier、両version、`CFBundleIconFile`が正しい
- [ ] Finderで専用iconを確認した
- [ ] local ad-hoc signatureのstrict verificationが成功した
- [ ] Ollamaなしでempty GUIが起動した
- [ ] DB／settingsがapp bundle外のQStandardPaths側にある

## Local DMG smoke

- [ ] credential-free local DMGを作成した
- [ ] `hdiutil verify`が成功した
- [ ] DMGをread-only mountできた
- [ ] 内容が`Research RAG.app`と`Applications` symlinkだけである
- [ ] `Applications` symlinkが正確に`/Applications`を指す
- [ ] mounted appを安全な一時領域へcopyして起動した
- [ ] DMGをclean detachした

## Developer ID and notarization

- [ ] Developer ID Application identityをKeychainで確認した
- [ ] notarytool Keychain profileを確認した
- [ ] NuitkaがappをDeveloper ID署名した
- [ ] appのhardened runtime、timestamp、authority、entitlementsを検証した
- [ ] final architecture labelを実行ファイルから確認した
- [ ] DMGをDeveloper ID Applicationで署名した
- [ ] DMGを`hdiutil verify`した
- [ ] DMG自体のnotarization statusが`Accepted`になった
- [ ] DMGへticketをstapleし、stapler validateした
- [ ] final codesign／hdiutil／Gatekeeper検証が成功した
- [ ] stapling後の最終DMGからSHA-256 checksumを生成した

## Tag and draft GitHub Release

- [ ] 既存の`v<version>` tagが意図したcommitを指す
- [ ] tagがremoteへ明示的にpush済みである
- [ ] `prepare_github_release.sh --dry-run`の表示を確認した
- [ ] GitHub Releaseを`--verify-tag --draft`で作成した
- [ ] version／architecture付きDMGとchecksumが添付されている
- [ ] release notesをreviewした
- [ ] draftからDMGとchecksumをdownloadし、checksumを再確認した
- [ ] downloaded DMGのmount、drag-copy、empty GUI、実Ollama質問を手動確認した
- [ ] known limitationsと必要modelをrelease notes／READMEで確認した

## Manual publication

- [ ] ここまでの全項目を人間が確認した
- [ ] draft GitHub Releaseの`Publish release`を人間が明示的に実行した
